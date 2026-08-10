import customtkinter as ctk
import tkinter as tk
import logging
from logging.handlers import RotatingFileHandler
from tkinter import ttk, filedialog, messagebox, colorchooser, simpledialog
import os
import sys
import shutil
import tempfile
import argparse
import threading
import queue
import time
import json
import traceback
import numpy as np
from typing import Optional, List, Dict, Any, Tuple, Union
from PIL import ImageTk, Image, ImageDraw, ImageChops, ImageOps
import project_io

# --- DEPENDENCY MANAGEMENT ---
class DependencyManager:
    MISSING_LIBS: List[str] = []
    LOAD_FAILURES: List[Tuple[str, str, str]] = []
    video_processing = None
    state_manager_cls = None
    movieprint_maker = None
    movieprint_maker_module = None
    image_grid = None
    version = "0.0.0"
    
    @classmethod
    def load(cls):
        modules = [
            ("video_processing", "video_processing"),
            ("image_grid", "image_grid"),
            ("state_manager", "state_manager"),
            ("movieprint_maker", "movieprint_maker"),
            ("version", "version")
        ]

        for attr, name in modules:
            try:
                mod = __import__(name)
                setattr(cls, attr, mod)
            except Exception as e:
                error_detail = f"{type(e).__name__}: {e}"
                error_traceback = traceback.format_exc()
                cls.LOAD_FAILURES.append((name, error_detail, error_traceback))
                logging.getLogger(__name__).error(
                    "Failed to import local module '%s'", name, exc_info=True
                )
                if name != "version":
                    cls.MISSING_LIBS.append(f"{name}.py ({error_detail})")

        if cls.state_manager:
            cls.state_manager_cls = cls.state_manager.StateManager
        if cls.movieprint_maker:
            cls.movieprint_maker_module = cls.movieprint_maker
            cls.movieprint_maker = cls.movieprint_maker.execute_movieprint_generation
        if hasattr(cls, 'version') and hasattr(cls.version, '__version__'):
            cls.version = cls.version.__version__

DependencyManager.load()

# Handle TkinterDnD2
DND_ENABLED = False
try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    DND_ENABLED = True
except ImportError:
    class TkinterDnD:
        class DnDWrapper: pass
        @staticmethod
        def _require(self): pass
    DND_FILES = "DND_FILES_DUMMY"

# --- CONSTANTS ---
SETTINGS_FILE = "movieprint_gui_settings.json"
ctk.set_appearance_mode("Dark")

class Theme:
    PRESETS = {
        "Teal": {
            "BG_PRIMARY": "#020707",
            "BG_SECONDARY": "#071111",
            "BG_TERTIARY": "#102222",
            "PANEL": "#0A1717",
            "PANEL_SOFT": "#112828",
            "ACCENT_BLUE": "#00B3A4",
            "ACCENT_BLUE_HOVER": "#17D6C8",
            "ACCENT_GREEN": "#008F83",
            "ACCENT_GREEN_HOVER": "#00B3A4",
            "ACTION_GOLD": "#35E0D0",
            "ACTION_GOLD_HOVER": "#62F0E4",
            "DANGER_RED": "#00675F",
            "DANGER_RED_HOVER": "#008F83",
            "TEXT_MUTED": "#8AA7A3",
        },
        "Yellow": {
            "BG_PRIMARY": "#080704",
            "BG_SECONDARY": "#121006",
            "BG_TERTIARY": "#25200B",
            "PANEL": "#191607",
            "PANEL_SOFT": "#2B250D",
            "ACCENT_BLUE": "#E5B80B",
            "ACCENT_BLUE_HOVER": "#FFD449",
            "ACCENT_GREEN": "#C99A00",
            "ACCENT_GREEN_HOVER": "#E5B80B",
            "ACTION_GOLD": "#FFE066",
            "ACTION_GOLD_HOVER": "#FFEB91",
            "DANGER_RED": "#8A6900",
            "DANGER_RED_HOVER": "#B88C00",
            "TEXT_MUTED": "#B5AA83",
        },
        "Dark Green": {
            "BG_PRIMARY": "#020702",
            "BG_SECONDARY": "#071107",
            "BG_TERTIARY": "#112312",
            "PANEL": "#0A170B",
            "PANEL_SOFT": "#122914",
            "ACCENT_BLUE": "#2E8B43",
            "ACCENT_BLUE_HOVER": "#43A95A",
            "ACCENT_GREEN": "#1F6F32",
            "ACCENT_GREEN_HOVER": "#2E8B43",
            "ACTION_GOLD": "#69C779",
            "ACTION_GOLD_HOVER": "#83DD91",
            "DANGER_RED": "#195626",
            "DANGER_RED_HOVER": "#237235",
            "TEXT_MUTED": "#8EA68F",
        },
    }
    PRESET_NAMES = list(PRESETS.keys())
    CURRENT = "Teal"

    TEXT_MAIN = "#FFFFFF"
    TEXT_DARK = "#020707"
    BUTTON_SUBTLE = "#142020"
    BUTTON_SUBTLE_HOVER = "#1C3030"

    FONT_HEADER = ("Impact", 60)
    FONT_SUB = ("Roboto", 16)
    FONT_BOLD = ("Roboto", 12, "bold")

    @classmethod
    def apply_preset(cls, name: str):
        if name not in cls.PRESETS:
            name = "Teal"
        cls.CURRENT = name
        for key, value in cls.PRESETS[name].items():
            setattr(cls, key, value)
        cls.TEXT_DARK = cls.BG_PRIMARY
        cls.BUTTON_SUBTLE = cls.BG_TERTIARY
        cls.BUTTON_SUBTLE_HOVER = cls.PANEL_SOFT

Theme.apply_preset("Teal")

# --- LOGGING SETUP ---
def setup_file_logging():
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    
    log_dir = os.path.expanduser(os.path.join("~", ".pymovieprint", "logs"))
    try:
        os.makedirs(log_dir, exist_ok=True)
        log_file = os.path.join(log_dir, "pymovieprint.log")
        handler = RotatingFileHandler(log_file, maxBytes=5*1024*1024, backupCount=3, encoding='utf-8')
        handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
        root_logger.addHandler(handler)
    except Exception as e:
        print(f"Failed to create user profile log: {e}")

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    root_logger.addHandler(console_handler)

    for module_name, error_detail, error_traceback in DependencyManager.LOAD_FAILURES:
        root_logger.error(
            "Failed to import local module '%s' (%s):\n%s",
            module_name,
            error_detail,
            error_traceback,
        )

    def handle_exception(exc_type, exc_value, exc_traceback):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return
        logging.critical("Uncaught exception", exc_info=(exc_type, exc_value, exc_traceback))
    sys.excepthook = handle_exception

class QueueHandler(logging.Handler):
    def __init__(self, queue_instance: queue.Queue):
        super().__init__()
        self.queue = queue_instance

    def emit(self, record):
        log_entry = self.format(record)
        self.queue.put(("log", log_entry))

# --- COMPONENT: High-Performance Scrubbing ---
class ScrubbingHandler:
    def __init__(self, app: 'MoviePrintApp'):
        self.app = app
        self.active: bool = False
        self.thumbnail_index: int = -1
        self.start_x: int = 0
        self.original_timestamp: float = 0.0
        self.video_path: Optional[str] = None
        self._scrub_queue: queue.LifoQueue = queue.LifoQueue(maxsize=10)
        self._stop_event = threading.Event()
        self._worker_thread: Optional[threading.Thread] = None

    def start(self, event, thumbnail_index: int, original_timestamp: float, video_path: str):
        if not video_path or not os.path.exists(video_path): return
        
        self.active = True
        self.thumbnail_index = thumbnail_index
        self.original_timestamp = original_timestamp
        self.start_x = event.x
        self.video_path = video_path
        
        self.app.preview_zoomable_canvas.canvas.config(cursor="sb_h_double_arrow")
        self._stop_event.clear()
        
        while not self._scrub_queue.empty():
            try: self._scrub_queue.get_nowait()
            except queue.Empty: break
            
        self._worker_thread = threading.Thread(target=self._scrub_worker, daemon=True)
        self._worker_thread.start()

    def stop(self, event):
        if self.active:
            self.active = False
            self.thumbnail_index = -1
            self.app.preview_zoomable_canvas.canvas.config(cursor="")
            self._stop_event.set()
            self._scrub_queue.put(None) 
            self.app.queue.put(("log", "Scrubbing finished."))
            self.app.after(0, self.app.quick_refresh_layout)

    def handle_motion(self, event):
        if not self.active: return
        dx = event.x - self.start_x
        pixels_per_second = 50.0 
        time_offset = dx / pixels_per_second
        new_timestamp = max(0.0, self.original_timestamp + time_offset)
        try:
            self._scrub_queue.put((new_timestamp, self.thumbnail_index), block=False)
        except queue.Full: pass 

    def _scrub_worker(self):
        if not DependencyManager.video_processing: return
        VideoExtractor = DependencyManager.video_processing.VideoExtractor
        
        try:
            with VideoExtractor(self.video_path) as extractor:
                while not self._stop_event.is_set():
                    try:
                        item = self._scrub_queue.get(timeout=0.5)
                        if item is None: break 
                        
                        target_ts, thumb_idx = item
                        while not self._scrub_queue.empty():
                            try:
                                next_item = self._scrub_queue.get_nowait()
                                if next_item is None:
                                    self._stop_event.set()
                                    break
                                target_ts, thumb_idx = next_item
                            except queue.Empty: break
                        
                        if self._stop_event.is_set(): break
                        
                        frame = extractor.extract_single_frame(target_ts)
                        if frame is not None:
                            cv2 = DependencyManager.video_processing.cv2
                            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                            pil_img = Image.fromarray(frame_rgb)
                            
                            self.app.queue.put(("update_thumbnail", {
                                "index": thumb_idx, 
                                "image": pil_img, 
                                "timestamp": target_ts
                            }))
                            
                    except queue.Empty: continue 
        except Exception as e:
            logging.error(f"Scrub worker error: {e}")

# --- UI COMPONENTS ---
class ZoomableCanvas(ctk.CTkFrame):
    def __init__(self, master, app_ref: 'MoviePrintApp', **kwargs):
        super().__init__(master, **kwargs)
        self.app_ref = app_ref
        self.canvas = tk.Canvas(self, background=Theme.BG_PRIMARY, highlightthickness=0)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        
        self.vsb = ctk.CTkScrollbar(self, orientation="vertical", command=self.canvas.yview, fg_color=Theme.BG_SECONDARY)
        self.hsb = ctk.CTkScrollbar(self, orientation="horizontal", command=self.canvas.xview, fg_color=Theme.BG_SECONDARY)
        
        self.canvas.configure(yscrollcommand=self.vsb.set, xscrollcommand=self.hsb.set)
        self.vsb.grid(row=0, column=1, sticky="ns")
        self.hsb.grid(row=1, column=0, sticky="ew")
        
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)
        
        self.image_id: Optional[int] = None
        self.original_image: Optional[Image.Image] = None
        self.photo_image: Optional[ImageTk.PhotoImage] = None
        self._zoom_level: float = 1.0
        
        self.canvas.bind("<ButtonPress-1>", self.on_button_press)
        self.canvas.bind("<B1-Motion>", self.on_mouse_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_button_release)
        self.canvas.bind("<MouseWheel>", self.on_mouse_wheel) 
        self.canvas.bind("<Button-4>", self.on_mouse_wheel)   
        self.canvas.bind("<Button-5>", self.on_mouse_wheel)   
        self.canvas.bind("<Button-3>", self.app_ref.show_thumbnail_menu)
        
        if DND_ENABLED:
            try:
                self.canvas.drop_target_register(DND_FILES)
                self.canvas.dnd_bind('<<Drop>>', self.app_ref.handle_drop)
            except Exception: pass

    def on_button_press(self, event):
        if self.app_ref.is_scrubbing_active():
            self.app_ref.stop_scrubbing(event)
            return
        is_scrub_initiated = self.app_ref.start_scrubbing(event)
        if not is_scrub_initiated:
            self.canvas.scan_mark(event.x, event.y)

    def on_mouse_drag(self, event):
        if self.app_ref.is_scrubbing_active():
            self.app_ref.handle_scrubbing(event)
        else:
            self.canvas.scan_dragto(event.x, event.y, gain=1)

    def on_button_release(self, event):
        if self.app_ref.is_scrubbing_active():
            self.app_ref.stop_scrubbing(event)

    def on_mouse_wheel(self, event):
        if self.app_ref.is_scrubbing_active(): return
        zoom_step = 1.1
        if (event.num == 5 or event.delta < 0):
            new_zoom = self._zoom_level / zoom_step
        elif (event.num == 4 or event.delta > 0):
            new_zoom = self._zoom_level * zoom_step
        else:
            return

        new_zoom = max(0.1, min(5.0, new_zoom))
        self.app_ref.zoom_level_var.set(new_zoom)
        self.set_zoom(new_zoom)

    def canvas_event_to_image_coords(self, event) -> Tuple[float, float]:
        """Convert a mouse event on the zoomed canvas back to original image coords."""
        canvas_x = self.canvas.canvasx(event.x)
        canvas_y = self.canvas.canvasy(event.y)
        zoom = self._zoom_level if self._zoom_level > 0 else 1.0
        return canvas_x / zoom, canvas_y / zoom

    def set_zoom(self, scale_level: float):
        scale_level = float(scale_level)
        if self._zoom_level == scale_level: return
        self._zoom_level = scale_level
        self._apply_zoom()

    def _apply_zoom(self):
        if not self.original_image or not self.image_id: return
        
        new_width = int(self.original_image.width * self._zoom_level)
        new_height = int(self.original_image.height * self._zoom_level)
        new_width = max(1, new_width)
        new_height = max(1, new_height)
        
        resample_filter = Image.Resampling.BILINEAR if self._zoom_level < 1.0 else Image.Resampling.NEAREST
        zoomed_image = self.original_image.resize((new_width, new_height), resample_filter)
        
        display_image = zoomed_image if zoomed_image.mode in ("RGB", "RGBA", "L") else zoomed_image.convert("RGBA")
        self.photo_image = ImageTk.PhotoImage(display_image)
        self.canvas.itemconfig(self.image_id, image=self.photo_image)
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def set_image(self, image_path: str):
        if not image_path or not os.path.exists(image_path):
            self.clear()
            return
        try:
            self.original_image = Image.open(image_path)
            self.app_ref.zoom_level_var.set(1.0)
            self._zoom_level = 1.0
            display_image = self.original_image if self.original_image.mode in ("RGB", "RGBA", "L") else self.original_image.convert("RGBA")
            self.photo_image = ImageTk.PhotoImage(display_image)
            
            if self.image_id: self.canvas.delete(self.image_id)
            self.image_id = self.canvas.create_image(0, 0, anchor="nw", image=self.photo_image)
            self.canvas.configure(scrollregion=self.canvas.bbox(self.image_id))
        except Exception as e:
            logging.error(f"Error setting image: {e}")
            self.clear()

    def clear(self):
        if self.image_id: self.canvas.delete(self.image_id)
        self.image_id = None
        self.original_image = None
        self.photo_image = None
        self.canvas.configure(scrollregion=(0,0,0,0))


class VideoPlayerWindow(ctk.CTkToplevel):
    """Small OpenCV-backed player/editor that stays inside the Tk architecture."""

    def __init__(self, app_ref: 'MoviePrintApp', video_path: str):
        super().__init__(app_ref)
        self.app_ref = app_ref
        self.video_path = video_path
        self.title(f"Player - {os.path.basename(video_path)}")
        self.geometry("960x650")
        self.configure(fg_color=Theme.BG_PRIMARY)
        self.cap = DependencyManager.video_processing.cv2.VideoCapture(video_path)
        if not self.cap.isOpened():
            self.destroy()
            raise ValueError("The selected video could not be opened.")
        cv2 = DependencyManager.video_processing.cv2
        self.fps = float(self.cap.get(cv2.CAP_PROP_FPS) or 25.0)
        self.frame_count = int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        self.duration = self.frame_count / self.fps if self.fps > 0 else 0.0
        self.current_timestamp = 0.0
        self.playing = False
        self._photo = None

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self.video_label = ctk.CTkLabel(self, text="", fg_color="#000000")
        self.video_label.grid(row=0, column=0, sticky="nsew", padx=12, pady=(12, 6))

        self.position_var = tk.DoubleVar(value=0.0)
        self.position_slider = ctk.CTkSlider(
            self, from_=0, to=max(self.duration, 0.001), variable=self.position_var,
            command=self._seek, progress_color=Theme.ACCENT_BLUE,
        )
        self.position_slider.grid(row=1, column=0, sticky="ew", padx=12)

        controls = ctk.CTkFrame(self, fg_color="transparent")
        controls.grid(row=2, column=0, pady=(6, 12))
        self.play_button = ctk.CTkButton(controls, text="PLAY", width=90, command=self.toggle_play)
        self.play_button.pack(side="left", padx=4)
        ctk.CTkButton(controls, text="-1s", width=60, command=lambda: self.seek_to(self.current_timestamp - 1)).pack(side="left", padx=4)
        ctk.CTkButton(controls, text="+1s", width=60, command=lambda: self.seek_to(self.current_timestamp + 1)).pack(side="left", padx=4)
        ctk.CTkButton(controls, text="USE FOR SELECTED", width=150, command=self._replace_selected).pack(side="left", padx=4)
        self.time_label = ctk.CTkLabel(controls, text="00:00.000", text_color=Theme.TEXT_MUTED)
        self.time_label.pack(side="left", padx=12)

        self.protocol("WM_DELETE_WINDOW", self.close)
        self.seek_to(0.0)

    def _seek(self, value):
        self.seek_to(float(value))

    def seek_to(self, timestamp: float):
        cv2 = DependencyManager.video_processing.cv2
        self.current_timestamp = max(0.0, min(float(timestamp), self.duration))
        self.position_var.set(self.current_timestamp)
        self.cap.set(cv2.CAP_PROP_POS_MSEC, self.current_timestamp * 1000.0)
        ok, frame = self.cap.read()
        if not ok:
            return
        frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        image = Image.fromarray(frame)
        max_w = max(320, self.winfo_width() - 40)
        max_h = max(200, self.winfo_height() - 150)
        image.thumbnail((max_w, max_h), Image.Resampling.LANCZOS)
        self._photo = ctk.CTkImage(light_image=image, dark_image=image, size=image.size)
        self.video_label.configure(image=self._photo)
        minutes, seconds = divmod(self.current_timestamp, 60)
        hours, minutes = divmod(int(minutes), 60)
        prefix = f"{hours:02d}:" if hours else ""
        self.time_label.configure(text=f"{prefix}{minutes:02d}:{seconds:06.3f}")

    def toggle_play(self):
        self.playing = not self.playing
        self.play_button.configure(text="PAUSE" if self.playing else "PLAY")
        if self.playing:
            self._tick()

    def _tick(self):
        if not self.playing or not self.winfo_exists():
            return
        next_timestamp = self.current_timestamp + max(1.0 / max(self.fps, 1.0), 0.033)
        if next_timestamp >= self.duration:
            self.playing = False
            self.play_button.configure(text="PLAY")
            return
        self.seek_to(next_timestamp)
        self.after(max(15, round(1000 / max(self.fps, 1.0))), self._tick)

    def _replace_selected(self):
        self.app_ref.replace_selected_thumbnail(self.current_timestamp)

    def close(self):
        self.playing = False
        if self.cap:
            self.cap.release()
        if self.app_ref.player_window is self:
            self.app_ref.player_window = None
        self.destroy()

class CTkCollapsibleFrame(ctk.CTkFrame):
    def __init__(self, master, title="", start_open=True, **kwargs):
        super().__init__(master, **kwargs)
        self.grid_columnconfigure(0, weight=1)
        self.variable = ctk.BooleanVar(value=start_open)
        self.title_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.title_frame.grid(row=0, column=0, sticky="ew")
        self.title_frame.grid_columnconfigure(1, weight=1)
        self.toggle_button = ctk.CTkButton(
            self.title_frame, text=f"{'-' if start_open else '+'} {title}", command=self.toggle, width=30,
            fg_color="transparent", text_color=Theme.ACCENT_BLUE, hover=False, anchor="w", font=Theme.FONT_BOLD
        )
        self.toggle_button.grid(row=0, column=0, sticky="w")
        self.sub_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.sub_frame.grid(row=1, column=0, sticky="nsew", padx=10, pady=5)
        if not start_open:
            self.sub_frame.grid_remove()

    def toggle(self):
        if self.variable.get():
            self.variable.set(False)
            self.sub_frame.grid_remove()
            self.toggle_button.configure(text=f"+ {self.toggle_button.cget('text')[2:]}")
        else:
            self.variable.set(True)
            self.sub_frame.grid()
            self.toggle_button.configure(text=f"- {self.toggle_button.cget('text')[2:]}")
    
    def get_content_frame(self): return self.sub_frame

# --- MAIN APPLICATION ---
class MoviePrintApp(ctk.CTk, TkinterDnD.DnDWrapper):
    def __init__(self):
        super().__init__()
        
        if DependencyManager.MISSING_LIBS:
            self.withdraw()
            error_msg = "Required dependencies missing:\n" + "\n".join(DependencyManager.MISSING_LIBS)
            messagebox.showerror("Startup Error", error_msg)
            sys.exit(1)

        self.title(f"PyMoviePrint Generator v{DependencyManager.version}")
        self.geometry("1500x950")
        Theme.apply_preset(self._read_persistent_ui_theme())
        self.configure(fg_color=Theme.BG_PRIMARY)
        
        self._init_dnd()
        self.scrubbing_handler = ScrubbingHandler(self)
        self.temp_dirs_to_cleanup: List[str] = []
        self._internal_input_paths: List[str] = []
        self.batch_file_list: List[str] = [] 
        self.queue = queue.Queue()
        self.preview_temp_dir: Optional[str] = None
        self.is_landing_state = True
        self.is_busy = False
        self.active_cancel_event = None
        self.active_job_kind = None
        self._applying_theme = False
        self._loading_persistent_settings = False
        self.current_project_path: Optional[str] = None
        self.selected_thumbnail_index: Optional[int] = None
        self.player_window: Optional[VideoPlayerWindow] = None
        
        self.state_manager = DependencyManager.state_manager_cls()
        self._init_variables_dynamic()
        self._bind_settings_to_state()
        
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self._build_sidebar()
        self._build_main_area()
        self._build_toolbar()
        self._build_action_footer()

        self._load_persistent_settings()
        self._start_queue_poller()
        
        self.protocol("WM_DELETE_WINDOW", self._on_closing)
        self.bind("<Control-z>", self.perform_undo)
        self.bind("<Control-y>", self.perform_redo)
        self._update_live_math()

    @staticmethod
    def _read_persistent_ui_theme():
        try:
            if os.path.exists(SETTINGS_FILE):
                with open(SETTINGS_FILE, 'r') as f:
                    return json.load(f).get("ui_theme", "Teal")
        except Exception:
            pass
        return "Teal"

    def _init_dnd(self):
        self.dnd_active = False
        if DND_ENABLED:
            try:
                self.TkdndVersion = TkinterDnD._require(self)
                self.dnd_active = True
            except Exception: pass
    
    def _init_variables_dynamic(self):
        default_settings = self.state_manager.get_settings()
        self.settings_map = {}
        
        self.input_paths_var = tk.StringVar(value="")
        self.zoom_level_var = tk.DoubleVar(value=1.0)
        
        self.output_naming_mode_var = tk.StringVar(value=default_settings.output_naming_mode)
        self.naming_mode_display_var = tk.StringVar(
            value="Fixed Name" if default_settings.output_naming_mode == "custom" else "Add Suffix"
        )
        self.output_filename_suffix_var = tk.StringVar(value=default_settings.output_filename_suffix)
        self.output_filename_var = tk.StringVar(value=default_settings.output_filename)

        self.settings_map["input_paths_var"] = "input_paths"
        self.settings_map["output_naming_mode_var"] = "output_naming_mode"
        self.settings_map["output_filename_suffix_var"] = "output_filename_suffix"
        self.settings_map["output_filename_var"] = "output_filename"
        
        # New Settings Maps
        self.settings_map["recursive_scan_var"] = "recursive_scan"
        self.settings_map["overwrite_mode_var"] = "overwrite_mode"

        for field_name, field_val in vars(default_settings).items():
            if field_name in ["input_paths", "output_naming_mode", "output_filename_suffix", "output_filename"]: continue
            
            tk_var_name = f"{field_name}_var"
            
            if isinstance(field_val, bool):
                setattr(self, tk_var_name, tk.BooleanVar(value=field_val))
            elif isinstance(field_val, int):
                setattr(self, tk_var_name, tk.IntVar(value=field_val))
            elif isinstance(field_val, float):
                setattr(self, tk_var_name, tk.DoubleVar(value=field_val))
            else:
                val = str(field_val) if field_val is not None else ""
                setattr(self, tk_var_name, tk.StringVar(value=val))
            
            self.settings_map[tk_var_name] = field_name
        
        try:
            has_gpu = DependencyManager.video_processing.VideoUtils.check_ffmpeg_gpu(logging.getLogger())
            if hasattr(self, "use_gpu_var"):
                self.use_gpu_var.set(has_gpu)
        except Exception: pass

    def _build_sidebar(self):
        self.sidebar_frame = ctk.CTkScrollableFrame(self, width=350, corner_radius=0, fg_color=Theme.BG_SECONDARY)
        self.sidebar_frame.grid(row=0, column=0, sticky="nsew")
        self._create_grid_controller(self.sidebar_frame)

    def _build_main_area(self):
        self.main_area = ctk.CTkFrame(self, fg_color=Theme.BG_PRIMARY, corner_radius=0)
        self.main_area.grid(row=0, column=1, sticky="nsew", padx=0, pady=0)
        self.main_area.grid_rowconfigure(0, weight=1)
        self.main_area.grid_columnconfigure(0, weight=1)
        self.preview_zoomable_canvas = ZoomableCanvas(self.main_area, app_ref=self)
        self.landing_frame = ctk.CTkFrame(self.main_area, fg_color=Theme.BG_PRIMARY)
        self.landing_frame.grid(row=0, column=0, sticky="nsew")
        self._create_landing_page(self.landing_frame)

    def _build_toolbar(self):
        self.toolbar_frame = ctk.CTkFrame(self, fg_color=Theme.BG_PRIMARY)
        self.toolbar_frame.grid(row=1, column=1, sticky="ew", padx=10, pady=(4, 2))
        project_row = ctk.CTkFrame(self.toolbar_frame, fg_color="transparent")
        project_row.pack(fill="x")
        for label, command in (
            ("OPEN PROJECT", self.open_project_action),
            ("SAVE PROJECT", self.save_project_action),
            ("PLAYER", self.open_player),
        ):
            ctk.CTkButton(
                project_row, text=label, command=command, height=26,
                fg_color=Theme.BUTTON_SUBTLE, hover_color=Theme.BUTTON_SUBTLE_HOVER,
            ).pack(side="left", padx=(0, 5))

        ctk.CTkLabel(project_row, text="Sheet:", text_color=Theme.TEXT_MUTED).pack(side="left", padx=(8, 3))
        self.sheet_display_var = tk.StringVar(value="Sheet 1")
        self.sheet_combo = ctk.CTkComboBox(
            project_row, width=150, variable=self.sheet_display_var,
            values=["Sheet 1"], command=self._on_sheet_selected,
        )
        self.sheet_combo.pack(side="left", padx=3)
        ctk.CTkButton(project_row, text="+", width=30, height=26, command=self.add_sheet).pack(side="left", padx=2)
        ctk.CTkButton(project_row, text="DUP", width=44, height=26, command=self.duplicate_sheet).pack(side="left", padx=2)
        ctk.CTkButton(project_row, text="-", width=30, height=26, command=self.delete_sheet).pack(side="left", padx=2)

        ctk.CTkLabel(project_row, text="Sort:", text_color=Theme.TEXT_MUTED).pack(side="left", padx=(12, 3))
        self.sort_combo = ctk.CTkComboBox(
            project_row, width=125, values=["timestamp", "timestamp_desc", "frame", "duration", "faces", "manual"],
            variable=self.sort_mode_var, command=lambda _value: self.quick_refresh_layout(),
        )
        self.sort_combo.pack(side="left", padx=3)
        self.hidden_switch = ctk.CTkSwitch(
            project_row, text="Show hidden", command=self._toggle_hidden_filter,
            progress_color=Theme.ACCENT_GREEN,
        )
        self.hidden_switch.pack(side="left", padx=8)

        zoom_row = ctk.CTkFrame(self.toolbar_frame, fg_color="transparent")
        zoom_row.pack(fill="x", pady=(3, 0))
        ctk.CTkLabel(zoom_row, text="Zoom:", text_color=Theme.TEXT_MUTED).pack(side="left", padx=5)
        self.zoom_slider = ctk.CTkSlider(zoom_row, from_=0.1, to=5.0, variable=self.zoom_level_var,
                                        command=self.preview_zoomable_canvas.set_zoom, width=150, progress_color=Theme.ACCENT_BLUE)
        self.zoom_slider.pack(side="left", padx=5)
        ctk.CTkLabel(
            zoom_row, text="Right-click a thumbnail to edit it; drag horizontally to scrub.",
            text_color=Theme.TEXT_MUTED,
        ).pack(side="left", padx=12)
        self._refresh_sheet_controls()

    def _build_action_footer(self):
        self.action_frame = ctk.CTkFrame(self, height=60, fg_color=Theme.BG_SECONDARY)
        self.action_frame.grid(row=2, column=0, columnspan=2, sticky="ew")
        self.action_frame.grid_columnconfigure(0, weight=1)
        
        self.status_lbl = ctk.CTkLabel(self.action_frame, text="Ready", text_color=Theme.TEXT_MUTED)
        self.status_lbl.grid(row=0, column=0, sticky="w", padx=20)
        
        self.progress_bar = ctk.CTkProgressBar(self.action_frame, width=300, progress_color=Theme.ACCENT_GREEN)
        self.progress_bar.set(0)
        self.progress_bar.grid(row=0, column=1, padx=20)
        
        btn_frame = ctk.CTkFrame(self.action_frame, fg_color="transparent")
        btn_frame.grid(row=0, column=2, sticky="e", padx=20, pady=10)
        
        self.preview_btn = ctk.CTkButton(btn_frame, text="PREVIEW", command=self.start_thumbnail_preview_generation,
                      fg_color="transparent", border_width=1, border_color=Theme.ACCENT_BLUE,
                      text_color=Theme.ACCENT_BLUE, hover_color=Theme.BUTTON_SUBTLE_HOVER)
        self.preview_btn.pack(side="left", padx=5)

        self.cancel_btn = ctk.CTkButton(
            btn_frame, text="CANCEL", command=self.cancel_active_job, width=86,
            fg_color="transparent", border_width=1, border_color=Theme.DANGER_RED,
            text_color=Theme.DANGER_RED_HOVER, hover_color=Theme.BUTTON_SUBTLE_HOVER,
        )
        self.cancel_btn.pack(side="left", padx=5)
        self.cancel_btn.configure(state="disabled")
        
        self.save_btn = ctk.CTkButton(btn_frame, text="GENERATE", command=self.generate_movieprint_action,
                                      fg_color=Theme.ACTION_GOLD, text_color=Theme.TEXT_DARK,
                                      hover_color=Theme.ACTION_GOLD_HOVER, font=Theme.FONT_BOLD, width=150)
        self.save_btn.pack(side="left", padx=5)

    def _create_landing_page(self, parent):
        parent.grid_columnconfigure(0, weight=1)
        parent.grid_rowconfigure(0, weight=1)
        parent.grid_rowconfigure(4, weight=1)
        
        ctk.CTkLabel(parent, text="PYMOVIEPRINT", font=Theme.FONT_HEADER, text_color=Theme.TEXT_MAIN).grid(row=1, column=0, pady=(20, 5))
        ctk.CTkLabel(parent, text="create screenshots of entire movies in an instant.", font=Theme.FONT_SUB, text_color=Theme.TEXT_MUTED).grid(row=2, column=0, pady=(0, 30))
        
        self.hero_canvas = ctk.CTkCanvas(parent, width=500, height=300, bg=Theme.BG_PRIMARY, highlightthickness=0)
        self.hero_canvas.grid(row=3, column=0, pady=20)
        self._draw_masonry_placeholder()
        
        workflow_frame = ctk.CTkFrame(parent, fg_color="transparent")
        workflow_frame.grid(row=5, column=0, pady=40)
        steps = [
            ("1", "Drag & Drop", "Video files", Theme.ACCENT_BLUE),
            ("2", "Customize", "Layout & Style", Theme.ACCENT_GREEN),
            ("3", "Save", "Export Image", Theme.ACTION_GOLD),
        ]
        
        for i, (num, title, desc, color) in enumerate(steps):
            f = ctk.CTkFrame(workflow_frame, fg_color="transparent")
            f.grid(row=0, column=i, padx=40)
            ctk.CTkLabel(f, text=num, font=("Roboto", 40, "bold"), text_color=color).pack()
            ctk.CTkLabel(f, text=title, font=Theme.FONT_BOLD, text_color=Theme.TEXT_MAIN).pack()
            ctk.CTkLabel(f, text=desc, font=("Roboto", 12), text_color=Theme.TEXT_MUTED).pack()
            
        if self.dnd_active:
            try:
                parent.drop_target_register(DND_FILES)
                parent.dnd_bind('<<Drop>>', self.handle_drop)
                self.hero_canvas.drop_target_register(DND_FILES)
                self.hero_canvas.dnd_bind('<<Drop>>', self.handle_drop)
            except Exception: pass

    def _draw_masonry_placeholder(self):
        """
        Replaces the random 'masonry' look with a structured 16:9 grid (Brand Identity).
        Kept the name '_draw_masonry_placeholder' to ensure compatibility with existing calls.
        """
        self.hero_canvas.delete("all")
        
        # Canvas dimensions (fixed to match _create_landing_page init)
        w, h = 500, 300
        
        # Grid Configuration
        cols = 4
        rows = 3
        gap = 12  # Spacing between frames
        
        color_frame = Theme.BG_TERTIARY
        color_tc = Theme.PANEL_SOFT
        color_highlight = Theme.ACCENT_BLUE
        
        # Calculate cell dimensions to fit perfectly with gaps
        # Formula: Total Width = (Cols * CellW) + ((Cols + 1) * Gap)
        cell_w = (w - (gap * (cols + 1))) / cols
        cell_h = (h - (gap * (rows + 1))) / rows
        
        for r in range(rows):
            for c in range(cols):
                # Calculate coordinates
                x1 = gap + c * (cell_w + gap)
                y1 = gap + r * (cell_h + gap)
                x2 = x1 + cell_w
                y2 = y1 + cell_h
                
                # Draw the "Video Frame"
                self.hero_canvas.create_rectangle(x1, y1, x2, y2, fill=color_frame, outline="")
                
                # Draw a subtle "Timecode/Metadata" strip at the bottom of each frame
                # This makes it look like a technical tool, not just boxes
                tc_h = cell_h * 0.15 # 15% height
                tc_y1 = y2 - tc_h
                
                self.hero_canvas.create_rectangle(x1, tc_y1, x2, y2, fill=color_tc, outline="")
                
                # Draw a tiny "cyan accent" on the first frame to suggest "Selection" or "Start"
                if r == 0 and c == 0:
                    self.hero_canvas.create_rectangle(x1, y2-2, x1 + (cell_w * 0.3), y2, fill=color_highlight, outline="")

    def _create_grid_controller(self, parent):
        self.live_math_frame = ctk.CTkFrame(parent, fg_color=Theme.PANEL_SOFT, corner_radius=8)
        self.live_math_frame.pack(fill="x", padx=10, pady=20)
        font_lg = ("Roboto", 32, "bold")
        
        self.math_lbl_cols = ctk.CTkLabel(self.live_math_frame, text="5", font=font_lg, text_color="white")
        self.math_lbl_cols.pack(side="left", expand=True)
        ctk.CTkLabel(self.live_math_frame, text="x", font=("Roboto", 24), text_color=Theme.TEXT_MUTED).pack(side="left")
        self.math_lbl_rows = ctk.CTkLabel(self.live_math_frame, text="?", font=font_lg, text_color="white")
        self.math_lbl_rows.pack(side="left", expand=True)
        ctk.CTkLabel(self.live_math_frame, text="=", font=("Roboto", 24), text_color=Theme.TEXT_MUTED).pack(side="left")
        self.math_lbl_res = ctk.CTkLabel(self.live_math_frame, text="?", font=font_lg, text_color=Theme.ACTION_GOLD)
        self.math_lbl_res.pack(side="left", expand=True)

        self.input_tabs = ctk.CTkTabview(parent, fg_color=Theme.PANEL, text_color=Theme.TEXT_MAIN,
                                         segmented_button_selected_color=Theme.ACCENT_BLUE,
                                         segmented_button_selected_hover_color=Theme.ACCENT_BLUE_HOVER,
                                         command=self._on_tab_change)
        self.input_tabs.pack(fill="x", padx=10, pady=(0, 5))
        self.input_tabs.add("Single Source")
        self.input_tabs.add("Batch Queue")
        
        single_tab = self.input_tabs.tab("Single Source")
        self.input_entry = ctk.CTkEntry(single_tab, textvariable=self.input_paths_var, placeholder_text="Drag file here...", border_color=Theme.BG_TERTIARY)
        self.input_entry.pack(fill="x", padx=0, pady=(10,5))
        if self.dnd_active:
            try:
                self.input_entry.drop_target_register(DND_FILES)
                self.input_entry.dnd_bind('<<Drop>>', self.handle_drop)
            except Exception: pass
        ctk.CTkButton(single_tab, text="Browse", command=self.browse_input_paths, fg_color=Theme.ACCENT_BLUE,
                      text_color=Theme.TEXT_MAIN, hover_color=Theme.ACCENT_BLUE_HOVER).pack(fill="x", padx=0, pady=10)

        batch_tab = self.input_tabs.tab("Batch Queue")
        list_container = ctk.CTkFrame(batch_tab, fg_color=Theme.BG_TERTIARY, height=150)
        list_container.pack(fill="x", padx=0, pady=(10,5))
        list_container.pack_propagate(False)
        self.batch_listbox = tk.Listbox(list_container, bg=Theme.BG_TERTIARY, fg="white", borderwidth=0, highlightthickness=0, selectmode="extended")
        self.batch_listbox.pack(side="left", fill="both", expand=True, padx=5, pady=5)
        scrollbar = ctk.CTkScrollbar(list_container, command=self.batch_listbox.yview, fg_color="transparent")
        scrollbar.pack(side="right", fill="y")
        self.batch_listbox.config(yscrollcommand=scrollbar.set)
        if self.dnd_active:
             try:
                self.batch_listbox.drop_target_register(DND_FILES)
                self.batch_listbox.dnd_bind('<<Drop>>', self.handle_drop)
             except Exception: pass
        batch_ctrl_frame = ctk.CTkFrame(batch_tab, fg_color="transparent")
        batch_ctrl_frame.pack(fill="x", pady=5)
        ctk.CTkButton(batch_ctrl_frame, text="Add Files", command=self.browse_batch_files, width=86,
                      fg_color=Theme.ACCENT_BLUE, hover_color=Theme.ACCENT_BLUE_HOVER).pack(side="left", padx=(0, 5))
        ctk.CTkButton(batch_ctrl_frame, text="Add Folder", command=self.browse_batch_folder, width=96,
                      fg_color=Theme.BUTTON_SUBTLE, hover_color=Theme.BUTTON_SUBTLE_HOVER).pack(side="left", padx=(0, 5))
        ctk.CTkButton(batch_ctrl_frame, text="Clear", command=self.clear_batch_list, width=60,
                      fg_color=Theme.DANGER_RED, hover_color=Theme.DANGER_RED_HOVER).pack(side="left", padx=(0,5))
        ctk.CTkButton(batch_ctrl_frame, text="Remove Selected", command=self.remove_batch_item, width=120,
                      fg_color="transparent", border_width=1, border_color=Theme.DANGER_RED,
                      text_color=Theme.DANGER_RED_HOVER, hover_color=Theme.BUTTON_SUBTLE_HOVER).pack(side="left")
        
        # --- NEW: Recursive Checkbox ---
        ctk.CTkCheckBox(parent, text="Recursive Folder Scan", variable=self.recursive_scan_var, 
                        text_color=Theme.TEXT_MUTED, fg_color=Theme.ACCENT_GREEN,
                        hover_color=Theme.ACCENT_GREEN_HOVER).pack(fill="x", padx=15, pady=(0, 10))

        self._create_cyber_slider_section(parent)
        
        # --- NEW: Output Dimensions Section ---
        dims_frame = CTkCollapsibleFrame(parent, title="Output")
        dims_frame.pack(fill="x", padx=10, pady=5)
        self._populate_dimensions_settings(dims_frame.get_content_frame())

        adv_frame = CTkCollapsibleFrame(parent, title="Advanced", start_open=False)
        adv_frame.pack(fill="x", padx=10, pady=5)
        self._populate_advanced_settings(adv_frame.get_content_frame())

        hdr_frame = CTkCollapsibleFrame(parent, title="HDR & Color", start_open=False)
        hdr_frame.pack(fill="x", padx=10, pady=5)
        self._populate_hdr_settings(hdr_frame.get_content_frame())

    def _create_cyber_slider_section(self, parent):
        self.slider_frame = ctk.CTkFrame(parent, fg_color=Theme.PANEL, corner_radius=8)
        self.slider_frame.pack(fill="x", padx=10, pady=10)
        
        ctk.CTkLabel(self.slider_frame, text="COLUMNS", font=Theme.FONT_BOLD, text_color=Theme.TEXT_MAIN).pack(anchor="w")
        self.col_slider = ctk.CTkSlider(self.slider_frame, from_=1, to=20, number_of_steps=19, variable=None,
                                       command=self._on_col_slider_change, progress_color=Theme.ACCENT_BLUE,
                                       button_color=Theme.ACCENT_BLUE, button_hover_color=Theme.ACCENT_BLUE_HOVER)
        self.col_slider.set(5)
        self.col_slider.pack(fill="x", pady=(0, 15))
        
        ctk.CTkLabel(self.slider_frame, text="ROWS", font=Theme.FONT_BOLD, text_color=Theme.TEXT_MAIN).pack(anchor="w")
        self.row_slider = ctk.CTkSlider(self.slider_frame, from_=1, to=20, number_of_steps=19, variable=None,
                                       command=self._on_row_slider_change, progress_color=Theme.ACCENT_GREEN,
                                       button_color=Theme.ACCENT_GREEN, button_hover_color=Theme.ACCENT_GREEN_HOVER)
        self.row_slider.set(5)
        self.row_slider.pack(fill="x", pady=(0, 15))

    def _populate_dimensions_settings(self, parent):
        # Fit Toggle
        self.fit_switch = ctk.CTkSwitch(parent, text="Force Fit to Resolution", variable=self.fit_to_output_params_var, 
                                        progress_color=Theme.ACCENT_GREEN, command=self.quick_refresh_layout)
        self.fit_switch.pack(anchor="w", pady=(5, 10))

        # Resolution Inputs
        res_frame = ctk.CTkFrame(parent, fg_color="transparent")
        res_frame.pack(fill="x", pady=5)
        
        ctk.CTkLabel(res_frame, text="Width:").pack(side="left", padx=(0,5))
        w_entry = ctk.CTkEntry(res_frame, textvariable=self.output_width_var, width=70)
        w_entry.pack(side="left", padx=(0,15))
        w_entry.bind("<Return>", lambda e: self.quick_refresh_layout())

        ctk.CTkLabel(res_frame, text="Height:").pack(side="left", padx=(0,5))
        h_entry = ctk.CTkEntry(res_frame, textvariable=self.output_height_var, width=70)
        h_entry.pack(side="left")
        h_entry.bind("<Return>", lambda e: self.quick_refresh_layout())

        ctk.CTkLabel(parent, text="Thumbnails will crop to fit exactly.", font=("Roboto", 10), text_color=Theme.TEXT_MUTED).pack(anchor="w", pady=(5,0))

    def _populate_advanced_settings(self, parent):
        ctk.CTkLabel(parent, text="UI Theme:").pack(anchor="w", pady=(5, 0))
        self.ui_theme_seg = ctk.CTkSegmentedButton(
            parent,
            values=Theme.PRESET_NAMES,
            variable=self.ui_theme_var,
            selected_color=Theme.ACCENT_BLUE,
            selected_hover_color=Theme.ACCENT_BLUE_HOVER,
            command=self._on_ui_theme_change,
        )
        self.ui_theme_seg.pack(fill="x", pady=(0, 10))

        ctk.CTkLabel(parent, text="Extraction Mode:").pack(anchor="w", pady=(5, 0))
        self.extraction_mode_seg = ctk.CTkSegmentedButton(parent, values=["interval", "shot"], variable=self.extraction_mode_var,
                                                          selected_color=Theme.ACCENT_GREEN, selected_hover_color=Theme.ACCENT_GREEN_HOVER,
                                                          command=self._on_extraction_mode_change)
        self.extraction_mode_seg.pack(fill="x", pady=(0, 5))
        
        ctk.CTkLabel(parent, text="Layout Mode:").pack(anchor="w", pady=(5, 0))
        self.layout_mode_seg = ctk.CTkSegmentedButton(parent, values=["grid", "timeline"], variable=self.layout_mode_var,
                                                      selected_color=Theme.ACCENT_BLUE, selected_hover_color=Theme.ACCENT_BLUE_HOVER,
                                                      command=self._on_layout_mode_change)
        self.layout_mode_seg.pack(fill="x", pady=(0, 5))
        
        self.shot_threshold_frame = ctk.CTkFrame(parent, fg_color="transparent")
        self.shot_threshold_frame.pack(fill="x", pady=5)
        ctk.CTkLabel(self.shot_threshold_frame, text="Shot Threshold:").pack(side="left")
        ctk.CTkEntry(self.shot_threshold_frame, textvariable=self.shot_threshold_var, width=60).pack(side="left", padx=5)
        
        self.row_height_frame = ctk.CTkFrame(parent, fg_color="transparent")
        self.row_height_frame.pack(fill="x", pady=5)
        ctk.CTkLabel(self.row_height_frame, text="Target Row Height:").pack(side="left")
        ctk.CTkEntry(self.row_height_frame, textvariable=self.target_row_height_var, width=60).pack(side="left", padx=5)
        
        ctk.CTkLabel(parent, text="Filename Generation:").pack(anchor="w", pady=(10, 0))
        self.naming_mode_seg = ctk.CTkSegmentedButton(
            parent, 
            values=["Add Suffix", "Fixed Name"], 
            variable=self.naming_mode_display_var,
            command=self._toggle_naming_inputs,
            selected_color=Theme.ACTION_GOLD,
            selected_hover_color=Theme.ACTION_GOLD_HOVER
        )
        self.naming_mode_seg.pack(fill="x", pady=(0, 5))
        
        self.naming_input_frame = ctk.CTkFrame(parent, fg_color="transparent")
        self.naming_input_frame.pack(fill="x")
        self.lbl_suffix = ctk.CTkLabel(self.naming_input_frame, text="Suffix (e.g. -thumb):")
        self.entry_suffix = ctk.CTkEntry(self.naming_input_frame, textvariable=self.output_filename_suffix_var)
        self.lbl_custom = ctk.CTkLabel(self.naming_input_frame, text="Custom Name (e.g. backdrop):")
        self.entry_custom = ctk.CTkEntry(self.naming_input_frame, textvariable=self.output_filename_var)
        self._toggle_naming_inputs(self.output_naming_mode_var.get())
        
        ctk.CTkLabel(parent, text="Output Location:", text_color=Theme.TEXT_MUTED).pack(anchor="w", pady=(15, 0))
        ctk.CTkLabel(parent, text="Movieprints save alongside source videos.", font=Theme.FONT_BOLD, text_color=Theme.TEXT_MUTED).pack(anchor="w", pady=(0, 5))

        self.output_frames_only_cb = ctk.CTkCheckBox(
            parent,
            text="Export individual frames only",
            variable=self.output_frames_only_var,
            fg_color=Theme.ACTION_GOLD,
            hover_color=Theme.ACTION_GOLD_HOVER,
            command=self._toggle_frame_export_options,
        )
        self.output_frames_only_cb.pack(anchor="w", pady=(4, 2))

        self.frames_dir_frame = ctk.CTkFrame(parent, fg_color="transparent")
        ctk.CTkEntry(
            self.frames_dir_frame,
            textvariable=self.individual_frames_output_dir_var,
            placeholder_text="Optional folder for exported frames",
        ).pack(side="left", fill="x", expand=True)
        ctk.CTkButton(
            self.frames_dir_frame,
            text="Browse",
            width=70,
            command=self.browse_output_dir,
            fg_color=Theme.BUTTON_SUBTLE,
            hover_color=Theme.BUTTON_SUBTLE_HOVER,
        ).pack(side="left", padx=(6, 0))
        self._toggle_frame_export_options()

        # --- NEW: Overwrite Switch ---
        ctk.CTkLabel(parent, text="Existing Files:").pack(anchor="w", pady=(5,0))
        self.overwrite_seg = ctk.CTkSegmentedButton(parent, values=["overwrite", "skip"], variable=self.overwrite_mode_var,
                                                   selected_color=Theme.ACTION_GOLD, selected_hover_color=Theme.ACTION_GOLD_HOVER)
        self.overwrite_seg.pack(fill="x", pady=5)


        ctk.CTkSwitch(parent, text="Show Frame Info/Timecode", variable=self.frame_info_show_var, progress_color=Theme.ACCENT_GREEN, command=self.quick_refresh_layout).pack(anchor="w", pady=5)
        ctk.CTkCheckBox(parent, text="Detect Faces", variable=self.detect_faces_var, fg_color=Theme.ACCENT_GREEN, hover_color=Theme.ACCENT_GREEN_HOVER).pack(anchor="w", pady=2)
        ctk.CTkCheckBox(parent, text="Use GPU (FFmpeg)", variable=self.use_gpu_var, fg_color=Theme.ACCENT_GREEN, hover_color=Theme.ACCENT_GREEN_HOVER).pack(anchor="w", pady=2)
        ctk.CTkCheckBox(parent, text="Show Header (Filename)", variable=self.show_header_var, fg_color=Theme.ACCENT_GREEN, hover_color=Theme.ACCENT_GREEN_HOVER, command=self.quick_refresh_layout).pack(anchor="w", pady=2)
        ctk.CTkCheckBox(parent, text="Show Timecode", variable=self.show_timecode_var, fg_color=Theme.ACCENT_GREEN, hover_color=Theme.ACCENT_GREEN_HOVER, command=self.quick_refresh_layout).pack(anchor="w", pady=2)
        
        ctk.CTkLabel(parent, text="Rotate Thumbnails:").pack(anchor="w", pady=(10, 0))
        self.rotate_seg = ctk.CTkSegmentedButton(parent, values=["0", "90", "180", "270"], variable=self.rotate_thumbnails_var,
                                                 selected_color=Theme.ACCENT_BLUE, selected_hover_color=Theme.ACCENT_BLUE_HOVER,
                                                 command=self.quick_refresh_layout)
        self.rotate_seg.pack(fill="x", pady=5)

        ctk.CTkLabel(parent, text="Thumbnail Aspect:").pack(anchor="w", pady=(8, 0))
        self.aspect_combo = ctk.CTkComboBox(
            parent, values=["source", "16:9", "4:3", "1:1", "9:16"],
            variable=self.thumbnail_aspect_ratio_var,
            command=lambda _value: self.quick_refresh_layout(),
        )
        self.aspect_combo.pack(fill="x", pady=(0, 5))

        ctk.CTkLabel(parent, text="Crop video edges (%):").pack(anchor="w", pady=(8, 0))
        crop_frame = ctk.CTkFrame(parent, fg_color="transparent")
        crop_frame.pack(fill="x", pady=(0, 5))
        for label, variable in (
            ("T", self.crop_top_var), ("R", self.crop_right_var),
            ("B", self.crop_bottom_var), ("L", self.crop_left_var),
        ):
            ctk.CTkLabel(crop_frame, text=label).pack(side="left", padx=(3, 1))
            entry = ctk.CTkEntry(crop_frame, textvariable=variable, width=48)
            entry.pack(side="left", padx=(0, 3))
            entry.bind("<Return>", lambda _event: self.quick_refresh_layout())
        
        ctk.CTkLabel(parent, text="Corner Roundness:").pack(anchor="w", pady=(10,0))
        ctk.CTkSlider(parent, from_=0, to=100, variable=self.rounded_corners_var, progress_color=Theme.ACCENT_GREEN, command=self.quick_refresh_layout).pack(fill="x", pady=5)
        
        ctk.CTkLabel(parent, text="Padding:").pack(anchor="w", pady=(10, 0))
        pad_entry = ctk.CTkEntry(parent, textvariable=self.padding_var)
        pad_entry.pack(fill="x", pady=5)
        pad_entry.bind("<Return>", lambda e: self.quick_refresh_layout()) 

        ctk.CTkLabel(parent, text="Outer Grid Margin:").pack(anchor="w", pady=(6, 0))
        margin_entry = ctk.CTkEntry(parent, textvariable=self.grid_margin_var)
        margin_entry.pack(fill="x", pady=5)
        margin_entry.bind("<Return>", lambda _event: self.quick_refresh_layout())

        ctk.CTkLabel(parent, text="Background Color:").pack(anchor="w", pady=(10,0))
        ctk.CTkEntry(parent, textvariable=self.background_color_var).pack(fill="x", pady=5)
        ctk.CTkButton(parent, text="Pick Color", command=lambda: [self.pick_bg_color(), self.quick_refresh_layout()],
                      width=90, fg_color=Theme.BUTTON_SUBTLE, hover_color=Theme.BUTTON_SUBTLE_HOVER).pack(anchor="w")

        ctk.CTkLabel(parent, text="Output Format:").pack(anchor="w", pady=(10, 0))
        self.format_seg = ctk.CTkSegmentedButton(parent, values=["jpg", "png"], variable=self.frame_format_var, 
                                                 selected_color=Theme.ACCENT_GREEN, selected_hover_color=Theme.ACCENT_GREEN_HOVER)
        self.format_seg.pack(fill="x", pady=5)
        
        ctk.CTkLabel(parent, text="Preview Quality (Fast):").pack(anchor="w", pady=(10,0))
        ctk.CTkSlider(parent, from_=10, to=100, variable=self.preview_quality_var, progress_color=Theme.ACCENT_BLUE).pack(fill="x")
        ctk.CTkLabel(parent, text="Output Quality (JPG):").pack(anchor="w", pady=(10,0))
        ctk.CTkSlider(parent, from_=10, to=100, variable=self.output_quality_var, progress_color=Theme.ACTION_GOLD).pack(fill="x")
        
        self.update_visibility_state()

    def _populate_hdr_settings(self, parent):
        ctk.CTkLabel(parent, text="HDR to SDR Tone Mapping", font=Theme.FONT_BOLD).pack(anchor="w", pady=(5,0))
        ctk.CTkLabel(parent, text="Converts washed-out HDR colors to normal SDR.", font=("Roboto", 10), text_color=Theme.TEXT_MUTED).pack(anchor="w", pady=(0,5))
        self.hdr_switch = ctk.CTkSwitch(parent, text="Enable Tone Mapping", variable=self.hdr_tonemap_var, progress_color=Theme.ACTION_GOLD, command=self._toggle_hdr_options)
        self.hdr_switch.pack(anchor="w", pady=5)
        self.hdr_algo_frame = ctk.CTkFrame(parent, fg_color="transparent")
        self.hdr_algo_frame.pack(fill="x", padx=20)
        ctk.CTkLabel(self.hdr_algo_frame, text="Algorithm:").pack(side="left")
        self.hdr_algo_combo = ctk.CTkComboBox(self.hdr_algo_frame, values=["hable", "reinhard", "mobius"], variable=self.hdr_algorithm_var, border_color=Theme.ACTION_GOLD, button_color=Theme.ACTION_GOLD)
        self.hdr_algo_combo.pack(side="left", padx=10)
        self._toggle_hdr_options()

    def _toggle_hdr_options(self):
        if self.hdr_tonemap_var.get():
            self.hdr_algo_frame.pack(fill="x", padx=20, pady=5)
        else:
            self.hdr_algo_frame.pack_forget()


    def _toggle_frame_export_options(self):
        """Show the optional individual-frame export folder picker only when needed."""
        if not hasattr(self, "frames_dir_frame"):
            return
        try:
            enabled = bool(self.output_frames_only_var.get())
        except Exception:
            enabled = False

        if enabled:
            self.frames_dir_frame.pack(fill="x", pady=(2, 8))
        else:
            self.frames_dir_frame.pack_forget()

    def _toggle_naming_inputs(self, mode=None):
        if mode is None: mode = self.output_naming_mode_var.get()
        is_custom = mode in {"Fixed Name", "custom"}
        self.lbl_suffix.pack_forget()
        self.entry_suffix.pack_forget()
        self.lbl_custom.pack_forget()
        self.entry_custom.pack_forget()
        if is_custom:
            self.lbl_custom.pack(anchor="w", pady=(2,0))
            self.entry_custom.pack(fill="x", pady=(0,5))
            self.output_naming_mode_var.set("custom")
            self.naming_mode_display_var.set("Fixed Name")
        else:
            self.lbl_suffix.pack(anchor="w", pady=(2,0))
            self.entry_suffix.pack(fill="x", pady=(0,5))
            self.output_naming_mode_var.set("suffix")
            self.naming_mode_display_var.set("Add Suffix")

    # --- LOGIC ---
    def _set_busy(self, busy: bool):
        self.is_busy = busy
        save_state = "disabled" if busy else "normal"
        self.save_btn.configure(state=save_state)
        self.cancel_btn.configure(state="normal" if busy else "disabled")
        if not busy:
            self.active_cancel_event = None
            self.active_job_kind = None
        self._on_tab_change()

    def cancel_active_job(self):
        if not self.is_busy or not self.active_cancel_event:
            return
        self.active_cancel_event.set()
        self.cancel_btn.configure(state="disabled")
        job_name = "preview" if self.active_job_kind == "preview" else "batch"
        self.status_lbl.configure(text=f"Cancelling {job_name} after the current video step...")

    def _on_tab_change(self):
        active = self.input_tabs.get()
        if self.is_busy or active == "Batch Queue":
            self.preview_btn.configure(state="disabled", text_color=Theme.TEXT_MUTED, border_color=Theme.BG_TERTIARY)
        else:
            self.preview_btn.configure(state="normal", text_color=Theme.ACCENT_BLUE, border_color=Theme.ACCENT_BLUE)

        if self.is_busy or active == "Batch Queue":
            self.input_entry.configure(state="disabled", fg_color=Theme.BG_TERTIARY)
        else:
            self.input_entry.configure(state="normal", fg_color=Theme.PANEL_SOFT)

    def _bind_settings_to_state(self):
        for var_name, setting_key in self.settings_map.items():
            if hasattr(self, var_name):
                var = getattr(self, var_name)
                var.trace_add("write", lambda *args, v=var_name, s=setting_key: self._on_setting_change(v, s))

    def _on_setting_change(self, var_name, setting_key):
        try:
            var = getattr(self, var_name)
            val = var.get()
            if setting_key == 'input_paths' and isinstance(val, str):
                val = [path.strip() for path in val.split(';') if path.strip()]
            self.state_manager.update_settings({setting_key: val}, commit=False)
        except Exception: pass

    def _on_ui_theme_change(self, value):
        if self._loading_persistent_settings or self._applying_theme:
            return
        self.state_manager.update_settings({"ui_theme": value}, commit=False)
        self._apply_ui_theme(value)

    def _apply_ui_theme(self, value):
        if value == Theme.CURRENT:
            return
        self._applying_theme = True
        try:
            Theme.apply_preset(value)
            self.configure(fg_color=Theme.BG_PRIMARY)
            for child in self.winfo_children():
                child.destroy()
            self.grid_columnconfigure(1, weight=1)
            self.grid_rowconfigure(0, weight=1)
            self._build_sidebar()
            self._build_main_area()
            self._build_toolbar()
            self._build_action_footer()
            self.refresh_ui_from_state(self.state_manager.get_state())
            self._on_tab_change()
        finally:
            self._applying_theme = False

    def _update_live_math(self, *args):
        try:
            cols = int(self.num_columns_var.get())
            rows = int(self.num_rows_var.get() or 5)
            self.math_lbl_cols.configure(text=str(cols))
            self.math_lbl_rows.configure(text=str(rows))
            self.math_lbl_res.configure(text=str(cols * rows))
        except Exception: pass

    def perform_undo(self, event=None):
        new_state = self.state_manager.undo()
        if new_state: self.refresh_ui_from_state(new_state)

    def perform_redo(self, event=None):
        new_state = self.state_manager.redo()
        if new_state: self.refresh_ui_from_state(new_state)

    def refresh_ui_from_state(self, state):
        settings = state.settings
        for var_name, setting_key in self.settings_map.items():
            if hasattr(self, var_name) and hasattr(settings, setting_key):
                val = getattr(settings, setting_key)
                if setting_key == "input_paths" and isinstance(val, list): val = "; ".join(val)
                getattr(self, var_name).set(val)
        try:
            self.col_slider.set(settings.num_columns)
            self.row_slider.set(settings.num_rows)
            if hasattr(self, 'layout_mode_seg'): self.layout_mode_seg.set(self.layout_mode_var.get())
            if hasattr(self, 'extraction_mode_seg'): self.extraction_mode_seg.set(self.extraction_mode_var.get())
            if hasattr(self, 'ui_theme_seg'): self.ui_theme_seg.set(self.ui_theme_var.get())
            if hasattr(self, 'rotate_seg'): self.rotate_seg.set(str(self.rotate_thumbnails_var.get()))
            if hasattr(self, 'format_seg'): self.format_seg.set(self.frame_format_var.get())
            if hasattr(self, 'overwrite_seg'): self.overwrite_seg.set(self.overwrite_mode_var.get())
        except AttributeError: pass
        self.update_visibility_state()
        self._toggle_naming_inputs()
        self._toggle_hdr_options()
        if state.thumbnail_metadata and self.preview_temp_dir:
            self._restore_grid_visuals(state, settings)
        self._refresh_sheet_controls()
        if hasattr(self, 'hidden_switch'):
            if settings.filter_mode == 'all': self.hidden_switch.select()
            else: self.hidden_switch.deselect()
        self._update_live_math()

    def _restore_grid_visuals(self, state, settings):
        image_source_data = self._preview_image_source_data(state.thumbnail_metadata, settings.layout_mode)
        grid_path = os.path.join(self.preview_temp_dir, "preview_restored.jpg")
        
        grid_params = {
            'image_source_data': image_source_data,
            'output_path': grid_path,
            'columns': settings.num_columns,
            'rows': settings.num_rows,
            'background_color_hex': settings.background_color,
            'padding': settings.padding,
            'logger': logging.getLogger("restore"),
            'rounded_corners': settings.rounded_corners,
            'rotation': settings.rotate_thumbnails,
            'grid_margin': settings.grid_margin,
            'show_header': settings.show_header,
            'show_file_path': settings.show_file_path,
            'show_timecode': settings.show_timecode,
            'show_frame_num': settings.show_frame_num,
            'frame_info_show': settings.frame_info_show,
            'layout_mode': settings.layout_mode,
            'target_row_height': settings.target_row_height,
            # NEW PARAMS
            'fit_to_output_params': settings.fit_to_output_params,
            'output_width': settings.output_width,
            'output_height': settings.output_height,
            'quality': settings.preview_quality,
            'crop_top': settings.crop_top,
            'crop_right': settings.crop_right,
            'crop_bottom': settings.crop_bottom,
            'crop_left': settings.crop_left,
            'thumbnail_aspect_ratio': settings.thumbnail_aspect_ratio,
            'sort_mode': settings.sort_mode,
            'filter_mode': settings.filter_mode,
        }

        success, layout = DependencyManager.image_grid.create_image_grid(**grid_params)
        
        self.state_manager.get_state().thumbnail_layout_data = layout
        if success:
            self.preview_zoomable_canvas.set_image(grid_path)

    def _preview_image_source_data(self, metadata, layout_mode):
        image_source_data = []
        for source_index, item in enumerate(metadata or []):
            entry = {
                'image_path': item.get('frame_path'),
                'timestamp_sec': item.get('timestamp_sec'),
                'frame_number': item.get('frame_number'),
                'video_filename': item.get('video_filename'),
                'video_path': item.get('video_path'),
                'id': item.get('id') or f'thumb-{source_index + 1}',
                'source_index': source_index,
                'hidden': bool(item.get('hidden')),
                'transform': item.get('transform', {}),
                'face_detection': item.get('face_detection'),
            }
            if layout_mode == 'timeline':
                entry['width_ratio'] = item.get('duration_frames', 1.0)
            image_source_data.append(entry)
        return image_source_data

    def _grid_transform_params(self):
        return {
            'crop_top': float(self.crop_top_var.get() or 0),
            'crop_right': float(self.crop_right_var.get() or 0),
            'crop_bottom': float(self.crop_bottom_var.get() or 0),
            'crop_left': float(self.crop_left_var.get() or 0),
            'thumbnail_aspect_ratio': self.thumbnail_aspect_ratio_var.get(),
            'sort_mode': self.sort_mode_var.get(),
            'filter_mode': self.filter_mode_var.get(),
        }

    # --- PROJECT WORKSPACE ---
    def _refresh_sheet_controls(self):
        if not hasattr(self, 'sheet_combo'):
            return
        state = self.state_manager.get_state()
        names = [sheet.name for sheet in state.sheets]
        self.sheet_combo.configure(values=names)
        self.sheet_display_var.set(state.active_sheet().name)

    def _on_sheet_selected(self, sheet_name):
        state = self.state_manager.get_state()
        target = next((sheet for sheet in state.sheets if sheet.name == sheet_name), None)
        if not target or target.id == state.active_sheet_id:
            return
        self.state_manager.switch_sheet(target.id)
        self.selected_thumbnail_index = None
        self.refresh_ui_from_state(self.state_manager.get_state())
        self.quick_refresh_layout()

    def add_sheet(self):
        self.state_manager.add_sheet()
        self.selected_thumbnail_index = None
        self._refresh_sheet_controls()
        self.preview_zoomable_canvas.clear()
        self.status_lbl.configure(text="New sheet ready. Click Preview to populate it.")

    def duplicate_sheet(self):
        self.state_manager.add_sheet(duplicate_active=True)
        self._refresh_sheet_controls()
        self.quick_refresh_layout()

    def delete_sheet(self):
        if not self.state_manager.remove_active_sheet():
            messagebox.showinfo("Sheets", "A project must keep at least one sheet.")
            return
        self.selected_thumbnail_index = None
        self._refresh_sheet_controls()
        self.quick_refresh_layout()

    def _toggle_hidden_filter(self):
        self.filter_mode_var.set("all" if self.hidden_switch.get() else "visible")
        self.quick_refresh_layout()

    def save_project_action(self):
        state = self.state_manager.get_state()
        state.source_paths = list(self._internal_input_paths or state.settings.input_paths)
        state.settings.input_paths = list(state.source_paths)
        path = self.current_project_path
        if not path:
            path = filedialog.asksaveasfilename(
                title="Save PyMoviePrint Project",
                initialfile=f"{state.project_name}.pymovieprint.json",
                defaultextension=".pymovieprint.json",
                filetypes=[("PyMoviePrint Project", "*.pymovieprint.json"), ("JSON", "*.json")],
            )
        if not path:
            return
        try:
            self.current_project_path = project_io.save_project_json(path, state)
            state.project_name = os.path.splitext(os.path.basename(self.current_project_path))[0]
            self.status_lbl.configure(text=f"Project saved: {os.path.basename(self.current_project_path)}")
        except (OSError, ValueError, TypeError) as error:
            messagebox.showerror("Project Save Error", str(error))

    def open_project_action(self):
        path = filedialog.askopenfilename(
            title="Open MoviePrint Project",
            filetypes=[
                ("Editable MoviePrint", "*.json *.png"),
                ("PyMoviePrint Project", "*.json"),
                ("MoviePrint PNG", "*.png"),
            ],
        )
        if not path:
            return
        try:
            state, source_kind = project_io.load_project(path)
            self._prepare_loaded_project_frames(state)
            self.state_manager.replace_state(state)
            self.current_project_path = path if path.lower().endswith(".json") else None
            self._internal_input_paths = list(state.source_paths or state.settings.input_paths)
            state.settings.input_paths = list(self._internal_input_paths)
            self.input_paths_var.set("; ".join(self._internal_input_paths))
            self.refresh_ui_from_state(state)
            self._refresh_sheet_controls()
            if state.thumbnail_metadata:
                if self.is_landing_state:
                    self.landing_frame.grid_remove()
                    self.preview_zoomable_canvas.grid(row=0, column=0, sticky="nsew")
                    self.is_landing_state = False
                self.quick_refresh_layout()
            self.status_lbl.configure(text=f"Opened {source_kind}: {os.path.basename(path)}")
        except (OSError, ValueError, json.JSONDecodeError) as error:
            messagebox.showerror("Project Open Error", str(error))

    def _prepare_loaded_project_frames(self, state):
        """Re-extract referenced frames so projects remain portable across machines."""
        missing = any(
            not item.get('frame_path') or not os.path.exists(item.get('frame_path', ''))
            for sheet in state.sheets for item in sheet.thumbnail_metadata
        )
        if not missing:
            return
        sources = state.source_paths or state.settings.input_paths
        if not sources or not os.path.exists(sources[0]):
            replacement = filedialog.askopenfilename(
                title="Locate the source video for this project",
                filetypes=[("Video files", "*.mp4 *.mov *.mkv *.avi *.wmv *.flv"), ("All files", "*.*")],
            )
            if not replacement:
                raise ValueError("The source video referenced by this project could not be found.")
            sources = [os.path.abspath(replacement)]
            state.source_paths = list(sources)
            state.settings.input_paths = list(sources)
        if self.preview_temp_dir and os.path.exists(self.preview_temp_dir):
            self.temp_dirs_to_cleanup.append(self.preview_temp_dir)
        self.preview_temp_dir = tempfile.mkdtemp(prefix="movieprint_project_")
        video_path = sources[0]
        cv2 = DependencyManager.video_processing.cv2
        cap = cv2.VideoCapture(video_path)
        fps = float(cap.get(cv2.CAP_PROP_FPS) or 25.0) if cap.isOpened() else 25.0
        video_width = float(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 1.0) if cap.isOpened() else 1.0
        video_height = float(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 1.0) if cap.isOpened() else 1.0
        if cap.isOpened():
            cap.release()
        if getattr(state.settings, 'crop_units', 'percent') == 'pixels':
            state.settings.crop_top = state.settings.crop_top * 100.0 / video_height
            state.settings.crop_bottom = state.settings.crop_bottom * 100.0 / video_height
            state.settings.crop_left = state.settings.crop_left * 100.0 / video_width
            state.settings.crop_right = state.settings.crop_right * 100.0 / video_width
            state.settings.crop_units = 'percent'
        for sheet_index, sheet in enumerate(state.sheets):
            sheet_dir = os.path.join(self.preview_temp_dir, f"sheet_{sheet_index + 1}")
            os.makedirs(sheet_dir, exist_ok=True)
            with DependencyManager.video_processing.VideoExtractor(video_path, logging.getLogger("project_open")) as extractor:
                for item_index, item in enumerate(sheet.thumbnail_metadata):
                    if item.get('frame_path') and os.path.exists(item['frame_path']):
                        continue
                    timestamp = item.get('timestamp_sec')
                    if timestamp is None and item.get('frame_number') is not None:
                        timestamp = float(item['frame_number']) / max(fps, 0.001)
                    timestamp = float(timestamp or 0.0)
                    frame = extractor.extract_single_frame(timestamp)
                    if frame is None:
                        continue
                    frame_path = os.path.join(sheet_dir, f"frame_{item_index + 1:05d}.jpg")
                    cv2.imwrite(frame_path, frame)
                    item['frame_path'] = frame_path
                    item['timestamp_sec'] = timestamp
                    item['video_path'] = video_path
                    item['video_filename'] = os.path.basename(video_path)
                    item['needs_extraction'] = False
        state.activate_sheet(state.active_sheet_id, save_current=False)

    # --- THUMBNAIL EDITING ---
    def _thumbnail_index_at_event(self, event) -> Optional[int]:
        layout = self.state_manager.get_state().thumbnail_layout_data
        if not layout or not self.preview_zoomable_canvas.original_image:
            return None
        canvas_x, canvas_y = self.preview_zoomable_canvas.canvas_event_to_image_coords(event)
        for display_index, thumb in enumerate(layout):
            if (thumb['x'] <= canvas_x <= thumb['x'] + thumb['width'] and
                    thumb['y'] <= canvas_y <= thumb['y'] + thumb['height']):
                return int(thumb.get('source_index', display_index))
        return None

    def show_thumbnail_menu(self, event):
        index = self._thumbnail_index_at_event(event)
        if index is None:
            return
        self.selected_thumbnail_index = index
        sheet = self.state_manager.get_state().active_sheet()
        sheet.selected_thumbnail_id = self.state_manager.get_state().thumbnail_metadata[index].get('id')
        menu = tk.Menu(self, tearoff=0)
        hidden = bool(self.state_manager.get_state().thumbnail_metadata[index].get('hidden'))
        menu.add_command(label="Show thumbnail" if hidden else "Hide thumbnail", command=self.toggle_selected_hidden)
        menu.add_separator()
        menu.add_command(label="Add frame before", command=lambda: self.add_thumbnail_relative(-1))
        menu.add_command(label="Add frame after", command=lambda: self.add_thumbnail_relative(1))
        menu.add_command(label="Replace at time...", command=self._replace_selected_prompt)
        menu.add_command(label="Save frame...", command=self.save_selected_frame)
        menu.add_separator()
        menu.add_command(label="Set IN", command=lambda: self.set_selected_boundary('in'))
        menu.add_command(label="Set OUT", command=lambda: self.set_selected_boundary('out'))
        menu.add_command(label="Expand", command=self.expand_selected_thumbnail)
        menu.tk_popup(event.x_root, event.y_root)

    def _selected_meta(self):
        metadata = self.state_manager.get_state().thumbnail_metadata
        if self.selected_thumbnail_index is None or not (0 <= self.selected_thumbnail_index < len(metadata)):
            return None
        return metadata[self.selected_thumbnail_index]

    def toggle_selected_hidden(self):
        item = self._selected_meta()
        if item is None:
            return
        self.state_manager.snapshot()
        item['hidden'] = not bool(item.get('hidden'))
        self.quick_refresh_layout()

    def _source_video_path(self) -> str:
        item = self._selected_meta() or {}
        candidates = [item.get('video_path')] + self._internal_input_paths + self.state_manager.get_state().source_paths
        return next((path for path in candidates if path and os.path.exists(path)), "")

    def _extract_frame_metadata(self, timestamp: float, identity: Optional[str] = None):
        video_path = self._source_video_path()
        if not video_path:
            raise ValueError("The source video is not available.")
        if not self.preview_temp_dir:
            self.preview_temp_dir = tempfile.mkdtemp(prefix="movieprint_preview_")
        with DependencyManager.video_processing.VideoExtractor(video_path, logging.getLogger("thumbnail_edit")) as extractor:
            frame = extractor.extract_single_frame(max(0.0, timestamp))
        if frame is None:
            raise ValueError("Could not extract that frame from the video.")
        identity = identity or f"thumb-{time.time_ns()}"
        frame_path = os.path.join(self.preview_temp_dir, f"edited_{identity}_{time.time_ns()}.jpg")
        DependencyManager.video_processing.cv2.imwrite(frame_path, frame)
        cap = DependencyManager.video_processing.cv2.VideoCapture(video_path)
        fps = float(cap.get(DependencyManager.video_processing.cv2.CAP_PROP_FPS) or 25.0) if cap.isOpened() else 25.0
        if cap.isOpened():
            cap.release()
        return {
            'id': identity, 'frame_path': frame_path, 'timestamp_sec': max(0.0, timestamp),
            'frame_number': round(max(0.0, timestamp) * fps),
            'video_path': video_path, 'video_filename': os.path.basename(video_path),
        }

    def add_thumbnail_relative(self, direction: int):
        current = self._selected_meta()
        if current is None:
            return
        metadata = self.state_manager.get_state().thumbnail_metadata
        index = self.selected_thumbnail_index
        current_ts = float(current.get('timestamp_sec') or 0.0)
        neighbour_index = index + direction
        if 0 <= neighbour_index < len(metadata):
            neighbour_ts = float(metadata[neighbour_index].get('timestamp_sec') or current_ts)
            timestamp = (current_ts + neighbour_ts) / 2.0
        else:
            timestamp = max(0.0, current_ts + direction)
        try:
            self.state_manager.snapshot()
            insert_at = index if direction < 0 else index + 1
            metadata.insert(insert_at, self._extract_frame_metadata(timestamp))
            self.selected_thumbnail_index = insert_at
            self.sort_mode_var.set("manual")
            self.quick_refresh_layout()
        except ValueError as error:
            messagebox.showerror("Thumbnail Edit", str(error))

    def _replace_selected_prompt(self):
        item = self._selected_meta()
        if item is None:
            return
        timestamp = simpledialog.askfloat(
            "Replace Thumbnail", "Time in seconds:", initialvalue=float(item.get('timestamp_sec') or 0.0), minvalue=0.0,
        )
        if timestamp is not None:
            self.replace_selected_thumbnail(timestamp)

    def replace_selected_thumbnail(self, timestamp: float):
        item = self._selected_meta()
        if item is None:
            messagebox.showinfo("Player", "Right-click a thumbnail first to select it.")
            return
        try:
            self.state_manager.snapshot()
            replacement = self._extract_frame_metadata(timestamp, item.get('id'))
            replacement.update({key: value for key, value in item.items() if key in {'hidden', 'transform'}})
            self.state_manager.get_state().thumbnail_metadata[self.selected_thumbnail_index] = replacement
            self.quick_refresh_layout()
        except ValueError as error:
            messagebox.showerror("Thumbnail Edit", str(error))

    def save_selected_frame(self):
        item = self._selected_meta()
        if not item or not os.path.exists(item.get('frame_path', '')):
            return
        extension = os.path.splitext(item['frame_path'])[1] or '.jpg'
        path = filedialog.asksaveasfilename(defaultextension=extension, filetypes=[("Image", "*.jpg *.png")])
        if path:
            shutil.copy2(item['frame_path'], path)

    def set_selected_boundary(self, boundary: str):
        item = self._selected_meta()
        if item is None:
            return
        timestamp = float(item.get('timestamp_sec') or 0.0)
        sheet = self.state_manager.get_state().active_sheet()
        self.state_manager.snapshot()
        if boundary == 'in':
            sheet.in_point_sec = timestamp
        else:
            sheet.out_point_sec = timestamp
        self.status_lbl.configure(text=f"{boundary.upper()} set to {timestamp:.3f}s")

    def expand_selected_thumbnail(self):
        item = self._selected_meta()
        if not item or not os.path.exists(item.get('frame_path', '')):
            return
        window = ctk.CTkToplevel(self)
        window.title(f"Frame at {float(item.get('timestamp_sec') or 0):.3f}s")
        with Image.open(item['frame_path']) as source:
            image = source.copy()
        image.thumbnail((1280, 800), Image.Resampling.LANCZOS)
        photo = ctk.CTkImage(light_image=image, dark_image=image, size=image.size)
        label = ctk.CTkLabel(window, text="", image=photo)
        label.image = photo
        label.pack(padx=10, pady=10)

    def open_player(self):
        video_path = self._source_video_path()
        if not video_path:
            messagebox.showerror("Player", "Choose a source video first.")
            return
        if self.player_window and self.player_window.winfo_exists():
            self.player_window.focus()
            return
        try:
            self.player_window = VideoPlayerWindow(self, video_path)
        except ValueError as error:
            messagebox.showerror("Player", str(error))

    # --- ACTION HANDLERS ---
    def _start_queue_poller(self):
        try:
            while True:
                msg_type, data = self.queue.get_nowait()
                if msg_type == "log":
                    self.status_lbl.configure(text=data)
                elif msg_type == "progress":
                    current, total, fname = data
                    if total > 0:
                        self.progress_bar.set(current / total)
                        if self.input_tabs.get() == "Batch Queue":
                            self.status_lbl.configure(text=f"Batch: {current}/{total} | {fname}")
                        else:
                            self.status_lbl.configure(text=f"Processing {current}/{total}...")
                    else: self.status_lbl.configure(text="Processing Complete.")
                elif msg_type == "preview_done":
                    self._handle_preview_done(data)
                elif msg_type == "preview_failed":
                    self._handle_preview_failed(data)
                elif msg_type == "preview_cancelled":
                    self._handle_preview_cancelled()
                elif msg_type == "generation_done":
                    self._handle_generation_done(data)
                elif msg_type == "update_thumbnail":
                    self.update_thumbnail_in_preview(data['index'], data['image'], data['timestamp'])
                elif msg_type == "busy":
                    self._set_busy(bool(data))
                self.update_idletasks()
        except queue.Empty: pass
        self.after(100, self._start_queue_poller)

    def start_thumbnail_preview_generation(self):
        if self.is_busy:
            return

        if self.input_tabs.get() == "Batch Queue":
            messagebox.showinfo("Mode Info", "Switch to 'Single Source' tab to preview tweaks.")
            return

        input_paths = [p.strip() for p in self.input_paths_var.get().split(';') if p.strip()]
        if not input_paths:
            messagebox.showerror("Preview Error", "Choose a video file before generating a preview.")
            return
        self._internal_input_paths = input_paths
        self.state_manager.get_state().source_paths = list(input_paths)
        
        # --- NEW: Check if input is directory and resolve to first video ---
        preview_target_path = self._internal_input_paths[0]
        if os.path.isdir(preview_target_path):
            self.status_lbl.configure(text="Scanning directory for preview...")
            # Use maker's discovery logic to find first valid video
            valid_exts = ".mp4,.avi,.mov,.mkv,.flv,.wmv"
            # We don't recurse for preview scan to save time, just check root
            videos = DependencyManager.movieprint_maker_module.discover_video_files([preview_target_path], valid_exts, False, logging.getLogger("preview_scan"))
            if videos:
                preview_target_path = videos[0]
            else:
                messagebox.showerror("Preview Error", "No video files found in the selected directory.")
                return

        if self.preview_temp_dir and os.path.exists(self.preview_temp_dir):
            self.temp_dirs_to_cleanup.append(self.preview_temp_dir)
            
        new_temp_dir = tempfile.mkdtemp(prefix="movieprint_preview_")
        self.preview_temp_dir = new_temp_dir
        self._cleanup_garbage_dirs()
        
        preview_settings = {
            'extraction_mode': self.extraction_mode_var.get(),
            'layout_mode': self.layout_mode_var.get(),
            'shot_threshold': float(self.shot_threshold_var.get() or 27.0),
            'cols': int(self.num_columns_var.get()),
            'rows': int(self.num_rows_var.get()),
            'detect_faces': self.detect_faces_var.get(),
            'rotate_thumbnails': int(self.rotate_thumbnails_var.get()),
            'bg_color': self.background_color_var.get(),
            'padding': int(self.padding_var.get()),
            'grid_margin': int(self.grid_margin_var.get()),
            'rounded': int(self.rounded_corners_var.get()),
            'show_header': self.show_header_var.get(),
            'show_file_path': self.show_file_path_var.get(),
            'show_timecode': self.show_timecode_var.get(),
            'show_frame_num': self.show_frame_num_var.get(),
            'target_row_height': int(self.target_row_height_var.get() or 150),
            'frame_info_show': self.frame_info_show_var.get(),
            'preview_quality': int(self.preview_quality_var.get()),
            'hdr_tonemap': self.hdr_tonemap_var.get(),
            'hdr_algorithm': self.hdr_algorithm_var.get(),
            'fit_to_output_params': self.fit_to_output_params_var.get(),
            'output_width': int(self.output_width_var.get()),
            'output_height': int(self.output_height_var.get()),
            'crop_top': float(self.crop_top_var.get() or 0),
            'crop_right': float(self.crop_right_var.get() or 0),
            'crop_bottom': float(self.crop_bottom_var.get() or 0),
            'crop_left': float(self.crop_left_var.get() or 0),
            'thumbnail_aspect_ratio': self.thumbnail_aspect_ratio_var.get(),
            'sort_mode': self.sort_mode_var.get(),
            'filter_mode': self.filter_mode_var.get(),
            'cancel_event': threading.Event(),
        }

        self.status_lbl.configure(text="Generating Preview...")
        self.progress_bar.configure(mode="indeterminate")
        self.progress_bar.start()
        self.active_cancel_event = preview_settings['cancel_event']
        self.active_job_kind = "preview"
        self._set_busy(True)
        
        threading.Thread(
            target=self._thumbnail_preview_thread, 
            args=(preview_target_path, new_temp_dir, preview_settings),
            daemon=True
        ).start()

    def _thumbnail_preview_thread(self, video_path, temp_dir, config):
        logger = logging.getLogger(f"preview_{threading.get_ident()}")
        logger.addHandler(QueueHandler(self.queue))
        meta = []
        success = False
        failure_reason = None
        try:
            if not config['hdr_tonemap']:
                 with DependencyManager.video_processing.VideoExtractor(video_path, logger) as ve:
                    if ve.detect_hdr():
                        self.queue.put(("log", "HDR content detected. Enable Tone Mapping for correct colors."))

            if config['extraction_mode'] == 'shot':
                self.queue.put(("log", f"Detecting shots (Threshold {config['shot_threshold']})..."))
                success, meta = DependencyManager.video_processing.extract_shot_boundary_frames(
                    video_path, temp_dir, logger,
                    detector_threshold=config['shot_threshold']
                )
                if not success: self.queue.put(("log", "Shot detection failed (is PySceneDetect installed?)"))

            else:
                duration = 600
                cap = DependencyManager.video_processing.cv2.VideoCapture(video_path)
                if cap.isOpened():
                    fps = cap.get(DependencyManager.video_processing.cv2.CAP_PROP_FPS)
                    frames = cap.get(DependencyManager.video_processing.cv2.CAP_PROP_FRAME_COUNT)
                    duration = frames / fps if fps > 0 else 600
                    cap.release()

                total_frames = config['cols'] * config['rows']
                timestamps = np.linspace(0, duration, total_frames+2)[1:-1]
                
                self.queue.put(("log", f"Extracting {total_frames} frames..."))
                
                if config['hdr_tonemap']:
                    self.queue.put(("log", "Generating HDR Preview (FFmpeg)..."))
                    interval = duration / total_frames
                    success, meta = DependencyManager.video_processing.extract_frames(
                        video_path, temp_dir, logger, 
                        interval_seconds=interval, 
                        fast_preview=True, 
                        hdr_tonemap=True, 
                        hdr_algorithm=config['hdr_algorithm']
                    )
                    if len(meta) > total_frames: meta = meta[:total_frames]
                else:
                    success, meta = DependencyManager.video_processing.extract_frames_from_timestamps(
                        video_path, timestamps, temp_dir, logger, fast_preview=True
                    )
            
            if config['cancel_event'].is_set():
                self.queue.put(("preview_cancelled", None))
            elif success and meta:
                self._process_preview_thumbnails(meta, config, logger)

                self.queue.put(("log", f"Generating {config['layout_mode']} layout..."))
                grid_path = os.path.join(temp_dir, "preview_initial.jpg")
                
                image_source_data = self._preview_image_source_data(meta, config['layout_mode'])

                grid_success, layout = DependencyManager.image_grid.create_image_grid(
                    image_source_data=image_source_data,
                    output_path=grid_path,
                    layout_mode=config['layout_mode'],
                    columns=config['cols'],
                    rows=config['rows'],
                    target_row_height=config['target_row_height'],
                    background_color_hex=config['bg_color'],
                    padding=config['padding'],
                    grid_margin=config['grid_margin'],
                    logger=logger,
                    rounded_corners=config['rounded'], 
                    rotation=config['rotate_thumbnails'],
                    show_header=config['show_header'],
                    show_file_path=config['show_file_path'],
                    show_timecode=config['show_timecode'],
                    show_frame_num=config['show_frame_num'],
                    frame_info_show=config['frame_info_show'],
                    quality=config['preview_quality'],
                    fit_to_output_params=config['fit_to_output_params'],
                    output_width=config['output_width'],
                    output_height=config['output_height'],
                    crop_top=config['crop_top'],
                    crop_right=config['crop_right'],
                    crop_bottom=config['crop_bottom'],
                    crop_left=config['crop_left'],
                    thumbnail_aspect_ratio=config['thumbnail_aspect_ratio'],
                    sort_mode=config['sort_mode'],
                    filter_mode=config['filter_mode'],
                )
                
                if config['cancel_event'].is_set():
                    self.queue.put(("preview_cancelled", None))
                elif grid_success:
                    self.queue.put(("preview_done", {
                        "grid_path": grid_path, "meta": meta,
                        "layout": layout, "temp_dir": temp_dir
                    }))
                else:
                    failure_reason = "Preview image could not be created."
            else:
                failure_reason = "Frame extraction yielded no frames."
        except Exception as e:
            logger.exception("Preview generation failed")
            failure_reason = str(e)
        finally:
            self.queue.put(("progress", (0, 0, "")))
            if failure_reason:
                self.queue.put(("preview_failed", {"reason": failure_reason}))
            self.queue.put(("busy", False))

    def _process_preview_thumbnails(self, meta_list, config, logger):
        cv2 = DependencyManager.video_processing.cv2
        if config['detect_faces']:
            self.queue.put(("log", "Detecting faces (Preview)..."))
            cascade_path = os.path.join(cv2.data.haarcascades, 'haarcascade_frontalface_default.xml')
            face_cascade = cv2.CascadeClassifier(cascade_path)
            if not face_cascade.empty():
                for item in meta_list:
                    try:
                        img = cv2.imread(item['frame_path'])
                        if img is None: continue
                        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
                        faces = face_cascade.detectMultiScale(gray, 1.1, 4)
                        if len(faces) > 0:
                            for (x, y, w, h) in faces:
                                cv2.rectangle(img, (x, y), (x+w, y+h), (0, 255, 0), 2)
                            cv2.imwrite(item['frame_path'], img)
                    except Exception as e: logger.warning(f"Face detect error: {e}")

    def _handle_preview_done(self, data):
        metadata = data.get("meta") or []
        for index, item in enumerate(metadata):
            item.setdefault('id', f"thumb-{time.time_ns()}-{index + 1}")
            item.setdefault('hidden', False)
        self.state_manager.get_state().thumbnail_metadata = metadata
        self.state_manager.get_state().thumbnail_layout_data = data.get("layout")
        self.state_manager.get_state().sync_active_sheet()
        
        if self.is_landing_state:
            self.landing_frame.grid_remove()
            self.preview_zoomable_canvas.grid(row=0, column=0, sticky="nsew")
            self.is_landing_state = False
            
        if data.get("grid_path"):
            self.preview_zoomable_canvas.set_image(data.get("grid_path"))
            
        self.progress_bar.stop()
        self._update_live_math()
        self.state_manager.snapshot()

    def _handle_preview_failed(self, data):
        reason = data.get("reason") or "An unknown error occurred while generating the preview."
        summary = f"Preview failed: {reason}"
        self.progress_bar.stop()
        self.status_lbl.configure(text=summary)
        messagebox.showerror("Preview Error", summary)

    def _handle_preview_cancelled(self):
        self.progress_bar.stop()
        self.status_lbl.configure(text="Preview cancelled. No preview was changed.")

    def _handle_generation_done(self, data):
        successful_ops = data.get("successful_ops", [])
        failed_ops = data.get("failed_ops", [])
        success_count = len(successful_ops)
        failure_count = len(failed_ops)
        cancelled = bool(data.get("cancelled"))

        # PNG exports carry a compressed, editable project payload. Failure to
        # embed metadata never invalidates an otherwise successful render.
        for operation in successful_ops:
            output_path = operation.get('output') if isinstance(operation, dict) else None
            if output_path and str(output_path).lower().endswith('.png') and os.path.isfile(output_path):
                try:
                    project_io.embed_project_in_png(output_path, self.state_manager.get_state())
                except (OSError, ValueError, TypeError) as error:
                    logging.getLogger("project_embed").warning("Could not embed project in %s: %s", output_path, error)

        if success_count == 0 and failure_count == 0 and not cancelled:
            summary = "No valid video files were found. Nothing was generated."
            self.status_lbl.configure(text=summary)
            messagebox.showwarning("Generation Complete", summary)
            return

        if failure_count == 0 and not cancelled:
            summary = f"Generation complete: {success_count} movieprint(s) created."
            self.status_lbl.configure(text=summary)
            messagebox.showinfo("Generation Complete", summary)
            return

        summary = f"Generation complete: {success_count} succeeded, {failure_count} failed."
        if success_count == 0:
            summary = f"Generation failed: {failure_count} movieprint(s) failed."

        if cancelled:
            summary = f"Generation cancelled: {success_count} completed before cancellation."
            if failure_count:
                summary += f" {failure_count} failed."

        first_failure = failed_ops[0].get("reason") if failed_ops else None
        if first_failure:
            first_file = failed_ops[0].get("video")
            if first_file:
                summary += f"\n\nFirst failed file: {first_file}"
            summary += f"\nWhat happened: {first_failure}"
        self.status_lbl.configure(text=summary.split("\n", 1)[0])
        messagebox.showwarning("Generation Completed with Errors", summary)

    def quick_refresh_layout(self, value=None):
        if not self.state_manager.get_state().thumbnail_metadata or not self.preview_temp_dir:
            return
        meta = self.state_manager.get_state().thumbnail_metadata
        layout_mode = self.layout_mode_var.get()
        image_source_data = self._preview_image_source_data(meta, layout_mode)
        grid_path = os.path.join(self.preview_temp_dir, "preview_refresh.jpg")
        transform_params = self._grid_transform_params()
        success, layout = DependencyManager.image_grid.create_image_grid(
            image_source_data=image_source_data,
            output_path=grid_path,
            layout_mode=layout_mode,
            columns=int(self.num_columns_var.get()),
            rows=int(self.num_rows_var.get()),
            target_row_height=int(self.target_row_height_var.get() or 150),
            background_color_hex=self.background_color_var.get(),
            padding=int(self.padding_var.get()),
            grid_margin=int(self.grid_margin_var.get()),
            logger=logging.getLogger("refresh"),
            rounded_corners=int(self.rounded_corners_var.get()),
            rotation=int(self.rotate_thumbnails_var.get()),
            show_header=self.show_header_var.get(),
            show_file_path=self.show_file_path_var.get(),
            show_timecode=self.show_timecode_var.get(),
            show_frame_num=self.show_frame_num_var.get(),
            frame_info_show=self.frame_info_show_var.get(),
            quality=int(self.preview_quality_var.get()),
            fit_to_output_params=self.fit_to_output_params_var.get(),
            output_width=int(self.output_width_var.get()),
            output_height=int(self.output_height_var.get()),
            **transform_params,
        )
        if success:
            self.preview_zoomable_canvas.set_image(grid_path)
            self.state_manager.get_state().thumbnail_layout_data = layout

    # --- SCRUBBING ---
    def is_scrubbing_active(self): return self.scrubbing_handler.active
    def start_scrubbing(self, event): return self.start_scrubbing_logic(event)
    def start_scrubbing_logic(self, event):
        layout = self.state_manager.get_state().thumbnail_layout_data
        if not layout or not self.preview_zoomable_canvas.original_image: return False
        canvas_x, canvas_y = self.preview_zoomable_canvas.canvas_event_to_image_coords(event)
        for i, thumb_info in enumerate(layout):
            if thumb_info['x'] <= canvas_x <= thumb_info['x'] + thumb_info['width'] and \
               thumb_info['y'] <= canvas_y <= thumb_info['y'] + thumb_info['height']:
                self.state_manager.snapshot()
                source_index = int(thumb_info.get('source_index', i))
                self.selected_thumbnail_index = source_index
                meta = self.state_manager.get_state().thumbnail_metadata[source_index]
                video_path = self._internal_input_paths[0] if self._internal_input_paths else ""
                self.scrubbing_handler.start(event, source_index, meta.get('timestamp_sec', 0.0), video_path)
                return True
        return False
    def handle_scrubbing(self, event): self.scrubbing_handler.handle_motion(event)
    def stop_scrubbing(self, event): self.scrubbing_handler.stop(event)
    def update_thumbnail_in_preview(self, index, new_thumb_img, new_timestamp):
        try:
            item = self.state_manager.get_state().thumbnail_metadata[index]
            item['timestamp_sec'] = new_timestamp
            frame_path = item.get('frame_path')
            if frame_path:
                new_thumb_img.convert('RGB').save(frame_path, quality=92)
        except IndexError: pass
        canvas_handler = self.preview_zoomable_canvas
        layout = self.state_manager.get_state().thumbnail_layout_data
        if not canvas_handler.original_image or index >= len(layout): return
        try:
            thumb_info = next(
                (value for display_index, value in enumerate(layout)
                 if int(value.get('source_index', display_index)) == index),
                None,
            )
            if thumb_info is None:
                return
            rot_val = int(self.rotate_thumbnails_var.get())
            if rot_val == 90: new_thumb_img = new_thumb_img.rotate(-90, expand=True)
            elif rot_val == 180: new_thumb_img = new_thumb_img.rotate(180)
            elif rot_val == 270: new_thumb_img = new_thumb_img.rotate(-270, expand=True)
            
            # Use same fit logic for live update if enabled
            fit = self.fit_to_output_params_var.get()
            if fit:
                resized = ImageOps.fit(new_thumb_img, (thumb_info['width'], thumb_info['height']), method=Image.Resampling.NEAREST)
            else:
                resized = new_thumb_img.resize((thumb_info['width'], thumb_info['height']), Image.Resampling.NEAREST)

            radius = int(self.rounded_corners_var.get())
            if radius > 0:
                resized = resized.convert("RGBA")
                mask = Image.new('L', resized.size, 0)
                draw = ImageDraw.Draw(mask)
                radius = min(radius, min(resized.size) // 2)
                draw.rounded_rectangle([(0, 0), (resized.width - 1, resized.height - 1)], radius=radius, fill=255)
                existing_alpha = resized.split()[3]
                final_alpha = ImageChops.multiply(existing_alpha, mask)
                resized.putalpha(final_alpha)
            canvas_handler.original_image.paste(resized, (thumb_info['x'], thumb_info['y']), mask=resized if radius > 0 else None)
            canvas_handler._apply_zoom()
        except Exception as e:
            logging.getLogger("preview").warning(f"Error updating preview thumbnail: {e}")

    # --- FINAL GENERATION ---
    def _find_batch_output_collisions(self, settings):
        logger = logging.getLogger("batch_output_collision_check")
        video_files = DependencyManager.movieprint_maker_module.discover_video_files(
            settings.input_paths,
            getattr(settings, 'video_extensions', ".mp4,.avi,.mov,.mkv,.flv,.wmv"),
            getattr(settings, 'recursive_scan', False),
            logger
        )
        if len(video_files) < 2:
            return []
        return DependencyManager.movieprint_maker_module.find_output_path_collisions(video_files, settings)

    def _show_batch_output_collision_error(self, collisions):
        first = collisions[0]
        videos = "\n".join(f"- {path}" for path in first['videos'][:4])
        if len(first['videos']) > 4:
            videos += f"\n- plus {len(first['videos']) - 4} more"
        messagebox.showerror(
            "Naming Error",
            "These batch items would write to the same output:\n\n"
            f"{first['output']}\n\n"
            f"{videos}\n\n"
            "Use Add Suffix, change Fixed Name, or split that folder into a separate batch."
        )

    def generate_movieprint_action(self):
        if self.is_busy:
            return

        self.status_lbl.configure(text="Starting Generation...")
        active_tab = self.input_tabs.get()
        final_input_list = []
        if active_tab == "Batch Queue":
            if not self.batch_file_list:
                messagebox.showerror("Input Error", "Batch queue is empty.")
                return
            final_input_list = self.batch_file_list
        else:
            input_paths_str = self.input_paths_var.get()
            final_input_list = [p.strip() for p in input_paths_str.split(';') if p.strip()]
            if not final_input_list:
                messagebox.showerror("Input Error", "Please select video file(s).")
                return
            self._internal_input_paths = final_input_list
        
        settings = argparse.Namespace()
        settings.input_paths = final_input_list
        settings.save_alongside_video = True 
        settings.output_dir = None
        
        try:
            settings.layout_mode = self.layout_mode_var.get()
            settings.extraction_mode = self.extraction_mode_var.get()
            settings.shot_threshold = float(self.shot_threshold_var.get())
            settings.frame_info_show = self.frame_info_show_var.get()
            settings.detect_faces = self.detect_faces_var.get()
            settings.rotate_thumbnails = int(self.rotate_thumbnails_var.get())
            settings.output_quality = int(self.output_quality_var.get())
            settings.hdr_tonemap = self.hdr_tonemap_var.get()
            settings.hdr_algorithm = self.hdr_algorithm_var.get()
            settings.fit_to_output_params = self.fit_to_output_params_var.get()
            settings.output_width = int(self.output_width_var.get())
            settings.output_height = int(self.output_height_var.get())
            settings.crop_top = float(self.crop_top_var.get() or 0)
            settings.crop_right = float(self.crop_right_var.get() or 0)
            settings.crop_bottom = float(self.crop_bottom_var.get() or 0)
            settings.crop_left = float(self.crop_left_var.get() or 0)
            settings.thumbnail_aspect_ratio = self.thumbnail_aspect_ratio_var.get()
            settings.sort_mode = self.sort_mode_var.get()
            settings.filter_mode = self.filter_mode_var.get()
            
            # --- NEW SETTINGS ---
            settings.recursive_scan = self.recursive_scan_var.get()
            settings.overwrite_mode = self.overwrite_mode_var.get()

            rows = int(self.num_rows_var.get())
            cols = int(self.num_columns_var.get())
            settings.manual_timestamps = None
            
            if settings.layout_mode == "grid":
                settings.rows = rows
                settings.columns = cols
                settings.max_frames_for_print = rows * cols
                settings.target_row_height = None
                settings.interval_seconds = None
                if active_tab == "Single Source":
                    current_meta = self._metadata_in_display_order()
                    if current_meta:
                        settings.manual_timestamps = [m.get('timestamp_sec', 0.0) for m in current_meta]
                else:
                    settings.manual_timestamps = None
            else:
                settings.rows = None
                settings.columns = None
                settings.max_frames_for_print = None
                settings.target_row_height = int(self.target_row_height_var.get() or 150)
                settings.interval_seconds = None
                if active_tab == "Single Source":
                    current_meta = self._metadata_in_display_order()
                    if current_meta:
                        settings.manual_timestamps = [m.get('timestamp_sec', 0.0) for m in current_meta]

            settings.padding = int(self.padding_var.get())
            settings.background_color = self.background_color_var.get()
            settings.frame_format = self.frame_format_var.get()
            settings.save_metadata_json = False 
            active_sheet = self.state_manager.get_state().active_sheet()
            settings.start_time = active_sheet.in_point_sec
            settings.end_time = active_sheet.out_point_sec
            settings.exclude_frames = None
            settings.exclude_shots = None
            settings.output_naming_mode = self.output_naming_mode_var.get()
            settings.output_filename_suffix = self.output_filename_suffix_var.get()
            settings.output_filename = self.output_filename_var.get()
            settings.output_frames_only = self.output_frames_only_var.get()
            settings.individual_frames_output_dir = self.individual_frames_output_dir_var.get().strip()
            settings.temp_dir = None
            settings.haar_cascade_xml = None
            settings.grid_margin = int(self.grid_margin_var.get())
            settings.show_header = self.show_header_var.get()
            settings.show_file_path = self.show_file_path_var.get()
            settings.show_timecode = self.show_timecode_var.get()
            settings.show_frame_num = self.show_frame_num_var.get()
            settings.rounded_corners = int(self.rounded_corners_var.get())
            settings.max_output_filesize_kb = None
            settings.use_gpu = self.use_gpu_var.get()
            settings.interval_frames = None
            settings.output_image_width = int(self.output_width_var.get())
            settings.target_thumbnail_width = None
            settings.target_thumbnail_height = None
            settings.video_extensions = ".mp4,.avi,.mov,.mkv,.flv,.wmv"
            settings.frame_info_timecode_or_frame = self.frame_info_timecode_or_frame_var.get()
            settings.frame_info_font_color = self.frame_info_font_color_var.get()
            settings.frame_info_bg_color = self.frame_info_bg_color_var.get()
            settings.frame_info_position = self.frame_info_position_var.get()
            settings.frame_info_size = int(self.frame_info_size_var.get())
            settings.frame_info_margin = int(self.frame_info_margin_var.get())

        except Exception as e:
             messagebox.showerror("Error", str(e))
             return

        try:
            collisions = self._find_batch_output_collisions(settings)
        except ValueError as error:
            messagebox.showerror("Naming Error", str(error))
            return
        if collisions:
            self._show_batch_output_collision_error(collisions)
            return
        
        self.status_lbl.configure(text="Generating...")
        self.progress_bar.configure(mode="determinate")
        self.active_cancel_event = threading.Event()
        self.active_job_kind = "generation"
        settings.cancel_event = self.active_cancel_event
        self._set_busy(True)
        
        threading.Thread(
            target=self.run_generation_in_thread, 
            args=(settings, self._gui_progress_callback),
            daemon=True
        ).start()

    def _metadata_in_display_order(self):
        state = self.state_manager.get_state()
        metadata = state.thumbnail_metadata
        if state.thumbnail_layout_data:
            ordered = []
            used = set()
            for display_index, item in enumerate(state.thumbnail_layout_data):
                index = int(item.get('source_index', display_index))
                if 0 <= index < len(metadata) and index not in used and not metadata[index].get('hidden'):
                    ordered.append(metadata[index])
                    used.add(index)
            if ordered:
                return ordered
        return [item for item in metadata if not item.get('hidden')]

    def run_generation_in_thread(self, settings, progress_cb):
        thread_logger = logging.getLogger(f"gui_thread_{threading.get_ident()}")
        thread_logger.setLevel(logging.INFO)
        thread_logger.addHandler(QueueHandler(self.queue))
        try:
            successful_ops, failed_ops = DependencyManager.movieprint_maker(
                settings, thread_logger, progress_cb, fast_preview=False
            )
        except Exception as e:
            thread_logger.exception(f"Error: {e}")
            successful_ops = []
            failed_ops = [{"reason": str(e)}]
        finally:
            self.queue.put(("generation_done", {
                "successful_ops": successful_ops,
                "failed_ops": failed_ops,
                "cancelled": bool(getattr(settings, "cancelled", False)),
            }))
            self.queue.put(("busy", False))

    def _gui_progress_callback(self, current, total, filename):
        self.queue.put(("progress", (current, total, filename)))

    # --- HELPERS ---
    def browse_input_paths(self):
        filepaths = filedialog.askopenfilenames(title="Select Video File(s)")
        if filepaths:
            self._internal_input_paths = list(filepaths)
            self.input_paths_var.set("; ".join(self._internal_input_paths))
            self.input_entry.delete(0, tk.END)
            self.input_entry.insert(0, self.input_paths_var.get())

    def _add_batch_paths(self, paths):
        added = 0
        existing_keys = {os.path.normcase(os.path.abspath(path)) for path in self.batch_file_list}
        for path in paths:
            normalised_path = os.path.abspath(path)
            key = os.path.normcase(normalised_path)
            if key in existing_keys:
                continue
            self.batch_file_list.append(normalised_path)
            self.batch_listbox.insert(tk.END, normalised_path)
            existing_keys.add(key)
            added += 1
        if paths and not added:
            self.status_lbl.configure(text="Those items are already in the batch queue.")

    def browse_batch_files(self):
        filepaths = filedialog.askopenfilenames(title="Add Video Files to Batch Queue")
        if filepaths:
            self._add_batch_paths(filepaths)

    def browse_batch_folder(self):
        folder = filedialog.askdirectory(title="Add Folder to Batch Queue")
        if folder:
            self._add_batch_paths([folder])

    def handle_drop(self, event):
        paths = self.tk.splitlist(event.data)
        if not paths: return
        active_tab = self.input_tabs.get()
        if active_tab == "Batch Queue":
            self._add_batch_paths(paths)
        else:
            self._internal_input_paths = list(paths)
            self.input_paths_var.set("; ".join(paths))
            self.input_entry.delete(0, tk.END)
            self.input_entry.insert(0, self.input_paths_var.get())

    def clear_batch_list(self):
        self.batch_file_list.clear()
        self.batch_listbox.delete(0, tk.END)

    def remove_batch_item(self):
        selection = self.batch_listbox.curselection()
        if not selection: return
        for i in reversed(selection):
            path = self.batch_listbox.get(i)
            if path in self.batch_file_list: self.batch_file_list.remove(path)
            self.batch_listbox.delete(i)

    def browse_output_dir(self):
        selected = filedialog.askdirectory(title="Select Folder for Individual Frame Exports")
        if selected:
            self.individual_frames_output_dir_var.set(selected)
    def pick_bg_color(self):
        c = colorchooser.askcolor(color=self.background_color_var.get())
        if c[1]: self.background_color_var.set(c[1])
    def _on_col_slider_change(self, value):
        self.num_columns_var.set(int(value))
        self._update_live_math()
    def _on_row_slider_change(self, value):
        self.num_rows_var.set(int(value))
        self._update_live_math()
    def _on_extraction_mode_change(self, value):
        if value == "interval" and self.layout_mode_var.get() == "timeline": self.layout_mode_var.set("grid")
        self.update_visibility_state()
    def _on_layout_mode_change(self, value):
        if value == "timeline" and self.extraction_mode_var.get() == "interval": self.extraction_mode_var.set("shot")
        self.update_visibility_state()

    def update_visibility_state(self, *args):
        layout = self.layout_mode_var.get()
        extraction = self.extraction_mode_var.get()
        if layout == "grid":
            self.slider_frame.pack(fill="x", padx=10, pady=10, after=self.input_entry.master.master) 
            self.row_height_frame.pack_forget()
        else:
            self.slider_frame.pack_forget()
            self.row_height_frame.pack(fill="x", pady=5, after=self.layout_mode_seg)
        if extraction == "shot": self.shot_threshold_frame.pack(fill="x", pady=5, after=self.layout_mode_seg)
        else: self.shot_threshold_frame.pack_forget()
        self._update_live_math()

    def _cleanup_garbage_dirs(self):
        for d in self.temp_dirs_to_cleanup:
            try: shutil.rmtree(d)
            except OSError: pass

    def _load_persistent_settings(self):
        if not os.path.exists(SETTINGS_FILE): return
        try:
            self._loading_persistent_settings = True
            with open(SETTINGS_FILE, 'r') as f:
                settings = json.load(f)
                self.input_paths_var.set(settings.get("input_paths", ""))
                if self.input_paths_var.get():
                     self._internal_input_paths = [p.strip() for p in self.input_paths_var.get().split(';') if p.strip()]
                for var_name, key in self.settings_map.items():
                    if key in settings and hasattr(self, var_name):
                        value = settings[key]
                        if key == "ui_theme" and value not in Theme.PRESET_NAMES:
                            value = "Teal"
                        getattr(self, var_name).set(value)
                self.col_slider.set(int(self.num_columns_var.get() or 5))
                self.row_slider.set(int(self.num_rows_var.get() or 5))
                if hasattr(self, 'layout_mode_seg'): self.layout_mode_seg.set(self.layout_mode_var.get())
                if hasattr(self, 'extraction_mode_seg'): self.extraction_mode_seg.set(self.extraction_mode_var.get())
                if hasattr(self, 'ui_theme_seg'): self.ui_theme_seg.set(self.ui_theme_var.get())
                if hasattr(self, 'rotate_seg'): self.rotate_seg.set(str(self.rotate_thumbnails_var.get()))
                if hasattr(self, 'format_seg'): self.format_seg.set(self.frame_format_var.get())
                if hasattr(self, 'overwrite_seg'): self.overwrite_seg.set(self.overwrite_mode_var.get())
                self.update_visibility_state()
                self._toggle_naming_inputs()
                self._toggle_hdr_options()
        except Exception: pass
        finally:
            self._loading_persistent_settings = False

    def _on_closing(self):
        settings = {}
        for var_name, key in self.settings_map.items():
            if hasattr(self, var_name): settings[key] = getattr(self, var_name).get()
        try:
            with open(SETTINGS_FILE, 'w') as f: json.dump(settings, f, indent=4)
        except: pass
        if self.preview_temp_dir and os.path.exists(self.preview_temp_dir): self.temp_dirs_to_cleanup.append(self.preview_temp_dir)
        self._cleanup_garbage_dirs()
        self.destroy()

if __name__ == "__main__":
    setup_file_logging()
    app = MoviePrintApp()
    app.mainloop()
