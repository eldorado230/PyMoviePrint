import tkinter as tk
import tkinter.font as tkfont
import logging
from logging.handlers import RotatingFileHandler
from tkinter import ttk, filedialog, messagebox, colorchooser, simpledialog
import os
import sys
import shutil
import tempfile
import argparse
import copy
import threading
import queue
import time
import json
import traceback
import subprocess
from typing import Optional, List, Dict, Any, Tuple, Union
try:
    dependency_name = 'customtkinter'
    import customtkinter as ctk
    dependency_name = 'numpy'
    import numpy as np
    dependency_name = 'Pillow'
    from PIL import ImageTk, Image, ImageDraw, ImageChops, ImageOps
except Exception as error:
    detail = traceback.format_exc()
    try:
        log_dir = os.path.join(os.path.expanduser('~'), '.pymovieprint', 'logs')
        os.makedirs(log_dir, exist_ok=True)
        with open(os.path.join(log_dir, 'startup_error.log'), 'a', encoding='utf-8') as stream:
            stream.write(detail + '\n')
    except OSError:
        logging.exception('Could not write startup error log')
    logging.error('Failed to load %s:\n%s', dependency_name, detail)
    root = tk.Tk()
    root.withdraw()
    messagebox.showerror('Startup Error', f'Could not load {dependency_name}: {type(error).__name__}: {error}')
    root.destroy()
    raise SystemExit(1) from error

# --- DEPENDENCY MANAGEMENT ---
class DependencyManager:
    MISSING_LIBS: List[str] = []
    LOAD_FAILURES: List[Tuple[str, str, str]] = []
    video_processing = None
    state_manager = None
    state_manager_cls = None
    movieprint_maker = None
    movieprint_maker_module = None
    image_grid = None
    project_io = None
    version = "0.0.0"
    
    @classmethod
    def load(cls):
        modules = [
            ("video_processing", "video_processing"),
            ("image_grid", "image_grid"),
            ("state_manager", "state_manager"),
            ("project_io", "project_io"),
            ("workspace_tools", "workspace_tools"),
            ("face_analysis", "face_analysis"),
            ("movieprint_maker", "movieprint_maker"),
            ("version", "version")
        ]

        for attr, name in modules:
            try:
                mod = __import__(name)
                if name == 'state_manager':
                    cls.state_manager_cls = mod.StateManager
                elif name == 'movieprint_maker':
                    cls.movieprint_maker_module = mod
                    cls.movieprint_maker = mod.execute_movieprint_generation
                    continue
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

        if hasattr(cls, 'version') and hasattr(cls.version, '__version__'):
            cls.version = cls.version.__version__

DependencyManager.load()
project_io = DependencyManager.project_io
workspace_tools = getattr(DependencyManager, 'workspace_tools', None)

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
            "BG_PRIMARY": "#242A2E",
            "BG_SECONDARY": "#2B3237",
            "BG_TERTIARY": "#414D54",
            "PANEL": "#303A40",
            "PANEL_SOFT": "#37434A",
            "ACCENT_BLUE": "#83B5B0",
            "ACCENT_BLUE_HOVER": "#96C4BF",
            "ACCENT_GREEN": "#608F89",
            "ACCENT_GREEN_HOVER": "#719F99",
            "ACTION_GOLD": "#A1C7BF",
            "ACTION_GOLD_HOVER": "#B2D3CD",
            "DANGER_RED": "#B67F83",
            "DANGER_RED_HOVER": "#C69094",
            "TEXT_MUTED": "#B5C0C5",
        },
        "Yellow": {
            "BG_PRIMARY": "#2C2925",
            "BG_SECONDARY": "#34312C",
            "BG_TERTIARY": "#504A40",
            "PANEL": "#3B3730",
            "PANEL_SOFT": "#454037",
            "ACCENT_BLUE": "#C7B28A",
            "ACCENT_BLUE_HOVER": "#D4C19F",
            "ACCENT_GREEN": "#978365",
            "ACCENT_GREEN_HOVER": "#AA9777",
            "ACTION_GOLD": "#D2BF99",
            "ACTION_GOLD_HOVER": "#DFCEAF",
            "DANGER_RED": "#BA8580",
            "DANGER_RED_HOVER": "#CC9791",
            "TEXT_MUTED": "#C2BBAF",
        },
        "Dark Green": {
            "BG_PRIMARY": "#262C28",
            "BG_SECONDARY": "#2E3630",
            "BG_TERTIARY": "#475249",
            "PANEL": "#343F37",
            "PANEL_SOFT": "#3D4940",
            "ACCENT_BLUE": "#A1B8A1",
            "ACCENT_BLUE_HOVER": "#B2C8B1",
            "ACCENT_GREEN": "#738F77",
            "ACCENT_GREEN_HOVER": "#85A087",
            "ACTION_GOLD": "#B3C9AE",
            "ACTION_GOLD_HOVER": "#C3D6BD",
            "DANGER_RED": "#B78383",
            "DANGER_RED_HOVER": "#C89393",
            "TEXT_MUTED": "#B7C2B8",
        },
    }
    PRESET_NAMES = list(PRESETS.keys())
    CURRENT = "Teal"

    TEXT_MAIN = "#E3E7E9"
    TEXT_DARK = "#020707"
    BUTTON_SUBTLE = "#142020"
    BUTTON_SUBTLE_HOVER = "#1C3030"

    FONT_FAMILY = 'Segoe UI'
    FONT_HEADER = (FONT_FAMILY, 60, 'bold')
    FONT_SUB = (FONT_FAMILY, 16)
    FONT_BOLD = (FONT_FAMILY, 12, "bold")

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
        ctk.ThemeManager.theme['CTkButton'].update(
            fg_color=cls.BUTTON_SUBTLE, hover_color=cls.BUTTON_SUBTLE_HOVER, text_color=cls.TEXT_MAIN)
        ctk.ThemeManager.theme['CTkLabel']['text_color'] = cls.TEXT_MAIN

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
        self._scrub_queue: queue.Queue = queue.Queue(maxsize=1)
        self._stop_event = threading.Event()
        self._worker_thread: Optional[threading.Thread] = None
        self.session_id = 0

    def start(self, event, thumbnail_index: int, original_timestamp: float, video_path: str):
        if not video_path or not os.path.exists(video_path): return
        self._stop_event.set()
        self.session_id += 1
        self._scrub_queue = queue.Queue(maxsize=1)
        
        self.active = True
        self.thumbnail_index = thumbnail_index
        self.original_timestamp = original_timestamp
        self.start_x = event.x
        self.video_path = video_path
        
        self.app.preview_zoomable_canvas.canvas.config(cursor="sb_h_double_arrow")
        self._stop_event = threading.Event()
        session_event = self._stop_event
        
        while True:
            try: self._scrub_queue.get_nowait()
            except queue.Empty: break

        self._worker_thread = threading.Thread(target=self._scrub_worker,
            args=(session_event, self._scrub_queue, video_path, self.session_id,
                  self.app.state_manager.get_state().active_sheet_id), daemon=True)
        self._worker_thread.start()

    def stop(self, event):
        if self.active:
            self.active = False
            self.thumbnail_index = -1
            self.app.preview_zoomable_canvas.canvas.config(cursor="")
            # Let the last requested position finish. Starting another session or
            # closing still cancels this worker and invalidates its result.
            self.app.queue.put(("log", "Scrubbing finished."))
            self.app.after(0, self.app.quick_refresh_layout)

    def handle_motion(self, event):
        if not self.active: return
        dx = event.x - self.start_x
        pixels_per_second = 50.0 
        time_offset = dx / pixels_per_second
        new_timestamp = max(0.0, self.original_timestamp + time_offset)
        try:
            self._scrub_queue.put_nowait((new_timestamp, self.thumbnail_index))
        except queue.Full:
            try: self._scrub_queue.get_nowait()
            except queue.Empty: pass
            try: self._scrub_queue.put_nowait((new_timestamp, self.thumbnail_index))
            except queue.Full: pass

    def _scrub_worker(self, stop_event=None, work_queue=None, video_path=None, session_id=None, sheet_id=None):
        stop_event = stop_event or self._stop_event
        work_queue = work_queue or self._scrub_queue
        video_path = video_path or self.video_path
        if not DependencyManager.video_processing: return
        VideoExtractor = DependencyManager.video_processing.VideoExtractor
        
        try:
            with VideoExtractor(video_path) as extractor:
                while not stop_event.is_set():
                    try:
                        item = work_queue.get(timeout=0.5)
                        if item is None: break 
                        
                        target_ts, thumb_idx = item
                        while not work_queue.empty():
                            try:
                                next_item = work_queue.get_nowait()
                                if next_item is None:
                                    stop_event.set()
                                    break
                                target_ts, thumb_idx = next_item
                            except queue.Empty: break
                        
                        if stop_event.is_set(): break
                        
                        frame = extractor.extract_single_frame(target_ts)
                        if frame is not None and not stop_event.is_set():
                            cv2 = DependencyManager.video_processing.cv2
                            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                            pil_img = Image.fromarray(frame_rgb)
                            
                            self.app.queue.put(("update_thumbnail", {
                                "index": thumb_idx, 
                                "image": pil_img, 
                                "timestamp": target_ts,
                                "frame_number": round(target_ts * extractor.properties[0]),
                                "session_id": session_id, "sheet_id": sheet_id
                            }))
                            
                    except queue.Empty:
                        if not self.active:
                            return
        except Exception as e:
            logging.error(f"Scrub worker error: {e}")

# --- UI COMPONENTS ---
class ZoomableCanvas(ctk.CTkFrame):
    MAX_ZOOM = 5.0

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
        self._auto_fit: bool = False
        self._fit_after_id = None
        
        self.canvas.bind("<ButtonPress-1>", self.on_button_press)
        self.canvas.bind("<B1-Motion>", self.on_mouse_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_button_release)
        self.canvas.bind("<MouseWheel>", self.on_mouse_wheel) 
        self.canvas.bind("<Button-4>", self.on_mouse_wheel)   
        self.canvas.bind("<Button-5>", self.on_mouse_wheel)   
        self.canvas.bind("<Button-3>", self.app_ref.show_thumbnail_menu)
        self.canvas.bind("<Configure>", self._on_canvas_configure, add="+")
        
        if DND_ENABLED:
            try:
                self.canvas.drop_target_register(DND_FILES)
                self.canvas.dnd_bind('<<Drop>>', self.app_ref.handle_drop)
            except Exception: pass

    def on_button_press(self, event):
        if self.app_ref.is_busy:
            return
        if event.state & 0x0001:
            self._drag_source = self.app_ref._thumbnail_index_at_event(event)
            return
        if self.app_ref.is_scrubbing_active():
            self.app_ref.stop_scrubbing(event)
            return
        is_scrub_initiated = self.app_ref.start_scrubbing(event)
        if not is_scrub_initiated:
            self.canvas.scan_mark(event.x, event.y)

    def on_mouse_drag(self, event):
        if getattr(self, '_drag_source', None) is not None:
            return
        if self.app_ref.is_scrubbing_active():
            self.app_ref.handle_scrubbing(event)
        else:
            self.canvas.scan_dragto(event.x, event.y, gain=1)

    def on_button_release(self, event):
        source = getattr(self, '_drag_source', None)
        self._drag_source = None
        if source is not None:
            destination = self.app_ref._thumbnail_index_at_event(event)
            if destination is not None and source != destination:
                self.app_ref.state_manager.snapshot()
                destination = workspace_tools.move_thumbnail(self.app_ref.state_manager.get_state(), source, destination)
                self.app_ref.sort_mode_var.set('manual')
                self.app_ref.selected_thumbnail_index = destination
                self.app_ref.quick_refresh_layout()
            return
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

        new_zoom = max(0.01, min(self.MAX_ZOOM, new_zoom))
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
        self._auto_fit = False
        if self._zoom_level == scale_level: return
        self._zoom_level = scale_level
        self._apply_zoom()

    @staticmethod
    def _calculate_fit_zoom(image_width: int, image_height: int,
                            viewport_width: int, viewport_height: int) -> float:
        """Return a contain scale that keeps the whole image in the viewport."""
        if min(image_width, image_height, viewport_width, viewport_height) <= 0:
            return 1.0
        return min(
            ZoomableCanvas.MAX_ZOOM,
            viewport_width / image_width,
            viewport_height / image_height,
        )

    def _on_canvas_configure(self, _event=None):
        if not self._auto_fit or not self.original_image:
            return
        if self._fit_after_id is not None:
            self.after_cancel(self._fit_after_id)
        self._fit_after_id = self.after(75, self._fit_image_to_window)

    def _fit_image_to_window(self):
        self._fit_after_id = None
        if not self._auto_fit or not self.original_image or not self.image_id:
            return
        self._zoom_level = self._calculate_fit_zoom(
            self.original_image.width,
            self.original_image.height,
            self.canvas.winfo_width(),
            self.canvas.winfo_height(),
        )
        self.app_ref.zoom_level_var.set(self._zoom_level)
        self._apply_zoom()
        self.canvas.xview_moveto(0)
        self.canvas.yview_moveto(0)

    def fit_to_window(self):
        """Restore automatic fitting after manual zooming."""
        self._auto_fit = True
        self._fit_image_to_window()

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
            if self.image_id: self.canvas.delete(self.image_id)
            self.image_id = self.canvas.create_image(0, 0, anchor="nw")
            self._auto_fit = True
            self._fit_image_to_window()
        except Exception as e:
            logging.error(f"Error setting image: {e}")
            self.clear()

    def clear(self):
        if self._fit_after_id is not None:
            self.after_cancel(self._fit_after_id)
            self._fit_after_id = None
        if self.image_id: self.canvas.delete(self.image_id)
        self.image_id = None
        self.original_image = None
        self.photo_image = None
        self._auto_fit = False
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
        self._frame_extractor = DependencyManager.video_processing.VideoExtractor(video_path)
        self._is_hdr = self._frame_extractor.detect_hdr()
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
        ctk.CTkButton(controls, text='Audio player', width=105, command=self.play_with_audio).pack(side='left', padx=4)
        self.bind('<Left>', lambda _event: self.seek_to(self.current_timestamp-1/self.fps))
        self.bind('<Right>', lambda _event: self.seek_to(self.current_timestamp+1/self.fps))
        self.bind('<space>', lambda _event: self.toggle_play())
        self.bind('<F11>', lambda _event: self.attributes('-fullscreen', not self.attributes('-fullscreen')))
        self.bind('<Escape>', lambda _event: self.attributes('-fullscreen', False))

        self.protocol("WM_DELETE_WINDOW", self.close)
        self.seek_to(0.0)

    def _seek(self, value):
        self.seek_to(float(value))

    def seek_to(self, timestamp: float):
        cv2 = DependencyManager.video_processing.cv2
        self.current_timestamp = max(0.0, min(float(timestamp), max(0, self.duration - 1/self.fps)))
        self.position_var.set(self.current_timestamp)
        self.cap.set(cv2.CAP_PROP_POS_MSEC, self.current_timestamp * 1000.0)
        ok, frame = self.cap.read()
        if self._is_hdr:
            frame = self._frame_extractor.extract_single_frame(self.current_timestamp)
            ok = frame is not None
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

    def play_with_audio(self):
        executable = shutil.which('ffplay')
        if not executable:
            messagebox.showerror('Audio player', 'FFplay is required for audio playback. Install a full FFmpeg build.')
            return
        self.playing = False
        self.play_button.configure(text='PLAY')
        self._stop_audio_playback()
        try:
            self._audio_errors = tempfile.TemporaryFile()
            self._audio_process = subprocess.Popen(
                [executable, '-loglevel', 'error', '-autoexit', '-ss', str(self.current_timestamp), '-window_title',
                 'PyMoviePrint · F: fullscreen · Space: pause · Q: close', self.video_path],
                stdout=subprocess.DEVNULL, stderr=self._audio_errors,
                startupinfo=DependencyManager.video_processing.VideoUtils.get_startup_info())
            self.after(250, self._check_audio_player)
        except OSError as error:
            self._stop_audio_playback()
            logging.getLogger(__name__).exception('Could not start audio player')
            messagebox.showerror('Audio player', str(error))

    def _check_audio_player(self):
        if not self.winfo_exists() or getattr(self, '_audio_process', None) is None:
            return
        code = self._audio_process.poll()
        if code is None:
            self.after(250, self._check_audio_player)
        elif not self._audio_errors.closed:
            self._audio_errors.seek(0)
            detail = self._audio_errors.read().decode('utf-8', errors='replace')
            self._audio_errors.close()
            if code:
                logging.getLogger(__name__).error('Audio player failed: %s', detail)
                messagebox.showerror('Audio player', detail[-1500:] or 'Audio playback failed.')

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

    def _stop_audio_playback(self):
        audio_process = getattr(self, '_audio_process', None)
        if audio_process and audio_process.poll() is None:
            audio_process.terminate()
            try:
                audio_process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                audio_process.kill()
                audio_process.wait()
        self._audio_process = None
        audio_errors = getattr(self, '_audio_errors', None)
        if audio_errors is not None and not audio_errors.closed:
            audio_errors.close()

    def close(self):
        self._stop_audio_playback()
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

        ctk.ThemeManager.theme['CTkFont']['family'] = Theme.FONT_FAMILY
        for name in ('TkDefaultFont', 'TkTextFont', 'TkMenuFont', 'TkHeadingFont', 'TkCaptionFont'):
            tkfont.nametofont(name, root=self).configure(family=Theme.FONT_FAMILY)
        self.title(f"PyMoviePrint v{DependencyManager.version}")
        self.library_visible = True
        self.inspector_visible = True
        # Tk reports logical screen coordinates here; CTk applies DPI scaling.
        width = min(1500, self.winfo_screenwidth()-40)
        height = min(950, self.winfo_screenheight()-100)
        self.geometry(f'{max(800, width)}x{max(550, height)}+10+10')
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
        self.grid_rowconfigure(2, weight=1)

        self._build_sidebar()
        self._build_main_area()
        self._build_toolbar()
        self._build_action_footer()

        self._load_persistent_settings()
        self._start_queue_poller()
        
        self.protocol("WM_DELETE_WINDOW", self._on_closing)
        self.bind("<Control-z>", self.perform_undo)
        self.bind("<Control-y>", self.perform_redo)
        self.bind('<Control-s>', lambda _event: self.save_project_action())
        self.bind('<Control-o>', lambda _event: self.open_project_action())
        self._update_live_math()

    def report_callback_exception(self, exc_type, exc_value, exc_traceback):
        logging.getLogger(__name__).error('GUI action failed', exc_info=(exc_type, exc_value, exc_traceback))
        if not getattr(self, '_closing', False):
            messagebox.showerror('PyMoviePrint Error', f'{exc_type.__name__}: {exc_value}\n\nDetails were written to the log.')

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
        self.sidebar_frame = ctk.CTkScrollableFrame(self, width=270, corner_radius=0, fg_color=Theme.BG_SECONDARY)
        self.sidebar_frame.grid(row=1, column=0, rowspan=2, sticky="nsew", padx=(0, 1))
        ctk.CTkLabel(self.sidebar_frame, text='LIBRARY', font=Theme.FONT_BOLD,
                     text_color=Theme.TEXT_MUTED).pack(anchor='w', padx=12, pady=(14, 4))
        style = ttk.Style(self)
        style.theme_use('clam')
        style.configure('MoviePrint.Treeview', background=Theme.BG_SECONDARY,
                        fieldbackground=Theme.BG_SECONDARY, foreground='#DCE5EA', rowheight=round(24*self._get_window_scaling()),
                        borderwidth=0, font=(Theme.FONT_FAMILY, -round(13*self._get_window_scaling())))
        style.map('MoviePrint.Treeview', background=[('selected', Theme.ACCENT_BLUE)],
                  foreground=[('selected', Theme.TEXT_DARK)])
        self.source_library = ttk.Treeview(self.sidebar_frame, show='tree', height=4,
                                          style='MoviePrint.Treeview', selectmode='browse')
        self.source_library.pack(fill='both', expand=True, padx=14, pady=(8, 12))
        self.source_library.bind('<<TreeviewSelect>>', self._library_selected)
        library_actions = ctk.CTkFrame(self.sidebar_frame, fg_color='transparent')
        library_actions.pack(fill='x', padx=14, pady=(0, 12))
        for label, command in (('+ Sheet', self.add_sheet), ('Duplicate', self.duplicate_sheet), ('−', self.delete_sheet)):
            ctk.CTkButton(library_actions, text=label, width=75, height=28, command=command,
                          fg_color=Theme.BUTTON_SUBTLE).pack(side='left', padx=(0, 5))
        self.inspector_frame = ctk.CTkScrollableFrame(self, width=300, corner_radius=0, fg_color=Theme.BG_SECONDARY)
        self.inspector_frame.grid(row=1, column=2, rowspan=2, sticky='nsew', padx=(1, 0))
        ctk.CTkLabel(self.inspector_frame, text='INSPECTOR', font=Theme.FONT_BOLD,
                     text_color=Theme.TEXT_MUTED).pack(anchor='w', padx=14, pady=(14, 8))
        self.selection_panel = ctk.CTkFrame(self.inspector_frame, fg_color=Theme.PANEL_SOFT, corner_radius=8)
        self.selection_panel.pack(fill='x', padx=10, pady=(0, 12))
        self.selection_title = ctk.CTkLabel(self.selection_panel, text='No frame selected', anchor='w', font=Theme.FONT_BOLD)
        self.selection_title.pack(fill='x', padx=12, pady=(10, 2))
        self.selection_detail = ctk.CTkLabel(self.selection_panel, text='Select a frame to edit its time or visibility.',
                                            anchor='w', justify='left', wraplength=250, text_color=Theme.TEXT_MUTED)
        self.selection_detail.pack(fill='x', padx=12, pady=(0, 10))
        self.selection_actions = ctk.CTkFrame(self.selection_panel, fg_color='transparent')
        for label, command in (('Change time', self._replace_selected_prompt), ('Hide / show', self.toggle_selected_hidden),
                               ('Save frame', self.save_selected_frame), ('Open player', self.open_player)):
            ctk.CTkButton(self.selection_actions, text=label, height=28, command=command,
                          fg_color=Theme.BUTTON_SUBTLE).pack(fill='x', pady=3)
        self._create_grid_controller(self.inspector_frame)

    def _build_main_area(self):
        self.main_area = ctk.CTkFrame(self, fg_color=Theme.BG_PRIMARY, corner_radius=0)
        self.main_area.grid(row=2, column=1, sticky="nsew", padx=16, pady=(0, 12))
        self.main_area.grid_rowconfigure(0, weight=1)
        self.main_area.grid_columnconfigure(0, weight=1)
        self.preview_zoomable_canvas = ZoomableCanvas(self.main_area, app_ref=self)
        self.landing_frame = ctk.CTkFrame(self.main_area, fg_color=Theme.BG_PRIMARY)
        self.landing_frame.grid(row=0, column=0, sticky="nsew")
        self._create_landing_page(self.landing_frame)
        # Root-owned edge buttons remain above the canvas and reachable even
        # when either scrollable side panel is hidden.
        self.library_toggle = ctk.CTkButton(self, width=28, height=52,
            text='‹', font=(Theme.FONT_FAMILY, 24, 'bold'),
            command=lambda: self._toggle_side_panel('library'))
        self.library_toggle.place(in_=self.main_area, relx=0, rely=0.5, anchor='w')
        self.inspector_toggle = ctk.CTkButton(self, width=28, height=52,
            text='›', font=(Theme.FONT_FAMILY, 24, 'bold'),
            command=lambda: self._toggle_side_panel('inspector'))
        self.inspector_toggle.place(in_=self.main_area, relx=1, rely=0.5, anchor='e')
        self._apply_panel_visibility()

    def _toggle_side_panel(self, panel):
        attribute = f'{panel}_visible'
        setattr(self, attribute, not getattr(self, attribute))
        self._apply_panel_visibility()

    def _apply_panel_visibility(self):
        for panel, visible in ((self.sidebar_frame, self.library_visible),
                               (self.inspector_frame, self.inspector_visible)):
            if visible:
                panel._parent_frame.grid()
            else:
                panel._parent_frame.grid_remove()
        self.library_toggle.configure(text='‹' if self.library_visible else '›')
        self.inspector_toggle.configure(text='›' if self.inspector_visible else '‹')
        self.library_toggle.lift()
        self.inspector_toggle.lift()

    def _build_toolbar(self):
        self.topbar_frame = ctk.CTkFrame(self, fg_color=Theme.BG_SECONDARY, corner_radius=0, height=64)
        self.topbar_frame.grid(row=0, column=0, columnspan=3, sticky='ew', pady=(0, 1))
        logo_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'assets', 'movieprint-studio-v1.png')
        try:
            with Image.open(logo_path) as source:
                logo = source.copy()
            self._brand_image = ctk.CTkImage(light_image=logo, dark_image=logo, size=(38, 38))
            ctk.CTkLabel(self.topbar_frame, text='', image=self._brand_image).pack(side='left', padx=(16, 8))
            self._window_icon = ImageTk.PhotoImage(logo.resize((64, 64), Image.Resampling.LANCZOS))
            self.iconphoto(True, self._window_icon)
        except (OSError, tk.TclError):
            logging.getLogger(__name__).warning('Could not load Studio logo', exc_info=True)
        self.brand_label = ctk.CTkLabel(self.topbar_frame, text='PyMoviePrint', font=(Theme.FONT_FAMILY, 21, 'bold'))
        self.brand_label.pack(side='left', padx=(8, 14), pady=14)
        ctk.CTkLabel(self.topbar_frame, text='STUDIO', text_color=Theme.ACCENT_BLUE,
                     font=(Theme.FONT_FAMILY, 11, 'bold')).pack(side='left', padx=(0, 20))
        for label, command in (('Add video…', self.browse_input_paths),
                               ('Open project…', self.open_project_action), ('Save project', self.save_project_action)):
            ctk.CTkButton(self.topbar_frame, text=label, command=command, width=100, height=32,
                          fg_color=Theme.BUTTON_SUBTLE).pack(side='left', padx=4)
        self.topbar_actions = ctk.CTkFrame(self.topbar_frame, fg_color='transparent')
        self.topbar_actions.pack(side='right', padx=16)
        self.toolbar_frame = ctk.CTkFrame(self, fg_color=Theme.BG_PRIMARY)
        self.toolbar_frame.grid(row=1, column=1, sticky="ew", padx=16, pady=(12, 10))
        project_row = ctk.CTkFrame(self.toolbar_frame, fg_color="transparent")
        project_row.pack(fill="x")
        ctk.CTkLabel(project_row, text="Sheet:", text_color=Theme.TEXT_MUTED).pack(side="left", padx=(8, 3))
        self.sheet_display_var = tk.StringVar(value="Sheet 1")
        self.sheet_combo = ctk.CTkComboBox(
            project_row, width=150, variable=self.sheet_display_var,
            values=["Sheet 1"], command=self._on_sheet_selected,
        )
        self.sheet_combo.pack(side="left", padx=3)

        ctk.CTkLabel(project_row, text="Sort:", text_color=Theme.TEXT_MUTED).pack(side="left", padx=(12, 3))
        self.sort_combo = ctk.CTkComboBox(
            project_row, width=125, values=["timestamp", "timestamp_desc", "frame", "duration", "faces", "face_size", "confidence", "occurrences", "face_group", "manual"],
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
        self.zoom_slider = ctk.CTkSlider(zoom_row, from_=0.01, to=5.0, variable=self.zoom_level_var,
                                        command=self.preview_zoomable_canvas.set_zoom, width=150, progress_color=Theme.ACCENT_BLUE)
        self.zoom_slider.pack(side="left", padx=5)
        ctk.CTkButton(zoom_row, text='Fit', width=45, height=26,
                      command=self.preview_zoomable_canvas.fit_to_window, fg_color=Theme.BUTTON_SUBTLE).pack(side='left', padx=4)
        ctk.CTkButton(zoom_row, text='Player', width=65, height=26,
                      command=self.open_player, fg_color=Theme.BUTTON_SUBTLE).pack(side='left', padx=4)
        ctk.CTkButton(zoom_row, text='Sheet tools ▾', width=110, height=26,
                      command=self.show_sheet_tools, fg_color=Theme.BUTTON_SUBTLE).pack(side='left', padx=3)
        self.editing_hint = ctk.CTkLabel(self.toolbar_frame,
            text='Drag a frame to scrub · Shift-drag to reorder · Right-click for frame tools',
            text_color=Theme.TEXT_MUTED, anchor='w', justify='left', wraplength=420)
        self.editing_hint.pack(fill='x', padx=8, pady=(5, 0))
        self._refresh_sheet_controls()

    def _build_action_footer(self):
        self.action_frame = ctk.CTkFrame(self, height=60, fg_color=Theme.BG_SECONDARY)
        self.action_frame.grid(row=3, column=0, columnspan=3, sticky="ew")
        self.action_frame.grid_columnconfigure(0, weight=1)
        
        self.status_lbl = ctk.CTkLabel(self.action_frame, text="Ready", text_color=Theme.TEXT_MUTED)
        self.status_lbl.grid(row=0, column=0, sticky="ew", padx=20, pady=10)
        
        self.progress_bar = ctk.CTkProgressBar(self.action_frame, width=180, progress_color=Theme.ACCENT_GREEN)
        self.progress_bar.set(0)
        self.progress_bar.grid(row=0, column=1, padx=20)
        
        btn_frame = self.topbar_actions
        
        self.preview_btn = ctk.CTkButton(btn_frame, text="Build preview", command=self.start_thumbnail_preview_generation,
                      fg_color="transparent", border_width=1, border_color=Theme.ACCENT_BLUE,
                      text_color=Theme.ACCENT_BLUE, hover_color=Theme.BUTTON_SUBTLE_HOVER)
        self.preview_btn.pack(side="left", padx=5)

        self.cancel_btn = ctk.CTkButton(
            self.action_frame, text="Cancel", command=self.cancel_active_job, width=86,
            fg_color="transparent", border_width=1, border_color=Theme.DANGER_RED,
            text_color=Theme.DANGER_RED_HOVER, hover_color=Theme.BUTTON_SUBTLE_HOVER,
        )
        self.cancel_btn.grid(row=0, column=2, padx=(0, 16))
        self.cancel_btn.configure(state="disabled")
        
        self.save_btn = ctk.CTkButton(btn_frame, text="Export movieprint", command=self.generate_movieprint_action,
                                      fg_color=Theme.ACTION_GOLD, text_color=Theme.TEXT_DARK,
                                      hover_color=Theme.ACTION_GOLD_HOVER, font=Theme.FONT_BOLD, width=150)
        self.save_btn.pack(side="left", padx=5)

    def _create_landing_page(self, parent):
        parent.grid_columnconfigure(0, weight=1)
        parent.grid_rowconfigure(0, weight=1)
        parent.grid_rowconfigure(2, weight=1)
        card = ctk.CTkFrame(parent, fg_color=Theme.PANEL, corner_radius=16,
                           border_width=1, border_color=Theme.BG_TERTIARY)
        card.grid(row=1, column=0, padx=24, sticky='ew')
        ctk.CTkLabel(card, text='Your next movieprint starts here',
                     font=(Theme.FONT_FAMILY, 22, 'bold'), wraplength=380).pack(padx=24, pady=(34, 12))
        ctk.CTkLabel(card, text='Add or drop a video to preview it automatically.\nAdjust your sheet, then export when you’re ready.',
                     text_color=Theme.TEXT_MUTED, justify='center', wraplength=360).pack(padx=24, pady=(0, 24))
        ctk.CTkButton(card, text='Add video & preview…', command=self.browse_input_paths,
                      width=170, height=36).pack(pady=(0, 28))
        ctk.CTkLabel(parent, text='Drag to scrub  ·  Shift-drag to reorder  ·  Right-click for more',
                     text_color=Theme.TEXT_MUTED, wraplength=420).grid(row=3, column=0, pady=14)
        if self.dnd_active:
            try:
                parent.drop_target_register(DND_FILES)
                parent.dnd_bind('<<Drop>>', self.handle_drop)
            except Exception:
                logging.getLogger(__name__).warning('Could not enable workspace drag and drop', exc_info=True)

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
        settings_parent = parent
        self.live_math_frame = ctk.CTkFrame(parent, fg_color=Theme.PANEL_SOFT, corner_radius=8)
        self.live_math_frame.pack(fill="x", padx=10, pady=(0, 12))
        font_lg = (Theme.FONT_FAMILY, 20, "bold")
        
        self.math_lbl_cols = ctk.CTkLabel(self.live_math_frame, text="5", font=font_lg, text_color="white")
        self.math_lbl_cols.pack(side="left", expand=True)
        ctk.CTkLabel(self.live_math_frame, text="x", font=(Theme.FONT_FAMILY, 24), text_color=Theme.TEXT_MUTED).pack(side="left")
        self.math_lbl_rows = ctk.CTkLabel(self.live_math_frame, text="?", font=font_lg, text_color="white")
        self.math_lbl_rows.pack(side="left", expand=True)
        ctk.CTkLabel(self.live_math_frame, text="=", font=(Theme.FONT_FAMILY, 24), text_color=Theme.TEXT_MUTED).pack(side="left")
        self.math_lbl_res = ctk.CTkLabel(self.live_math_frame, text="?", font=font_lg, text_color=Theme.ACTION_GOLD)
        self.math_lbl_res.pack(side="left", expand=True)

        parent = self.sidebar_frame
        self.input_tabs = ctk.CTkTabview(parent, height=180, fg_color=Theme.PANEL, text_color=Theme.TEXT_MAIN,
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
        self.input_entry.bind('<Return>', lambda _event: self.start_thumbnail_preview_generation())
        ctk.CTkButton(single_tab, text="Add video & preview…", command=self.browse_input_paths, fg_color=Theme.ACCENT_BLUE,
                      text_color=Theme.TEXT_DARK, hover_color=Theme.ACCENT_BLUE_HOVER).pack(fill="x", padx=0, pady=10)
        ctk.CTkLabel(single_tab, text='Pasted a path? Press Enter to preview.',
                     text_color=Theme.TEXT_MUTED, wraplength=240).pack(fill='x')

        batch_tab = self.input_tabs.tab("Batch Queue")
        list_container = ctk.CTkFrame(batch_tab, fg_color=Theme.BG_TERTIARY, height=150)
        list_container.pack(fill="x", padx=0, pady=(10,5))
        list_container.pack_propagate(False)
        self.batch_listbox = tk.Listbox(list_container, bg=Theme.BG_TERTIARY, fg="white", borderwidth=0, highlightthickness=0, selectmode="extended",
            font=(Theme.FONT_FAMILY, -round(13*self._get_window_scaling())))
        self.batch_listbox.pack(side="left", fill="both", expand=True, padx=5, pady=5)
        for path in self.batch_file_list:
            self.batch_listbox.insert(tk.END, path)
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
                      fg_color=Theme.ACCENT_BLUE, text_color=Theme.TEXT_DARK,
                      hover_color=Theme.ACCENT_BLUE_HOVER).pack(fill='x', pady=2)
        ctk.CTkButton(batch_ctrl_frame, text="Add Folder", command=self.browse_batch_folder, width=96,
                      fg_color=Theme.BUTTON_SUBTLE, hover_color=Theme.BUTTON_SUBTLE_HOVER).pack(fill='x', pady=2)
        ctk.CTkButton(batch_ctrl_frame, text="Clear", command=self.clear_batch_list, width=60,
                      fg_color=Theme.DANGER_RED, hover_color=Theme.DANGER_RED_HOVER).pack(fill='x', pady=2)
        ctk.CTkButton(batch_ctrl_frame, text="Remove Selected", command=self.remove_batch_item, width=120,
                      fg_color="transparent", border_width=1, border_color=Theme.DANGER_RED,
                      text_color=Theme.DANGER_RED_HOVER, hover_color=Theme.BUTTON_SUBTLE_HOVER).pack(fill='x', pady=2)
        
        # Folder discovery
        ctk.CTkCheckBox(parent, text="Recursive Folder Scan", variable=self.recursive_scan_var, 
                        text_color=Theme.TEXT_MUTED, fg_color=Theme.ACCENT_GREEN,
                        hover_color=Theme.ACCENT_GREEN_HOVER).pack(fill="x", padx=15, pady=(0, 10))

        parent = settings_parent
        self._create_cyber_slider_section(parent)
        
        # Output dimensions
        dims_frame = CTkCollapsibleFrame(parent, title="Output")
        dims_frame.pack(fill="x", padx=10, pady=5)
        self._populate_dimensions_settings(dims_frame.get_content_frame())

        adv_frame = CTkCollapsibleFrame(parent, title="Layout, style & export", start_open=True)
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

        ctk.CTkLabel(parent, text="Thumbnails will crop to fit exactly.", font=(Theme.FONT_FAMILY, 12), text_color=Theme.TEXT_MUTED).pack(anchor="w", pady=(5,0))

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
        ctk.CTkLabel(parent, text='Timeline minutes/row (0 = automatic):').pack(anchor='w', pady=(6, 0))
        timeline_entry = ctk.CTkEntry(parent, textvariable=self.timeline_minutes_per_row_var)
        timeline_entry.pack(fill='x', pady=3)
        timeline_entry.bind('<Return>', self.quick_refresh_layout)
        
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
        self.output_path_preview = ctk.CTkLabel(parent, text='', anchor='w', justify='left',
                                               wraplength=310, text_color=Theme.TEXT_MUTED)
        self.output_path_preview.pack(fill='x', pady=4)
        ctk.CTkLabel(parent, text='Filename tokens: {movie}  {sheet}', text_color=Theme.TEXT_MUTED).pack(anchor='w')
        if not getattr(self, '_output_preview_traces_bound', False):
            for variable in (self.input_paths_var, self.output_filename_var, self.output_filename_suffix_var,
                             self.output_naming_mode_var, self.output_dir_var, self.frame_format_var,
                             self.output_frames_only_var, self.individual_frames_output_dir_var):
                variable.trace_add('write', lambda *_: self._update_output_preview())
            self._output_preview_traces_bound = True
        
        ctk.CTkLabel(parent, text="Output Location:", text_color=Theme.TEXT_MUTED).pack(anchor="w", pady=(15, 0))
        self.save_next_to_video_var = tk.BooleanVar(value=not self.output_dir_var.get().strip())
        self.save_next_to_video_cb = ctk.CTkCheckBox(parent, text='Save next to each video file',
            variable=self.save_next_to_video_var, command=self._toggle_save_next_to_video)
        self.save_next_to_video_cb.pack(anchor='w', pady=(4, 6))
        location_row = ctk.CTkFrame(parent, fg_color='transparent')
        location_row.pack(fill='x', pady=5)
        ctk.CTkEntry(location_row, textvariable=self.output_dir_var,
                     placeholder_text='Or choose an output folder').pack(side='left', fill='x', expand=True)
        ctk.CTkButton(location_row, text='Browse', width=70, command=self.browse_movieprint_output_dir).pack(side='left', padx=(6, 0))
        self.output_destination_hint = ctk.CTkLabel(parent, text='', wraplength=250,
            justify='left', anchor='w', text_color=Theme.TEXT_MUTED)
        self.output_destination_hint.pack(fill='x', pady=(0, 6))
        self._sync_output_destination()

        self.output_frames_only_cb = ctk.CTkCheckBox(
            parent,
            text="Export individual frames only",
            variable=self.output_frames_only_var,
            fg_color=Theme.ACTION_GOLD,
            hover_color=Theme.ACTION_GOLD_HOVER,
            command=self._toggle_frame_export_options,
        )
        self.output_frames_only_cb.pack(anchor="w", pady=(4, 2))
        ctk.CTkCheckBox(parent, text='Also export individual frames', variable=self.include_individual_frames_var,
                        command=self._toggle_frame_export_options).pack(anchor='w', pady=4)

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

        # Existing output policy
        ctk.CTkLabel(parent, text="Existing Files:").pack(anchor="w", pady=(5,0))
        self.overwrite_seg = ctk.CTkSegmentedButton(parent, values=["overwrite", "skip"], variable=self.overwrite_mode_var,
                                                   selected_color=Theme.ACTION_GOLD, selected_hover_color=Theme.ACTION_GOLD_HOVER)
        self.overwrite_seg.pack(fill="x", pady=5)


        ctk.CTkSwitch(parent, text="Show Frame Info/Timecode", variable=self.frame_info_show_var, progress_color=Theme.ACCENT_GREEN, command=self.quick_refresh_layout).pack(anchor="w", pady=5)
        ctk.CTkCheckBox(parent, text="Detect Faces", variable=self.detect_faces_var, fg_color=Theme.ACCENT_GREEN, hover_color=Theme.ACCENT_GREEN_HOVER).pack(anchor="w", pady=2)
        ctk.CTkCheckBox(parent, text="Use GPU (FFmpeg)", variable=self.use_gpu_var, fg_color=Theme.ACCENT_GREEN, hover_color=Theme.ACCENT_GREEN_HOVER).pack(anchor="w", pady=2)
        ctk.CTkCheckBox(parent, text="Show Header (Filename)", variable=self.show_header_var, fg_color=Theme.ACCENT_GREEN, hover_color=Theme.ACCENT_GREEN_HOVER, command=self.quick_refresh_layout).pack(anchor="w", pady=2)
        ctk.CTkCheckBox(parent, text='Header timeline markers', variable=self.show_header_timeline_var,
                        command=self.quick_refresh_layout).pack(anchor='w', pady=2)
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
        ctk.CTkButton(parent, text='Preview / draw crop…', command=self.crop_preview_action,
                      fg_color=Theme.BUTTON_SUBTLE).pack(fill='x', pady=4)
        
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
        ctk.CTkLabel(parent, text='Cached frame width (0 = native; next preview):').pack(anchor='w', pady=(8, 0))
        ctk.CTkEntry(parent, textvariable=self.cache_max_width_var).pack(fill='x', pady=3)
        ctk.CTkLabel(parent, text="Output Quality (JPG):").pack(anchor="w", pady=(10,0))
        ctk.CTkSlider(parent, from_=10, to=100, variable=self.output_quality_var, progress_color=Theme.ACTION_GOLD).pack(fill="x")
        
        self.update_visibility_state()

    def _populate_hdr_settings(self, parent):
        ctk.CTkLabel(parent, text="HDR to SDR Tone Mapping", font=Theme.FONT_BOLD).pack(anchor="w", pady=(5,0))
        ctk.CTkLabel(parent, text="Converts washed-out HDR colors to normal SDR.", font=(Theme.FONT_FAMILY, 12), text_color=Theme.TEXT_MUTED).pack(anchor="w", pady=(0,5))
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
            enabled = bool(self.output_frames_only_var.get() or self.include_individual_frames_var.get())
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
        control_types = (ctk.CTkButton, ctk.CTkEntry, ctk.CTkComboBox, ctk.CTkSlider,
                         ctk.CTkCheckBox, ctk.CTkSwitch)
        if busy and not getattr(self, '_disabled_job_controls', None):
            self._disabled_job_controls = []
            def disable_controls(widget):
                if isinstance(widget, control_types):
                    self._disabled_job_controls.append((widget, widget.cget('state')))
                    widget.configure(state='disabled')
                    return
                for child in widget.winfo_children():
                    disable_controls(child)
            for panel in (getattr(self, 'sidebar_frame', None), getattr(self, 'toolbar_frame', None),
                          getattr(self, 'inspector_frame', None), getattr(self, 'topbar_frame', None)):
                if panel is not None:
                    disable_controls(panel)
        elif not busy:
            for widget, previous_state in getattr(self, '_disabled_job_controls', []):
                if widget.winfo_exists():
                    widget.configure(state=previous_state)
            self._disabled_job_controls = []
        if busy:
            self.scrubbing_handler._stop_event.set()
            self.scrubbing_handler.session_id += 1
            self.scrubbing_handler.active = False
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
        self.input_tabs.configure(height=360 if active == 'Batch Queue' else 180)
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
        # A theme change is purely visual. Never reconstruct widgets or reload
        # project state: doing so loses the live preview, view and open tools.
        roles = list(Theme.PRESETS[Theme.CURRENT]) + ['TEXT_DARK', 'BUTTON_SUBTLE', 'BUTTON_SUBTLE_HOVER']
        old_colors = {role: getattr(Theme, role) for role in roles}
        self._applying_theme = True
        try:
            Theme.apply_preset(value)
            replacements = {old.lower(): getattr(Theme, role) for role, old in old_colors.items()}
            def recolor(color):
                if isinstance(color, (list, tuple)):
                    return tuple(recolor(c) for c in color)
                return replacements.get(color.lower(), color) if isinstance(color, str) else color
            options = ('fg_color', 'bg_color', 'text_color', 'hover_color', 'border_color',
                       'progress_color', 'button_color', 'button_hover_color',
                       'selected_color', 'selected_hover_color', 'unselected_color',
                       'unselected_hover_color', 'dropdown_fg_color', 'dropdown_hover_color',
                       'dropdown_text_color', 'background', 'foreground', 'selectbackground')
            def repaint(widget):
                for option in options:
                    try:
                        old = widget.cget(option)
                    except (ValueError, tk.TclError, AttributeError):
                        continue  # This widget does not expose this colour option.
                    new = recolor(old)
                    if new != old:
                        widget.configure(**{option: new})
                for child in list(widget.winfo_children()):
                    repaint(child)
            repaint(self)
            style = ttk.Style(self)
            style.configure('MoviePrint.Treeview', background=Theme.BG_SECONDARY,
                            fieldbackground=Theme.BG_SECONDARY)
            style.map('MoviePrint.Treeview', background=[('selected', Theme.ACCENT_BLUE)],
                      foreground=[('selected', Theme.TEXT_DARK)])
            self.ui_theme_var.set(Theme.CURRENT)
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
        if self.is_busy:
            return
        new_state = self.state_manager.undo()
        if new_state: self.refresh_ui_from_state(new_state)

    def perform_redo(self, event=None):
        if self.is_busy:
            return
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
        elif hasattr(self, 'preview_zoomable_canvas'):
            self.preview_zoomable_canvas.clear()
        self._refresh_sheet_controls()
        if hasattr(self, 'hidden_switch'):
            if settings.filter_mode == 'all': self.hidden_switch.select()
            else: self.hidden_switch.deselect()
        self._update_live_math()

    def _restore_grid_visuals(self, state, settings):
        if settings.filter_mode != 'all' and all(item.get('hidden') for item in state.thumbnail_metadata):
            state.thumbnail_layout_data = []
            self.preview_zoomable_canvas.clear()
            return
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
            'show_header_timeline': settings.show_header_timeline,
            'show_file_path': settings.show_file_path,
            'show_timecode': settings.show_timecode,
            'show_frame_num': settings.show_frame_num,
            'frame_info_show': settings.frame_info_show,
            'frame_info_timecode_or_frame': settings.frame_info_timecode_or_frame,
            'frame_info_font_color': settings.frame_info_font_color,
            'frame_info_bg_color': settings.frame_info_bg_color,
            'frame_info_position': settings.frame_info_position,
            'frame_info_size': settings.frame_info_size,
            'frame_info_margin': settings.frame_info_margin,
            'layout_mode': settings.layout_mode,
            'target_row_height': settings.target_row_height,
            'timeline_minutes_per_row': settings.timeline_minutes_per_row,
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

    def _update_output_preview(self):
        if getattr(self, '_applying_theme', False) or not hasattr(self, 'output_path_preview'):
            return
        self._sync_output_destination()
        try:
            inputs = [p.strip() for p in self.input_paths_var.get().split(';') if p.strip()]
            if not inputs or not os.path.isfile(inputs[0]):
                text = 'Select a video to preview its output path.'
            else:
                settings = argparse.Namespace(output_dir=self.output_dir_var.get().strip(),
                    output_naming_mode=self.output_naming_mode_var.get(), output_filename=self.output_filename_var.get(),
                    output_filename_suffix=self.output_filename_suffix_var.get(), frame_format=self.frame_format_var.get(),
                    sheet_name=self.state_manager.get_state().active_sheet().name,
                    output_frames_only=self.output_frames_only_var.get(),
                    individual_frames_output_dir=self.individual_frames_output_dir_var.get())
                text = DependencyManager.movieprint_maker_module.get_target_output_path(inputs[0], settings)
            self.output_path_preview.configure(text=text)
        except (ValueError, tk.TclError) as error:
            self.output_path_preview.configure(text=f'Check filename: {error}')

    def crop_preview_action(self):
        if self.is_busy:
            return
        item = self._selected_meta()
        if item is None:
            items = self.state_manager.get_state().thumbnail_metadata
            item = items[0] if items else None
        if not item or not os.path.isfile(item.get('frame_path', '')):
            messagebox.showinfo('Crop preview', 'Build a preview first.')
            return
        try:
            with Image.open(item['frame_path']) as source:
                preview = source.convert('RGB')
            preview.thumbnail((900, 550), Image.Resampling.LANCZOS)
        except OSError as error:
            messagebox.showerror('Crop preview', str(error))
            return
        window = ctk.CTkToplevel(self)
        window.title('Draw crop · drag to select the retained area')
        canvas = tk.Canvas(window, width=preview.width, height=preview.height, highlightthickness=0)
        canvas.pack(padx=12, pady=12)
        photo = ImageTk.PhotoImage(preview)
        canvas.image = photo
        canvas.create_image(0, 0, anchor='nw', image=photo)
        rectangle = canvas.create_rectangle(0, 0, preview.width, preview.height, outline='#36B8A9', width=2)
        origin = [0, 0]
        def begin(event):
            origin[:] = [event.x, event.y]
            canvas.coords(rectangle, event.x, event.y, event.x, event.y)
        def drag(event):
            canvas.coords(rectangle, *origin, max(0, min(preview.width, event.x)), max(0, min(preview.height, event.y)))
        def apply():
            if self.is_busy:
                messagebox.showinfo('Crop preview', 'Wait for the current job before applying a crop.', parent=window)
                return
            x1, y1, x2, y2 = canvas.coords(rectangle)
            x1, x2 = sorted((x1, x2))
            y1, y2 = sorted((y1, y2))
            values = [100*y1/preview.height, 100*(preview.width-x2)/preview.width,
                      100*(preview.height-y2)/preview.height, 100*x1/preview.width]
            if x2-x1 < 2 or y2-y1 < 2 or max(values) > 45:
                messagebox.showerror('Crop preview', 'Keep a non-empty area; each edge can crop at most 45%.', parent=window)
                return
            self.state_manager.snapshot()
            for variable, value in zip((self.crop_top_var, self.crop_right_var, self.crop_bottom_var, self.crop_left_var), values):
                variable.set(round(value, 3))
            self.quick_refresh_layout()
            window.destroy()
        canvas.bind('<ButtonPress-1>', begin)
        canvas.bind('<B1-Motion>', drag)
        row = ctk.CTkFrame(window, fg_color='transparent')
        row.pack(fill='x', padx=12, pady=(0, 12))
        ctk.CTkButton(row, text='Reset crop', command=lambda: canvas.coords(rectangle, 0, 0, preview.width, preview.height)).pack(side='left')
        ctk.CTkButton(row, text='Apply crop', command=apply).pack(side='right')

    def _grid_transform_params(self):
        return {
            'show_header_timeline': self.show_header_timeline_var.get(),
            'timeline_minutes_per_row': float(self.timeline_minutes_per_row_var.get() or 0),
            'crop_top': float(self.crop_top_var.get() or 0),
            'crop_right': float(self.crop_right_var.get() or 0),
            'crop_bottom': float(self.crop_bottom_var.get() or 0),
            'crop_left': float(self.crop_left_var.get() or 0),
            'thumbnail_aspect_ratio': self.thumbnail_aspect_ratio_var.get(),
            'sort_mode': self.sort_mode_var.get(),
            'filter_mode': self.filter_mode_var.get(),
        }

    @staticmethod
    def _snapshot_render_metadata(metadata):
        """Copy editable thumbnail state without reusing low-resolution preview files."""
        snapshots = []
        for item in metadata or []:
            snapshot = copy.deepcopy(item)
            snapshot.pop('frame_path', None)
            snapshots.append(snapshot)
        return snapshots

    # --- PROJECT WORKSPACE ---
    def _refresh_sheet_controls(self):
        self._refresh_selected_inspector()
        if not hasattr(self, 'sheet_combo'):
            return
        state = self.state_manager.get_state()
        names = [sheet.name for sheet in state.sheets]
        self.sheet_combo.configure(values=names)
        self.sheet_display_var.set(state.active_sheet().name)
        self._update_output_preview()
        if hasattr(self, 'source_library'):
            self._refreshing_library = True
            try:
                self.source_library.delete(*self.source_library.get_children())
                self._library_sources = {}
                groups = {}
                for sheet in state.sheets:
                    sources = {item.get('video_path') for item in sheet.thumbnail_metadata if item.get('video_path')}
                    source = next(iter(sources)) if len(sources) == 1 else ''
                    if source not in groups:
                        group_id = f'source-{len(groups)}'
                        groups[source] = group_id
                        self._library_sources[group_id] = source
                        self.source_library.insert('', 'end', iid=group_id,
                                                   text=os.path.basename(source) or 'Unassigned sheets', open=True)
                    self.source_library.insert(groups[source], 'end', iid=sheet.id,
                                               text=f'{sheet.name}  ·  {len(sheet.thumbnail_metadata)} frames')
                self.source_library.selection_set(state.active_sheet_id)
            finally:
                self._refreshing_library = False

    def _library_selected(self, event=None):
        if self.is_busy or getattr(self, '_refreshing_library', False):
            return
        selection = self.source_library.selection()
        if not selection:
            return
        identity = selection[0]
        source = self._library_sources.get(identity)
        if source:
            self._set_single_source_paths([source])
            self.selected_thumbnail_index = None
        else:
            state = self.state_manager.get_state()
            sheet = next((item for item in state.sheets if item.id == identity), None)
            if sheet and sheet.id != state.active_sheet_id:
                self._on_sheet_selected(sheet.name)

    def _on_sheet_selected(self, sheet_name):
        if self.is_busy:
            self._refresh_sheet_controls()
            return
        self.scrubbing_handler._stop_event.set()
        self.scrubbing_handler.session_id += 1
        state = self.state_manager.get_state()
        target = next((sheet for sheet in state.sheets if sheet.name == sheet_name), None)
        if not target or target.id == state.active_sheet_id:
            return
        self.state_manager.switch_sheet(target.id)
        self.selected_thumbnail_index = None
        self.refresh_ui_from_state(self.state_manager.get_state())
        self.quick_refresh_layout()

    def add_sheet(self):
        if self.is_busy:
            return
        self.state_manager.add_sheet()
        self.selected_thumbnail_index = None
        self._refresh_sheet_controls()
        self.preview_zoomable_canvas.clear()
        self.status_lbl.configure(text="New sheet ready. Click Preview to populate it.")

    def duplicate_sheet(self):
        if self.is_busy:
            return
        self.state_manager.add_sheet(duplicate_active=True)
        self._refresh_sheet_controls()
        self.quick_refresh_layout()

    def delete_sheet(self):
        if self.is_busy:
            return
        if not self.state_manager.remove_active_sheet():
            messagebox.showinfo("Sheets", "A project must keep at least one sheet.")
            return
        self.selected_thumbnail_index = None
        self._refresh_sheet_controls()
        self.refresh_ui_from_state(self.state_manager.get_state())
        self.quick_refresh_layout()

    def _toggle_hidden_filter(self):
        self.filter_mode_var.set("all" if self.hidden_switch.get() else "visible")
        self.quick_refresh_layout()

    def save_project_action(self):
        state = self.state_manager.get_state()
        state.source_paths = [p.strip() for p in self.input_paths_var.get().split(';') if p.strip()]
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
        if self.is_busy:
            return
        path = filedialog.askopenfilename(
            title="Open PyMoviePrint Project",
            filetypes=[
                ("Editable PyMoviePrint", "*.json *.png"),
                ("PyMoviePrint Project", "*.json"),
                ("PyMoviePrint PNG", "*.png"),
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
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as error:
            messagebox.showerror("Project Open Error", str(error))

    def _prepare_loaded_project_frames(self, state):
        """Re-extract referenced frames so projects remain portable across machines."""
        missing = any(
            not item.get('frame_path') or not os.path.exists(item.get('frame_path', ''))
            for sheet in state.sheets for item in sheet.thumbnail_metadata
        )
        if not missing:
            if not self.preview_temp_dir:
                self.preview_temp_dir = tempfile.mkdtemp(prefix="movieprint_project_")
            return
        sources = list(state.source_paths or state.settings.input_paths)
        referenced = {item.get('video_path') for sheet in state.sheets
                      for item in sheet.thumbnail_metadata if item.get('video_path')}
        if not referenced:
            referenced = set(sources)
        replacements = {}
        for original in sorted(referenced or {''}):
            if original and os.path.isfile(original):
                continue
            replacement = filedialog.askopenfilename(
                title=f"Locate source video: {os.path.basename(original) or 'project source'}",
                filetypes=[("Video files", "*.mp4 *.mov *.mkv *.avi *.wmv *.flv"), ("All files", "*.*")],
            )
            if not replacement:
                raise ValueError("The source video referenced by this project could not be found.")
            replacements[original] = os.path.abspath(replacement)
        sources = sorted({replacements.get(path, path) for path in referenced})
        state.source_paths = list(sources)
        state.settings.input_paths = list(sources)
        for sheet in state.sheets:
            sheet.settings['input_paths'] = [replacements.get(p, p) for p in sheet.settings.get('input_paths', sources)]
            for item in sheet.thumbnail_metadata:
                original = item.get('video_path')
                if original in replacements:
                    item['video_path'] = replacements[original]
                elif not original:
                    if len(sources) != 1:
                        raise ValueError("A thumbnail has no source identity in a multi-video project.")
                    item['video_path'] = sources[0]
        if self.preview_temp_dir and os.path.exists(self.preview_temp_dir):
            self.temp_dirs_to_cleanup.append(self.preview_temp_dir)
        self.preview_temp_dir = tempfile.mkdtemp(prefix="movieprint_project_")
        video_path = next((path for path in sources if os.path.exists(path)), sources[0])
        cv2 = DependencyManager.video_processing.cv2
        cap = cv2.VideoCapture(video_path)
        fps = float(cap.get(cv2.CAP_PROP_FPS) or 25.0) if cap.isOpened() else 25.0
        video_width = float(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 1.0) if cap.isOpened() else 1.0
        video_height = float(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 1.0) if cap.isOpened() else 1.0
        if cap.isOpened(): cap.release()
        if getattr(state.settings, 'crop_units', 'percent') == 'pixels':
            state.settings.crop_top = state.settings.crop_top * 100.0 / video_height
            state.settings.crop_bottom = state.settings.crop_bottom * 100.0 / video_height
            state.settings.crop_left = state.settings.crop_left * 100.0 / video_width
            state.settings.crop_right = state.settings.crop_right * 100.0 / video_width
            state.settings.crop_units = 'percent'
        for sheet_index, sheet in enumerate(state.sheets):
            sheet_dir = os.path.join(self.preview_temp_dir, f"sheet_{sheet_index + 1}")
            os.makedirs(sheet_dir, exist_ok=True)
            extractors = {}
            try:
                for item_index, item in enumerate(sheet.thumbnail_metadata):
                    if item.get('frame_path') and os.path.exists(item['frame_path']):
                        continue
                    item_source = item.get('video_path')
                    if not item_source or not os.path.exists(item_source):
                        raise ValueError("A thumbnail's source video is unavailable.")
                    if item_source not in extractors:
                        extractors[item_source] = DependencyManager.video_processing.VideoExtractor(item_source, logging.getLogger("project_open"))
                        extractors[item_source].__enter__()
                    extractor = extractors[item_source]
                    timestamp = item.get('timestamp_sec')
                    if timestamp is None and item.get('frame_number') is not None:
                        source_fps = float(extractor.properties[0] or fps or 25.0)
                        timestamp = float(item['frame_number']) / max(source_fps, 0.001)
                    timestamp = float(timestamp or 0.0)
                    frame = extractor.extract_single_frame(timestamp)
                    if frame is None:
                        raise ValueError(f"Could not recover frame at {timestamp:.3f}s from {item_source}.")
                    frame_path = os.path.join(sheet_dir, f"frame_{item_index + 1:05d}.jpg")
                    if not cv2.imwrite(frame_path, frame):
                        raise ValueError(f"Could not save recovered frame: {frame_path}")
                    item['frame_path'] = frame_path
                    item['timestamp_sec'] = timestamp
                    item['video_path'] = item_source
                    item['video_filename'] = os.path.basename(item_source)
                    item['needs_extraction'] = False
            finally:
                for extractor in extractors.values():
                    extractor.__exit__(None, None, None)
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
        if self.is_busy:
            return
        index = self._thumbnail_index_at_event(event)
        if index is None:
            return
        self.selected_thumbnail_index = index
        self._refresh_selected_inspector()
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
        menu.add_command(label="Explore scene in new sheet", command=self.explore_scene_action)
        menu.add_command(label="Cut scene...", command=self.cut_scene_action)
        menu.add_command(label="Merge with next scene", command=self.merge_scene_action)
        menu.add_separator()
        menu.add_command(label="Previous frame", command=lambda: self.step_selected_frame(-1))
        menu.add_command(label="Next frame", command=lambda: self.step_selected_frame(1))
        faces = self._selected_meta().get('face_detection', {}).get('faces', [])
        for face in faces:
            group = face.get('group')
            if group:
                menu.add_command(label=f"Find face group {group} ({face.get('occurrences', 0)} frames)",
                                 command=lambda g=group: self.find_face_occurrences(g))
        menu.tk_popup(event.x_root, event.y_root)

    def _refresh_selected_inspector(self):
        if not hasattr(self, 'selection_title'):
            return
        item = self._selected_meta()
        if item is None:
            self.selection_title.configure(text='Sheet settings')
            self.selection_detail.configure(text='Select a frame on the canvas to edit it.\nLayout and export settings are below.')
            self.selection_actions.pack_forget()
        else:
            self.selection_title.configure(text=f'Frame {self.selected_thumbnail_index + 1}')
            source = os.path.basename(item.get('video_path', '')) or 'Source video'
            visibility = 'Hidden from export' if item.get('hidden') else 'Included in export'
            self.selection_detail.configure(text=f"{source}\n{float(item.get('timestamp_sec') or 0):.3f} seconds · {visibility}")
            self.selection_actions.pack(fill='x', padx=12, pady=(0, 12))

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
        if item.get('video_path'):
            return item['video_path'] if os.path.isfile(item['video_path']) else ''
        candidates = [p.strip() for p in self.input_paths_var.get().split(';') if p.strip()]
        return next((path for path in candidates if os.path.isfile(path)), "")

    def rename_sheet_action(self):
        if self.is_busy:
            return
        state = self.state_manager.get_state()
        name = simpledialog.askstring('Rename sheet', 'Sheet name:', initialvalue=state.active_sheet().name)
        if name is not None:
            try:
                self.state_manager.snapshot()
                workspace_tools.rename_sheet(state, name)
                self._refresh_sheet_controls()
            except ValueError as error:
                messagebox.showerror('Rename sheet', str(error))

    def show_sheet_tools(self):
        menu = tk.Menu(self, tearoff=0)
        for label, command in (('Rename sheet', self.rename_sheet_action),
                               ('Export all sheets', self.export_all_sheets_action),
                               ('Export EDL', self.export_edl_action), ('Find faces (local)', self.analyze_faces_action),
                               ('Cut strength chart', self.show_detection_chart),
                               ('Automatic IN/OUT (trim black ends)', self.auto_range_action),
                               ('Crop preview', self.crop_preview_action)):
            menu.add_command(label=label, command=command)
        menu.tk_popup(self.winfo_pointerx(), self.winfo_pointery())

    def show_detection_chart(self):
        items = [item for item in self.state_manager.get_state().thumbnail_metadata if 'boundary_score' in item]
        if not items:
            messagebox.showinfo('Cut strength', 'Build a Shot preview first. This chart shows the detector score at each scene start.')
            return
        window = ctk.CTkToplevel(self)
        window.title('Cut strength at scene starts')
        canvas = tk.Canvas(window, width=800, height=350, bg=Theme.BG_PRIMARY, highlightthickness=0)
        canvas.pack(padx=12, pady=12)
        threshold = float(self.shot_threshold_var.get())
        maximum = max(threshold, max(float(item['boundary_score']) for item in items), 1)
        for index, item in enumerate(items):
            x = 45 + index*710/max(len(items), 1)
            y = 300 - float(item['boundary_score'])*260/maximum
            canvas.create_rectangle(x, y, x+max(2, 700/len(items)-2), 300, fill=Theme.ACCENT_BLUE, outline='')
        threshold_y = 300-threshold*260/maximum
        canvas.create_line(40, threshold_y, 770, threshold_y, fill='#E8B66D', dash=(4, 4))
        canvas.create_text(45, 320, anchor='w', fill='#DCE5EA', text=f'{len(items)} scenes · threshold {threshold:g} · left to right: scene order')

    def auto_range_action(self):
        if self.is_busy:
            return
        source = self._source_video_path()
        if not source:
            messagebox.showerror('Automatic IN/OUT', 'Choose an available source video first.')
            return
        self.active_cancel_event = threading.Event()
        self.active_job_kind = 'automatic IN/OUT'
        self._set_busy(True)
        self.status_lbl.configure(text='Finding leading and trailing black sections…')
        self._job_thread = threading.Thread(target=self._auto_range_worker, args=(source, self.active_cancel_event), daemon=True)
        self._job_thread.start()

    def _auto_range_worker(self, source, cancel_event):
        try:
            bounds = DependencyManager.video_processing.detect_content_range(source, logging.getLogger(__name__), cancel_event)
            if not cancel_event.is_set():
                self.queue.put(('range_done', bounds))
        except InterruptedError:
            self.queue.put(('log', 'Automatic IN/OUT cancelled.'))
        except Exception as error:
            logging.getLogger(__name__).exception('Automatic IN/OUT failed')
            self.queue.put(('tool_failed', dict(title='Automatic IN/OUT', reason=str(error))))
        finally:
            self.queue.put(('busy', False))

    def analyze_faces_action(self):
        if self.is_busy:
            return
        items = self.state_manager.get_state().thumbnail_metadata
        if not items:
            messagebox.showinfo('Find faces', 'Build a preview first.')
            return
        if not messagebox.askyesno('Local face matching',
                'Analyse faces locally? The first run downloads about 39 MB of OpenCV models. '
                'Your images stay on this computer. Face groups are suggested matches, not guaranteed identities.'):
            return
        self.active_cancel_event = threading.Event()
        self.active_job_kind = 'face analysis'
        self._set_busy(True)
        self._job_thread = threading.Thread(target=self._face_analysis_worker,
            args=(copy.deepcopy(items), self.active_cancel_event), daemon=True)
        self._job_thread.start()

    def _face_analysis_worker(self, items, cancel_event):
        try:
            result = DependencyManager.face_analysis.analyze(items, cancel_event, self._gui_progress_callback)
            if not cancel_event.is_set():
                self.queue.put(('faces_done', result))
        except InterruptedError:
            self.queue.put(('log', 'Face analysis cancelled. No edits were changed.'))
        except Exception as error:
            logging.getLogger(__name__).exception('Face analysis failed')
            self.queue.put(('tool_failed', {'title': 'Face analysis', 'reason': str(error)}))
        finally:
            self.queue.put(('busy', False))

    def find_face_occurrences(self, group):
        if self.is_busy:
            return
        state = self.state_manager.get_state()
        frames = [copy.deepcopy(item) for item in state.thumbnail_metadata
                  if any(face.get('group') == group for face in item.get('face_detection', {}).get('faces', []))]
        if not frames:
            return
        parent = state.active_sheet_id
        self.state_manager.add_sheet()
        state = self.state_manager.get_state()
        state.active_sheet().parent_sheet_id = parent
        state.thumbnail_metadata = frames
        state.settings.sort_mode = 'timestamp'
        state.sync_active_sheet()
        self.refresh_ui_from_state(state)

    def export_all_sheets_action(self):
        if self.is_busy:
            return
        destination = filedialog.askdirectory(title='Export all sheets to folder')
        if not destination:
            return
        state = self.state_manager.get_state()
        state.sync_active_sheet()
        try:
            jobs = [workspace_tools.sheet_export_settings(sheet, destination, i)
                    for i, sheet in enumerate(state.sheets, 1)]
        except ValueError as error:
            messagebox.showerror('Export all sheets', str(error))
            return
        self.active_cancel_event = threading.Event()
        self.active_job_kind = 'generation'
        self._set_busy(True)
        self.progress_bar.configure(mode='determinate')
        self._job_thread = threading.Thread(target=self._export_sheets_worker, args=(jobs, self.active_cancel_event), daemon=True)
        self._job_thread.start()

    def _export_sheets_worker(self, jobs, cancel_event):
        succeeded, failed, skipped = [], [], 0
        logger = logging.getLogger('sheet_export')
        handler = QueueHandler(self.queue)
        logger.addHandler(handler)
        try:
            for index, settings in enumerate(jobs):
                if cancel_event.is_set():
                    break
                settings.cancel_event = cancel_event
                self.queue.put(('progress', (index, len(jobs), settings.output_filename)))
                try:
                    good, bad = DependencyManager.movieprint_maker(settings, logger)
                    succeeded.extend(good)
                    failed.extend(bad)
                    skipped += getattr(settings, 'skipped_count', 0)
                except Exception as error:
                    logger.exception('Sheet export failed')
                    failed.append({'video': settings.output_filename, 'reason': str(error)})
        finally:
            logger.removeHandler(handler)
            self.queue.put(('generation_done', dict(successful_ops=succeeded, failed_ops=failed,
                                                   skipped_count=skipped, cancelled=cancel_event.is_set())))
            self.queue.put(('busy', False))

    def _selected_fps(self):
        source = self._source_video_path()
        if not source:
            raise ValueError('The source video is not available.')
        with DependencyManager.video_processing.VideoExtractor(source, logging.getLogger(__name__)) as extractor:
            return float(extractor.properties[0]) or 25.0

    def step_selected_frame(self, direction):
        item = self._selected_meta()
        if item is None or self.is_busy:
            return
        try:
            self.replace_selected_thumbnail(max(0, float(item.get('timestamp_sec', 0)) + direction / self._selected_fps()))
        except ValueError as error:
            messagebox.showerror('Frame step', str(error))

    def _materialize_scene(self, scene):
        frame = self._extract_frame_metadata(scene['timestamp_sec'])
        scene.update(frame)
        return scene

    def cut_scene_action(self):
        item = self._selected_meta()
        if item is None or self.is_busy:
            return
        try:
            fps = self._selected_fps()
            start, end = workspace_tools.scene_bounds(item, fps)
            cut = simpledialog.askfloat('Cut scene', f'Cut time in seconds ({start:.3f}–{end:.3f}):', initialvalue=(start+end)/2)
            if cut is None:
                return
            scenes = [self._materialize_scene(s) for s in workspace_tools.split_scene(item, cut, fps)]
            self.state_manager.snapshot()
            i = self.selected_thumbnail_index
            self.state_manager.get_state().thumbnail_metadata[i:i+1] = scenes
            self.quick_refresh_layout()
        except (ValueError, OSError) as error:
            messagebox.showerror('Cut scene', str(error))

    def merge_scene_action(self):
        item = self._selected_meta()
        if item is None or self.is_busy:
            return
        try:
            items = self.state_manager.get_state().thumbnail_metadata
            i = self.selected_thumbnail_index
            if i+1 >= len(items):
                raise ValueError('There is no following scene to merge.')
            merged = self._materialize_scene(workspace_tools.merge_scenes(item, items[i+1], self._selected_fps()))
            self.state_manager.snapshot()
            items[i:i+2] = [merged]
            self.quick_refresh_layout()
        except (ValueError, OSError) as error:
            messagebox.showerror('Merge scenes', str(error))

    def explore_scene_action(self):
        item = self._selected_meta()
        if item is None or self.is_busy:
            return
        try:
            start, end = workspace_tools.scene_bounds(item, self._selected_fps())
            frames = [self._extract_frame_metadata(start+(end-start)*(i+0.5)/12) for i in range(12)]
            parent = self.state_manager.get_state().active_sheet_id
            self.state_manager.add_sheet()
            state = self.state_manager.get_state()
            sheet = state.active_sheet()
            sheet.parent_sheet_id = parent
            sheet.in_point_sec, sheet.out_point_sec = start, end
            state.thumbnail_metadata = frames
            state.settings.input_paths = [item['video_path']]
            state.settings.num_rows, state.settings.num_columns = 3, 4
            state.sync_active_sheet()
            self.refresh_ui_from_state(state)
            self._refresh_sheet_controls()
            self.quick_refresh_layout()
        except (ValueError, OSError) as error:
            messagebox.showerror('Explore scene', str(error))

    def export_edl_action(self):
        if self.is_busy:
            return
        try:
            state = self.state_manager.get_state()
            items = self._metadata_in_display_order()
            sources = {item.get('video_path') for item in items}
            if len(sources) != 1:
                raise ValueError('Export one source video per EDL to preserve its frame rate.')
            fps = self._selected_fps()
            workspace_tools.edl_text(items, state.active_sheet().name, fps)
            path = filedialog.asksaveasfilename(defaultextension='.edl', filetypes=[('Edit decision list', '*.edl')])
            if path:
                workspace_tools.save_edl(path, items, state.active_sheet().name, fps)
                self.status_lbl.configure(text='EDL exported')
        except (ValueError, OSError) as error:
            messagebox.showerror('EDL export', str(error))

    def _extract_frame_metadata(self, timestamp: float, identity: Optional[str] = None):
        video_path = self._source_video_path()
        if not video_path:
            raise ValueError("The source video is not available.")
        if not self.preview_temp_dir:
            self.preview_temp_dir = tempfile.mkdtemp(prefix="movieprint_preview_")
        with DependencyManager.video_processing.VideoExtractor(video_path, logging.getLogger("thumbnail_edit")) as extractor:
            frame = extractor.extract_single_frame(max(0.0, timestamp))
            aspect_ratio = extractor.display_aspect_ratio
        if frame is None:
            raise ValueError("Could not extract that frame from the video.")
        identity = identity or f"thumb-{time.time_ns()}"
        frame_path = os.path.join(self.preview_temp_dir, f"edited_{identity}_{time.time_ns()}.jpg")
        if not DependencyManager.video_processing.cv2.imwrite(frame_path, frame):
            raise ValueError('Could not save the edited frame.')
        cap = DependencyManager.video_processing.cv2.VideoCapture(video_path)
        fps = float(cap.get(DependencyManager.video_processing.cv2.CAP_PROP_FPS) or 25.0) if cap.isOpened() else 25.0
        if cap.isOpened():
            cap.release()
        return {
            'id': identity, 'frame_path': frame_path, 'timestamp_sec': max(0.0, timestamp),
            'frame_number': round(max(0.0, timestamp) * fps),
            'video_path': video_path, 'video_filename': os.path.basename(video_path),
            'aspect_ratio': aspect_ratio,
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
        if self.is_busy:
            return
        item = self._selected_meta()
        if item is None:
            messagebox.showinfo("Player", "Right-click a thumbnail first to select it.")
            return
        try:
            self.state_manager.snapshot()
            replacement = self._extract_frame_metadata(timestamp, item.get('id'))
            replacement.update({key: value for key, value in item.items() if key in {'hidden', 'transform', 'scene_start_sec', 'scene_end_sec', 'duration_frames'}})
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
            temporary = None
            try:
                target_ext = os.path.splitext(path)[1].lower()
                target_format = {'.jpg': 'JPEG', '.jpeg': 'JPEG', '.png': 'PNG'}.get(target_ext)
                if target_format is None:
                    raise ValueError('Choose a .jpg, .jpeg or .png filename.')
                with Image.open(item['frame_path']) as source:
                    source_format = source.format
                    pixels = source.convert('RGB') if target_format == 'JPEG' else source.copy()
                if source_format == target_format:
                    fd, temporary = tempfile.mkstemp(prefix='.movieprint_frame_', suffix=target_ext,
                        dir=os.path.dirname(os.path.abspath(path)))
                    os.close(fd)
                    shutil.copy2(item['frame_path'], temporary)
                    os.replace(temporary, path)
                elif not DependencyManager.image_grid._save_image_optimized(
                        pixels, path, 95, logging.getLogger(__name__)):
                    raise OSError('Could not save the frame. Check the destination and available disk space.')
                self.status_lbl.configure(text=f'Frame saved: {os.path.basename(path)}')
            except (OSError, ValueError) as error:
                logging.getLogger(__name__).warning('Frame export failed', exc_info=True)
                messagebox.showerror('Save frame', str(error))
            finally:
                if temporary and os.path.exists(temporary):
                    os.remove(temporary)

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
            if self.player_window.video_path == video_path:
                self.player_window.focus()
                return
            self.player_window.close()
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
                elif msg_type == 'faces_done':
                    self.state_manager.snapshot()
                    self.state_manager.get_state().thumbnail_metadata = data
                    self.state_manager.get_state().sync_active_sheet()
                    self.quick_refresh_layout()
                    self.status_lbl.configure(text='Face analysis complete. Sort by face group or right-click a frame to find matches.')
                elif msg_type == 'range_done':
                    self.state_manager.snapshot()
                    sheet = self.state_manager.get_state().active_sheet()
                    sheet.in_point_sec, sheet.out_point_sec = data
                    self.status_lbl.configure(text=f'IN {data[0]:.3f}s · OUT {data[1]:.3f}s. Build preview to apply; review dark scenes manually.')
                elif msg_type == 'tool_failed':
                    self.status_lbl.configure(text=f"{data['title']} failed: {data['reason']}")
                    messagebox.showerror(data['title'], data['reason'])
                elif msg_type == "update_thumbnail":
                    if (data.get('session_id') == self.scrubbing_handler.session_id
                            and data.get('sheet_id') == self.state_manager.get_state().active_sheet_id):
                        self.update_thumbnail_in_preview(data['index'], data['image'], data['timestamp'], data.get('frame_number'))
                        if not self.scrubbing_handler.active:
                            self.quick_refresh_layout()
                elif msg_type == "busy":
                    self._set_busy(bool(data))
                self.update_idletasks()
        except queue.Empty: pass
        except Exception as error:
            logging.getLogger('gui_events').exception('Could not process GUI result')
            self.status_lbl.configure(text=f"Could not display result: {error}")
        if not getattr(self, '_closing', False):
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
        
        # Resolve a folder selection to its first discovered video.
        preview_target_path = self._internal_input_paths[0]
        if os.path.isdir(preview_target_path):
            self.status_lbl.configure(text="Scanning directory for preview...")
            # Use maker's discovery logic to find first valid video
            valid_exts = ".mp4,.avi,.mov,.mkv,.flv,.wmv"
            videos = DependencyManager.movieprint_maker_module.discover_video_files(
                [preview_target_path], valid_exts, self.recursive_scan_var.get(), logging.getLogger("preview_scan"))
            if videos:
                preview_target_path = videos[0]
            else:
                messagebox.showerror("Preview Error", "No video files found in the selected directory.")
                return

        if self.preview_temp_dir and os.path.exists(self.preview_temp_dir):
            self.temp_dirs_to_cleanup.append(self.preview_temp_dir)
            
        new_temp_dir = tempfile.mkdtemp(prefix="movieprint_preview_")
        self.temp_dirs_to_cleanup.append(new_temp_dir)
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
            'show_header_timeline': self.show_header_timeline_var.get(),
            'show_file_path': self.show_file_path_var.get(),
            'show_timecode': self.show_timecode_var.get(),
            'show_frame_num': self.show_frame_num_var.get(),
            'target_row_height': int(self.target_row_height_var.get() or 150),
            'timeline_minutes_per_row': float(self.timeline_minutes_per_row_var.get() or 0),
            'frame_info_show': self.frame_info_show_var.get(),
            'frame_info_timecode_or_frame': self.frame_info_timecode_or_frame_var.get(),
            'frame_info_font_color': self.frame_info_font_color_var.get(),
            'frame_info_bg_color': self.frame_info_bg_color_var.get(),
            'frame_info_position': self.frame_info_position_var.get(),
            'frame_info_size': int(self.frame_info_size_var.get()),
            'frame_info_margin': int(self.frame_info_margin_var.get()),
            'preview_quality': int(self.preview_quality_var.get()),
            'cache_max_width': int(self.cache_max_width_var.get() or 0),
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
            'start_time': self.state_manager.get_state().active_sheet().in_point_sec,
            'end_time': self.state_manager.get_state().active_sheet().out_point_sec,
        }

        self.status_lbl.configure(text="Generating Preview...")
        self.progress_bar.configure(mode="indeterminate")
        self.progress_bar.start()
        self.active_cancel_event = preview_settings['cancel_event']
        self.active_job_kind = "preview"
        self._set_busy(True)
        
        self._job_thread = threading.Thread(
            target=self._thumbnail_preview_thread, 
            args=(preview_target_path, new_temp_dir, preview_settings),
            daemon=True
        )
        self._job_thread.start()

    def _thumbnail_preview_thread(self, video_path, temp_dir, config):
        logger = logging.getLogger(f"preview_{threading.get_ident()}")
        queue_handler = QueueHandler(self.queue)
        logger.addHandler(queue_handler)
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
                    detector_threshold=config['shot_threshold'],
                    start_time_sec=config.get('start_time'), end_time_sec=config.get('end_time'),
                    hdr_tonemap=config['hdr_tonemap'], hdr_algorithm=config['hdr_algorithm'],
                    cancel_event=config['cancel_event']
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
                start = config.get('start_time') or 0.0
                end = min(config.get('end_time') if config.get('end_time') is not None else duration, duration)
                if not 0 <= start < end:
                    raise ValueError('The IN/OUT range must lie inside the source video.')
                timestamps = np.linspace(start, end, total_frames+2)[1:-1]
                
                self.queue.put(("log", f"Extracting {total_frames} frames..."))
                
                success, meta = DependencyManager.video_processing.extract_frames_from_timestamps(
                    video_path, timestamps, temp_dir, logger, fast_preview=False,
                    hdr_tonemap=config['hdr_tonemap'], hdr_algorithm=config['hdr_algorithm'],
                    cancel_event=config['cancel_event']
                )
                if len(meta) != total_frames and not config['cancel_event'].is_set():
                    raise ValueError(f'Only {len(meta)} of {total_frames} requested frames could be extracted.')
            
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
                    timeline_minutes_per_row=config.get('timeline_minutes_per_row', 0),
                    background_color_hex=config['bg_color'],
                    padding=config['padding'],
                    grid_margin=config['grid_margin'],
                    logger=logger,
                    rounded_corners=config['rounded'], 
                    rotation=config['rotate_thumbnails'],
                    show_header=config['show_header'],
                    show_header_timeline=config.get('show_header_timeline', False),
                    show_file_path=config['show_file_path'],
                    show_timecode=config['show_timecode'],
                    show_frame_num=config['show_frame_num'],
                    frame_info_show=config['frame_info_show'],
                    frame_info_timecode_or_frame=config['frame_info_timecode_or_frame'],
                    frame_info_font_color=config['frame_info_font_color'],
                    frame_info_bg_color=config['frame_info_bg_color'],
                    frame_info_position=config['frame_info_position'],
                    frame_info_size=config['frame_info_size'],
                    frame_info_margin=config['frame_info_margin'],
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
            logger.removeHandler(queue_handler)
            if failure_reason:
                if config['cancel_event'].is_set():
                    self.queue.put(("preview_cancelled", None))
                else:
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
                        item['face_detection'] = {
                            'num_faces': len(faces),
                            'face_bboxes_thumbnail': [list(map(int, face)) for face in faces],
                        }
                    except Exception as e: logger.warning(f"Face detect error: {e}")
        max_width = int(config.get('cache_max_width') or 0)
        if max_width and max_width < 160:
            raise ValueError('Cached frame width must be zero (native) or at least 160 pixels.')
        if max_width:
            for item in meta_list:
                if config.get('cancel_event') and config['cancel_event'].is_set():
                    return
                with Image.open(item['frame_path']) as source:
                    image = source.copy()
                item['native_width'], item['native_height'] = image.size
                if image.width > max_width:
                    image.thumbnail((max_width, max(1, round(image.height*max_width/image.width))), Image.Resampling.LANCZOS)
                    if not DependencyManager.image_grid._save_image_optimized(image, item['frame_path'], 92, logger):
                        raise ValueError('Could not resize a cached frame.')

    def _handle_preview_done(self, data):
        self.state_manager.snapshot()
        self.selected_thumbnail_index = None
        if data.get('grid_path'):
            self.preview_temp_dir = os.path.dirname(data['grid_path'])
        metadata = data.get("meta") or []
        for index, item in enumerate(metadata):
            item.setdefault('id', f"thumb-{time.time_ns()}-{index + 1}")
            item.setdefault('hidden', False)
        self.state_manager.get_state().thumbnail_metadata = metadata
        self.state_manager.get_state().source_paths = sorted({
            item['video_path'] for sheet in self.state_manager.get_state().sheets
            for item in sheet.thumbnail_metadata if item.get('video_path')
        } | {item['video_path'] for item in metadata if item.get('video_path')})
        self.state_manager.get_state().thumbnail_layout_data = data.get("layout")
        self.state_manager.get_state().sync_active_sheet()
        self._refresh_sheet_controls()
        
        if self.is_landing_state:
            self.landing_frame.grid_remove()
            self.preview_zoomable_canvas.grid(row=0, column=0, sticky="nsew")
            self.is_landing_state = False
            
        if data.get("grid_path"):
            self.preview_zoomable_canvas.set_image(data.get("grid_path"))
            
        self.progress_bar.stop()
        self._update_live_math()
        source = os.path.basename(metadata[0].get('video_path', '')) if metadata else ''
        self.status_lbl.configure(text=f'Preview ready: {source} · {len(metadata)} frames.')
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

        # Each output already contains its generation snapshot, not the live workspace.
        skipped = data.get('skipped_count', 0)
        if skipped and not failure_count and not cancelled:
            summary = f"Generation complete: {success_count} created, {skipped} skipped (already exist)."
            self.status_lbl.configure(text=summary)
            messagebox.showinfo("Generation Complete", summary)
            return

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
        self._refresh_selected_inspector()
        if not self.state_manager.get_state().thumbnail_metadata or not self.preview_temp_dir:
            return
        meta = self.state_manager.get_state().thumbnail_metadata
        if self.filter_mode_var.get() != 'all' and all(item.get('hidden') for item in meta):
            self.preview_zoomable_canvas.clear()
            self.state_manager.get_state().thumbnail_layout_data = []
            self.status_lbl.configure(text='All thumbnails are hidden. Show hidden frames to edit them.')
            return
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
            frame_info_timecode_or_frame=self.frame_info_timecode_or_frame_var.get(),
            frame_info_font_color=self.frame_info_font_color_var.get(),
            frame_info_bg_color=self.frame_info_bg_color_var.get(),
            frame_info_position=self.frame_info_position_var.get(),
            frame_info_size=int(self.frame_info_size_var.get()),
            frame_info_margin=int(self.frame_info_margin_var.get()),
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
                self._refresh_selected_inspector()
                meta = self.state_manager.get_state().thumbnail_metadata[source_index]
                video_path = meta.get('video_path') or self._source_video_path()
                self.scrubbing_handler.start(event, source_index, meta.get('timestamp_sec', 0.0), video_path)
                return True
        return False
    def handle_scrubbing(self, event): self.scrubbing_handler.handle_motion(event)
    def stop_scrubbing(self, event): self.scrubbing_handler.stop(event)
    def update_thumbnail_in_preview(self, index, new_thumb_img, new_timestamp, frame_number=None):
        try:
            item = self.state_manager.get_state().thumbnail_metadata[index]
            frame_path = item.get('frame_path')
            if frame_path:
                new_path = os.path.join(os.path.dirname(frame_path), f"scrub_{time.time_ns()}.jpg")
                new_thumb_img.convert('RGB').save(new_path, quality=92)
                item['frame_path'] = new_path
            item['timestamp_sec'] = new_timestamp
            if frame_number is not None:
                item['frame_number'] = frame_number
        except (IndexError, OSError) as error:
            logging.getLogger(__name__).warning('Could not update scrubbed thumbnail: %s', error)
            return
        self._refresh_selected_inspector()
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
        settings.output_dir = self.output_dir_var.get().strip() or None
        settings.save_alongside_video = not bool(settings.output_dir)
        settings.include_individual_frames = self.include_individual_frames_var.get()
        
        try:
            settings.layout_mode = self.layout_mode_var.get()
            settings.timeline_minutes_per_row = float(self.timeline_minutes_per_row_var.get() or 0)
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
            settings.manual_thumbnail_metadata = None

            if settings.layout_mode == "grid":
                settings.rows = rows
                settings.columns = cols
                settings.max_frames_for_print = rows * cols
                settings.target_row_height = None
                settings.interval_seconds = None
            else:
                settings.rows = None
                settings.columns = None
                settings.max_frames_for_print = None
                settings.target_row_height = int(self.target_row_height_var.get() or 150)
                settings.interval_seconds = None

            if active_tab == "Single Source":
                current_meta = self._metadata_in_display_order()
                if (self._preview_metadata_matches_single_source(final_input_list, self.state_manager.get_state().thumbnail_metadata)
                        and not current_meta):
                    raise ValueError("All thumbnails are hidden. Show at least one frame before exporting.")
                if self._preview_metadata_matches_single_source(final_input_list, current_meta):
                    settings.manual_timestamps = [
                        float(item.get('timestamp_sec') or 0.0) for item in current_meta
                    ]
                    settings.manual_thumbnail_metadata = self._snapshot_render_metadata(current_meta)

            settings.padding = int(self.padding_var.get())
            settings.background_color = self.background_color_var.get()
            settings.frame_format = self.frame_format_var.get()
            settings.save_metadata_json = False 
            active_sheet = self.state_manager.get_state().active_sheet()
            settings.sheet_name = active_sheet.name
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
            settings.show_header_timeline = self.show_header_timeline_var.get()
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
        
        self._job_thread = threading.Thread(
            target=self.run_generation_in_thread, 
            args=(settings, self._gui_progress_callback),
            daemon=True
        )
        self._job_thread.start()

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

    @staticmethod
    def _preview_metadata_matches_single_source(input_paths, metadata):
        """Only reuse preview edits for the exact file that produced the preview."""
        if len(input_paths) != 1 or not metadata:
            return False

        input_path = os.path.abspath(input_paths[0])
        if not os.path.isfile(input_path):
            return False

        preview_paths = {
            os.path.normcase(os.path.abspath(item['video_path']))
            for item in metadata
            if item.get('video_path')
        }
        return preview_paths == {os.path.normcase(input_path)}

    def run_generation_in_thread(self, settings, progress_cb):
        thread_logger = logging.getLogger(f"gui_thread_{threading.get_ident()}")
        thread_logger.setLevel(logging.INFO)
        queue_handler = QueueHandler(self.queue)
        thread_logger.addHandler(queue_handler)
        try:
            successful_ops, failed_ops = DependencyManager.movieprint_maker(
                settings, thread_logger, progress_cb, fast_preview=False
            )
        except Exception as e:
            thread_logger.exception(f"Error: {e}")
            successful_ops = []
            failed_ops = [{"reason": str(e)}]
        finally:
            thread_logger.removeHandler(queue_handler)
            self.queue.put(("generation_done", {
                "successful_ops": successful_ops,
                "failed_ops": failed_ops,
                "cancelled": bool(getattr(settings, "cancelled", False)),
                "skipped_count": getattr(settings, 'skipped_count', 0),
            }))
            self.queue.put(("busy", False))

    def _gui_progress_callback(self, current, total, filename):
        self.queue.put(("progress", (current, total, filename)))

    # --- HELPERS ---
    def _set_single_source_paths(self, paths):
        """Update the text-bound source entry without clearing its StringVar."""
        self._internal_input_paths = [str(path) for path in paths if path]
        self.input_paths_var.set("; ".join(self._internal_input_paths))

    def browse_input_paths(self):
        if self.is_busy:
            return
        filepaths = filedialog.askopenfilenames(title="Add video to preview",
            filetypes=[('Video files', '*.mp4 *.avi *.mov *.mkv *.flv *.wmv'), ('All files', '*.*')])
        if filepaths:
            self._add_preview_paths(filepaths)

    def _add_preview_paths(self, paths):
        """Picker/drop actions preview immediately; typed paths wait for Enter."""
        if self.is_busy or not paths:
            return
        if self.state_manager.get_state().thumbnail_metadata:
            if not messagebox.askyesno('Replace preview?',
                    'Build a new preview in this sheet? This replaces its current frame edits. '
                    'You can Undo afterwards, or choose No and add a new sheet first.',
                    default='no'):
                return
        self.input_tabs.set('Single Source')
        self._on_tab_change()
        self._set_single_source_paths(paths)
        if len(paths) > 1:
            messagebox.showinfo('Multiple videos selected',
                'The first video will be previewed. Export will process all selected videos. '
                'Use Batch Queue to manage the list individually.')
        self.start_thumbnail_preview_generation()

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
        if self.is_busy:
            return
        paths = self.tk.splitlist(event.data)
        if not paths: return
        active_tab = self.input_tabs.get()
        if active_tab == "Batch Queue":
            self._add_batch_paths(paths)
        else:
            self._add_preview_paths(paths)

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

    def browse_movieprint_output_dir(self):
        selected = filedialog.askdirectory(title='Movieprint output folder')
        if selected:
            self.output_dir_var.set(selected)

    def _sync_output_destination(self):
        if not hasattr(self, 'save_next_to_video_var'):
            return
        alongside = not self.output_dir_var.get().strip()
        self.save_next_to_video_var.set(alongside)
        self.output_destination_hint.configure(text=(
            'Each movieprint will be saved in its source video’s folder.' if alongside else
            'Movieprints will be saved in the folder chosen above.'))

    def _toggle_save_next_to_video(self):
        if self.is_busy:
            self._sync_output_destination()
            return
        if self.save_next_to_video_var.get():
            self.output_dir_var.set('')
        else:
            self.browse_movieprint_output_dir()
        # Cancelling the folder picker keeps the actual destination selected.
        self._sync_output_destination()
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
            self.slider_frame.pack(fill="x", padx=10, pady=10, after=self.live_math_frame)
            self.row_height_frame.pack_forget()
        else:
            self.slider_frame.pack_forget()
            self.row_height_frame.pack(fill="x", pady=5, after=self.layout_mode_seg)
        if extraction == "shot": self.shot_threshold_frame.pack(fill="x", pady=5, after=self.layout_mode_seg)
        else: self.shot_threshold_frame.pack_forget()
        self._update_live_math()

    def _cleanup_garbage_dirs(self):
        # Sheets and Undo retain frame paths. Reclaim only when the workspace closes.
        if not getattr(self, '_closing', False):
            return
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
        except Exception as error:
            logging.getLogger(__name__).warning(
                "Could not load saved GUI settings; using defaults: %s", error
            )
        finally:
            self._loading_persistent_settings = False

    def _on_closing(self):
        self._closing = True
        if self.active_cancel_event:
            self.active_cancel_event.set()
        self.scrubbing_handler._stop_event.set()
        self._finish_closing_when_idle()

    def _finish_closing_when_idle(self):
        workers = [getattr(self, '_job_thread', None), self.scrubbing_handler._worker_thread]
        if any(worker and worker.is_alive() for worker in workers):
            self.status_lbl.configure(text='Cancelling work before closing…')
            self.after(100, self._finish_closing_when_idle)
            return
        if self.player_window and self.player_window.winfo_exists():
            self.player_window.close()
        settings = {}
        for var_name, key in self.settings_map.items():
            if hasattr(self, var_name): settings[key] = getattr(self, var_name).get()
        try:
            with open(SETTINGS_FILE, 'w') as f: json.dump(settings, f, indent=4)
        except (OSError, TypeError) as error:
            logging.getLogger(__name__).warning("Could not save GUI settings: %s", error)
        if self.preview_temp_dir and os.path.exists(self.preview_temp_dir): self.temp_dirs_to_cleanup.append(self.preview_temp_dir)
        self._cleanup_garbage_dirs()
        self.destroy()

if __name__ == "__main__":
    setup_file_logging()
    app = MoviePrintApp()
    app.mainloop()
