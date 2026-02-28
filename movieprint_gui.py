import customtkinter as ctk
import tkinter as tk
import logging
from logging.handlers import RotatingFileHandler
from tkinter import ttk, filedialog, messagebox, colorchooser
import os
import sys
import shutil
import tempfile
import argparse
import threading
import queue
import time
import json
import numpy as np
from typing import Optional, List, Dict, Any, Tuple, Union
from PIL import ImageTk, Image, ImageDraw, ImageChops, ImageOps

# --- DEPENDENCY MANAGEMENT ---
class DependencyManager:
    MISSING_LIBS: List[str] = []
    video_processing = None
    state_manager_cls = None
    movieprint_maker = None
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
            except ImportError as e:
                if name != "version":
                    cls.MISSING_LIBS.append(f"{name}.py ({e})")

        if cls.state_manager:
            cls.state_manager_cls = cls.state_manager.StateManager
        if cls.movieprint_maker:
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
    BG_PRIMARY = "#121212"
    BG_SECONDARY = "#1E1E1E"
    ACCENT_CYAN = "#008B8B"
    ACCENT_GLOW = "#00FFFF"
    TEXT_MAIN = "#FFFFFF"
    TEXT_MUTED = "#888888"
    BUTTON_HOVER = "#00CED1"
    FONT_HEADER = ("Impact", 60)
    FONT_SUB = ("Roboto", 16)
    FONT_BOLD = ("Roboto", 12, "bold")

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
        scale_factor = 1.1
        if (event.num == 5 or event.delta < 0):
            self.canvas.scale("all", event.x, event.y, 1/scale_factor, 1/scale_factor)
        elif (event.num == 4 or event.delta > 0):
            self.canvas.scale("all", event.x, event.y, scale_factor, scale_factor)
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

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

class CTkCollapsibleFrame(ctk.CTkFrame):
    def __init__(self, master, title="", **kwargs):
        super().__init__(master, **kwargs)
        self.grid_columnconfigure(0, weight=1)
        self.variable = ctk.BooleanVar(value=True)
        self.title_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.title_frame.grid(row=0, column=0, sticky="ew")
        self.title_frame.grid_columnconfigure(1, weight=1)
        self.toggle_button = ctk.CTkButton(
            self.title_frame, text=f"- {title}", command=self.toggle, width=30,
            fg_color="transparent", text_color=Theme.ACCENT_CYAN, hover=False, anchor="w", font=Theme.FONT_BOLD
        )
        self.toggle_button.grid(row=0, column=0, sticky="w")
        self.sub_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.sub_frame.grid(row=1, column=0, sticky="nsew", padx=10, pady=5)

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
        self.configure(fg_color=Theme.BG_PRIMARY)
        
        self._init_dnd()
        self.scrubbing_handler = ScrubbingHandler(self)
        self.temp_dirs_to_cleanup: List[str] = []
        self._internal_input_paths: List[str] = []
        self.batch_file_list: List[str] = [] 
        self.queue = queue.Queue()
        self.preview_temp_dir: Optional[str] = None
        self.is_landing_state = True
        
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
        self.toolbar_frame = ctk.CTkFrame(self, height=30, fg_color=Theme.BG_PRIMARY)
        self.toolbar_frame.grid(row=1, column=1, sticky="ew", padx=10)
        ctk.CTkLabel(self.toolbar_frame, text="Zoom:", text_color=Theme.TEXT_MUTED).pack(side="left", padx=5)
        self.zoom_slider = ctk.CTkSlider(self.toolbar_frame, from_=0.1, to=5.0, variable=self.zoom_level_var, 
                                        command=self.preview_zoomable_canvas.set_zoom, width=150, progress_color=Theme.ACCENT_CYAN)
        self.zoom_slider.pack(side="left", padx=5)

    def _build_action_footer(self):
        self.action_frame = ctk.CTkFrame(self, height=60, fg_color=Theme.BG_SECONDARY)
        self.action_frame.grid(row=2, column=0, columnspan=2, sticky="ew")
        self.action_frame.grid_columnconfigure(0, weight=1)
        
        self.status_lbl = ctk.CTkLabel(self.action_frame, text="Ready", text_color=Theme.TEXT_MUTED)
        self.status_lbl.grid(row=0, column=0, sticky="w", padx=20)
        
        self.progress_bar = ctk.CTkProgressBar(self.action_frame, width=300, progress_color=Theme.ACCENT_CYAN)
        self.progress_bar.set(0)
        self.progress_bar.grid(row=0, column=1, padx=20)
        
        btn_frame = ctk.CTkFrame(self.action_frame, fg_color="transparent")
        btn_frame.grid(row=0, column=2, sticky="e", padx=20, pady=10)
        
        self.preview_btn = ctk.CTkButton(btn_frame, text="PREVIEW", command=self.start_thumbnail_preview_generation,
                      fg_color="transparent", border_width=1, border_color=Theme.ACCENT_CYAN,
                      text_color=Theme.ACCENT_CYAN)
        self.preview_btn.pack(side="left", padx=5)
        
        ctk.CTkButton(btn_frame, text="APPLY / SAVE", command=self.generate_movieprint_action,
                      fg_color=Theme.ACCENT_CYAN, text_color=Theme.BG_PRIMARY,
                      hover_color=Theme.BUTTON_HOVER, font=Theme.FONT_BOLD, width=150).pack(side="left", padx=5)

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
        steps = [("1", "Drag & Drop", "Video files"), ("2", "Customize", "Layout & Style"), ("3", "Save", "Export Image")]
        
        for i, (num, title, desc) in enumerate(steps):
            f = ctk.CTkFrame(workflow_frame, fg_color="transparent")
            f.grid(row=0, column=i, padx=40)
            ctk.CTkLabel(f, text=num, font=("Roboto", 40, "bold"), text_color=Theme.ACCENT_CYAN).pack()
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
        
        # Colors (Hardcoded to match Theme context without relying on missing attrs)
        color_frame = "#252525"  # Dark Grey (Frame placeholder)
        color_tc = "#333333"     # Darker Grey (Timecode placeholder)
        color_highlight = Theme.ACCENT_CYAN # Use the existing Cyan accent
        
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
        self.live_math_frame = ctk.CTkFrame(parent, fg_color="transparent")
        self.live_math_frame.pack(fill="x", padx=10, pady=20)
        font_lg = ("Roboto", 32, "bold")
        
        self.math_lbl_cols = ctk.CTkLabel(self.live_math_frame, text="5", font=font_lg, text_color="white")
        self.math_lbl_cols.pack(side="left", expand=True)
        ctk.CTkLabel(self.live_math_frame, text="×", font=("Roboto", 24), text_color=Theme.TEXT_MUTED).pack(side="left")
        self.math_lbl_rows = ctk.CTkLabel(self.live_math_frame, text="?", font=font_lg, text_color="white")
        self.math_lbl_rows.pack(side="left", expand=True)
        ctk.CTkLabel(self.live_math_frame, text="=", font=("Roboto", 24), text_color=Theme.TEXT_MUTED).pack(side="left")
        self.math_lbl_res = ctk.CTkLabel(self.live_math_frame, text="?", font=font_lg, text_color=Theme.ACCENT_CYAN)
        self.math_lbl_res.pack(side="left", expand=True)

        self.input_tabs = ctk.CTkTabview(parent, fg_color="transparent", text_color=Theme.TEXT_MAIN, 
                                         segmented_button_selected_color=Theme.ACCENT_CYAN,
                                         segmented_button_selected_hover_color=Theme.BUTTON_HOVER,
                                         command=self._on_tab_change)
        self.input_tabs.pack(fill="x", padx=10, pady=(0, 5))
        self.input_tabs.add("Single Source")
        self.input_tabs.add("Batch Queue")
        
        single_tab = self.input_tabs.tab("Single Source")
        self.input_entry = ctk.CTkEntry(single_tab, textvariable=self.input_paths_var, placeholder_text="Drag file here...", border_color=Theme.ACCENT_CYAN)
        self.input_entry.pack(fill="x", padx=0, pady=(10,5))
        if self.dnd_active:
            try:
                self.input_entry.drop_target_register(DND_FILES)
                self.input_entry.dnd_bind('<<Drop>>', self.handle_drop)
            except Exception: pass
        ctk.CTkButton(single_tab, text="Browse", command=self.browse_input_paths, fg_color=Theme.ACCENT_CYAN, 
                      text_color=Theme.BG_PRIMARY, hover_color=Theme.BUTTON_HOVER).pack(fill="x", padx=0, pady=10)

        batch_tab = self.input_tabs.tab("Batch Queue")
        list_container = ctk.CTkFrame(batch_tab, fg_color="#2B2B2B", height=150)
        list_container.pack(fill="x", padx=0, pady=(10,5))
        list_container.pack_propagate(False)
        self.batch_listbox = tk.Listbox(list_container, bg="#2B2B2B", fg="white", borderwidth=0, highlightthickness=0, selectmode="extended")
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
        ctk.CTkButton(batch_ctrl_frame, text="Clear", command=self.clear_batch_list, width=60, fg_color="#333333", hover_color="#555555").pack(side="left", padx=(0,5))
        ctk.CTkButton(batch_ctrl_frame, text="Remove Selected", command=self.remove_batch_item, width=100, fg_color="#333333", hover_color="#555555").pack(side="left")
        
        # --- NEW: Recursive Checkbox ---
        ctk.CTkCheckBox(parent, text="Recursive Folder Scan", variable=self.recursive_scan_var, 
                        text_color=Theme.TEXT_MUTED).pack(fill="x", padx=15, pady=(0, 10))

        self._create_cyber_slider_section(parent)
        
        # --- NEW: Output Dimensions Section ---
        dims_frame = CTkCollapsibleFrame(parent, title="Output Dimensions")
        dims_frame.pack(fill="x", padx=10, pady=5)
        self._populate_dimensions_settings(dims_frame.get_content_frame())

        adv_frame = CTkCollapsibleFrame(parent, title="Advanced Settings")
        adv_frame.pack(fill="x", padx=10, pady=5)
        self._populate_advanced_settings(adv_frame.get_content_frame())

        hdr_frame = CTkCollapsibleFrame(parent, title="HDR & Color")
        hdr_frame.pack(fill="x", padx=10, pady=5)
        self._populate_hdr_settings(hdr_frame.get_content_frame())

    def _create_cyber_slider_section(self, parent):
        self.slider_frame = ctk.CTkFrame(parent, fg_color="transparent")
        self.slider_frame.pack(fill="x", padx=10, pady=10)
        
        ctk.CTkLabel(self.slider_frame, text="COLUMNS", font=Theme.FONT_BOLD, text_color=Theme.TEXT_MAIN).pack(anchor="w")
        self.col_slider = ctk.CTkSlider(self.slider_frame, from_=1, to=20, number_of_steps=19, variable=None, 
                                       command=self._on_col_slider_change, progress_color=Theme.ACCENT_CYAN, 
                                       button_color=Theme.ACCENT_GLOW, button_hover_color="white")
        self.col_slider.set(5)
        self.col_slider.pack(fill="x", pady=(0, 15))
        
        ctk.CTkLabel(self.slider_frame, text="ROWS", font=Theme.FONT_BOLD, text_color=Theme.TEXT_MAIN).pack(anchor="w")
        self.row_slider = ctk.CTkSlider(self.slider_frame, from_=1, to=20, number_of_steps=19, variable=None, 
                                       command=self._on_row_slider_change, progress_color=Theme.ACCENT_CYAN, 
                                       button_color=Theme.ACCENT_GLOW, button_hover_color="white")
        self.row_slider.set(5)
        self.row_slider.pack(fill="x", pady=(0, 15))

    def _populate_dimensions_settings(self, parent):
        # Fit Toggle
        self.fit_switch = ctk.CTkSwitch(parent, text="Force Fit to Resolution", variable=self.fit_to_output_params_var, 
                                        progress_color=Theme.ACCENT_CYAN, command=self.quick_refresh_layout)
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

        ctk.CTkLabel(parent, text="ℹ Thumbnails will crop to fit exactly.", font=("Roboto", 10), text_color=Theme.TEXT_MUTED).pack(anchor="w", pady=(5,0))

    def _populate_advanced_settings(self, parent):
        ctk.CTkLabel(parent, text="Extraction Mode:").pack(anchor="w", pady=(5, 0))
        self.extraction_mode_seg = ctk.CTkSegmentedButton(parent, values=["interval", "shot"], variable=self.extraction_mode_var, 
                                                          selected_color=Theme.ACCENT_CYAN, selected_hover_color=Theme.BUTTON_HOVER, 
                                                          command=self._on_extraction_mode_change)
        self.extraction_mode_seg.pack(fill="x", pady=(0, 5))
        
        ctk.CTkLabel(parent, text="Layout Mode:").pack(anchor="w", pady=(5, 0))
        self.layout_mode_seg = ctk.CTkSegmentedButton(parent, values=["grid", "timeline"], variable=self.layout_mode_var, 
                                                      selected_color=Theme.ACCENT_CYAN, selected_hover_color=Theme.BUTTON_HOVER, 
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
            variable=self.output_naming_mode_var,
            command=self._toggle_naming_inputs,
            selected_color=Theme.ACCENT_CYAN, 
            selected_hover_color=Theme.BUTTON_HOVER
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
        ctk.CTkLabel(parent, text="ℹ Files will be saved alongside source videos.", font=Theme.FONT_BOLD).pack(anchor="w", pady=(0, 5))

        # --- NEW: Overwrite Switch ---
        ctk.CTkLabel(parent, text="Existing Files:").pack(anchor="w", pady=(5,0))
        self.overwrite_seg = ctk.CTkSegmentedButton(parent, values=["overwrite", "skip"], variable=self.overwrite_mode_var,
                                                   selected_color=Theme.ACCENT_CYAN, selected_hover_color=Theme.BUTTON_HOVER)
        self.overwrite_seg.pack(fill="x", pady=5)


        ctk.CTkSwitch(parent, text="Show Frame Info/Timecode", variable=self.frame_info_show_var, progress_color=Theme.ACCENT_CYAN, command=self.quick_refresh_layout).pack(anchor="w", pady=5)
        ctk.CTkCheckBox(parent, text="Detect Faces", variable=self.detect_faces_var, fg_color=Theme.ACCENT_CYAN, hover_color=Theme.BUTTON_HOVER).pack(anchor="w", pady=2)
        ctk.CTkCheckBox(parent, text="Use GPU (FFmpeg)", variable=self.use_gpu_var, fg_color=Theme.ACCENT_CYAN, hover_color=Theme.BUTTON_HOVER).pack(anchor="w", pady=2)
        ctk.CTkCheckBox(parent, text="Show Header (Filename)", variable=self.show_header_var, fg_color=Theme.ACCENT_CYAN, hover_color=Theme.BUTTON_HOVER, command=self.quick_refresh_layout).pack(anchor="w", pady=2)
        ctk.CTkCheckBox(parent, text="Show Timecode", variable=self.show_timecode_var, fg_color=Theme.ACCENT_CYAN, hover_color=Theme.BUTTON_HOVER, command=self.quick_refresh_layout).pack(anchor="w", pady=2)
        
        ctk.CTkLabel(parent, text="Rotate Thumbnails:").pack(anchor="w", pady=(10, 0))
        self.rotate_seg = ctk.CTkSegmentedButton(parent, values=["0", "90", "180", "270"], variable=self.rotate_thumbnails_var, 
                                                 selected_color=Theme.ACCENT_CYAN, selected_hover_color=Theme.BUTTON_HOVER, 
                                                 command=self.quick_refresh_layout)
        self.rotate_seg.pack(fill="x", pady=5)
        
        ctk.CTkLabel(parent, text="Corner Roundness:").pack(anchor="w", pady=(10,0))
        ctk.CTkSlider(parent, from_=0, to=100, variable=self.rounded_corners_var, progress_color=Theme.ACCENT_CYAN, command=self.quick_refresh_layout).pack(fill="x", pady=5)
        
        ctk.CTkLabel(parent, text="Padding:").pack(anchor="w", pady=(10, 0))
        pad_entry = ctk.CTkEntry(parent, textvariable=self.padding_var)
        pad_entry.pack(fill="x", pady=5)
        pad_entry.bind("<Return>", lambda e: self.quick_refresh_layout()) 

        ctk.CTkLabel(parent, text="Background Color:").pack(anchor="w", pady=(10,0))
        ctk.CTkEntry(parent, textvariable=self.background_color_var).pack(fill="x", pady=5)
        ctk.CTkButton(parent, text="Pick Color", command=lambda: [self.pick_bg_color(), self.quick_refresh_layout()], 
                      width=80, fg_color=Theme.BG_SECONDARY).pack(anchor="w")

        ctk.CTkLabel(parent, text="Output Format:").pack(anchor="w", pady=(10, 0))
        self.format_seg = ctk.CTkSegmentedButton(parent, values=["jpg", "png"], variable=self.frame_format_var, 
                                                 selected_color=Theme.ACCENT_CYAN, selected_hover_color=Theme.BUTTON_HOVER)
        self.format_seg.pack(fill="x", pady=5)
        
        ctk.CTkLabel(parent, text="Preview Quality (Fast):").pack(anchor="w", pady=(10,0))
        ctk.CTkSlider(parent, from_=10, to=100, variable=self.preview_quality_var).pack(fill="x")
        ctk.CTkLabel(parent, text="Output Quality (JPG):").pack(anchor="w", pady=(10,0))
        ctk.CTkSlider(parent, from_=10, to=100, variable=self.output_quality_var, progress_color=Theme.ACCENT_CYAN).pack(fill="x")
        
        self.update_visibility_state()

    def _populate_hdr_settings(self, parent):
        ctk.CTkLabel(parent, text="HDR to SDR Tone Mapping", font=Theme.FONT_BOLD).pack(anchor="w", pady=(5,0))
        ctk.CTkLabel(parent, text="Converts washed-out HDR colors to normal SDR.", font=("Roboto", 10), text_color=Theme.TEXT_MUTED).pack(anchor="w", pady=(0,5))
        self.hdr_switch = ctk.CTkSwitch(parent, text="Enable Tone Mapping", variable=self.hdr_tonemap_var, progress_color=Theme.ACCENT_CYAN, command=self._toggle_hdr_options)
        self.hdr_switch.pack(anchor="w", pady=5)
        self.hdr_algo_frame = ctk.CTkFrame(parent, fg_color="transparent")
        self.hdr_algo_frame.pack(fill="x", padx=20)
        ctk.CTkLabel(self.hdr_algo_frame, text="Algorithm:").pack(side="left")
        self.hdr_algo_combo = ctk.CTkComboBox(self.hdr_algo_frame, values=["hable", "reinhard", "mobius"], variable=self.hdr_algorithm_var, border_color=Theme.ACCENT_CYAN, button_color=Theme.ACCENT_CYAN)
        self.hdr_algo_combo.pack(side="left", padx=10)
        self._toggle_hdr_options()

    def _toggle_hdr_options(self):
        if self.hdr_tonemap_var.get():
            self.hdr_algo_frame.pack(fill="x", padx=20, pady=5)
        else:
            self.hdr_algo_frame.pack_forget()

    def _toggle_naming_inputs(self, mode=None):
        if mode is None: mode = self.output_naming_mode_var.get()
        self.lbl_suffix.pack_forget()
        self.entry_suffix.pack_forget()
        self.lbl_custom.pack_forget()
        self.entry_custom.pack_forget()
        if mode == "Fixed Name":
            self.lbl_custom.pack(anchor="w", pady=(2,0))
            self.entry_custom.pack(fill="x", pady=(0,5))
            self.output_naming_mode_var.set("custom")
        else:
            self.lbl_suffix.pack(anchor="w", pady=(2,0))
            self.entry_suffix.pack(fill="x", pady=(0,5))
            self.output_naming_mode_var.set("suffix")

    # --- LOGIC ---
    def _on_tab_change(self):
        active = self.input_tabs.get()
        if active == "Batch Queue":
            self.preview_btn.configure(state="disabled", text_color="gray")
            self.input_entry.configure(state="disabled", fg_color="gray")
        else:
            self.preview_btn.configure(state="normal", text_color=Theme.ACCENT_CYAN)
            self.input_entry.configure(state="normal", fg_color="#343638")

    def _bind_settings_to_state(self):
        for var_name, setting_key in self.settings_map.items():
            if hasattr(self, var_name):
                var = getattr(self, var_name)
                var.trace_add("write", lambda *args, v=var_name, s=setting_key: self._on_setting_change(v, s))

    def _on_setting_change(self, var_name, setting_key):
        try:
            var = getattr(self, var_name)
            val = var.get()
            self.state_manager.update_settings({setting_key: val}, commit=False)
        except Exception: pass

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
            if hasattr(self, 'rotate_seg'): self.rotate_seg.set(str(self.rotate_thumbnails_var.get()))
            if hasattr(self, 'format_seg'): self.format_seg.set(self.frame_format_var.get())
            if hasattr(self, 'overwrite_seg'): self.overwrite_seg.set(self.overwrite_mode_var.get())
        except AttributeError: pass
        self.update_visibility_state()
        self._toggle_naming_inputs()
        self._toggle_hdr_options()
        if state.thumbnail_metadata and self.preview_temp_dir:
            self._restore_grid_visuals(state, settings)
        self._update_live_math()

    def _restore_grid_visuals(self, state, settings):
        image_paths = [item.get('frame_path') for item in state.thumbnail_metadata]
        grid_path = os.path.join(self.preview_temp_dir, "preview_restored.jpg")
        
        grid_params = {
            'image_source_data': image_paths,
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
            'frame_info_show': settings.frame_info_show,
            'layout_mode': settings.layout_mode,
            'target_row_height': settings.target_row_height,
            # NEW PARAMS
            'fit_to_output_params': settings.fit_to_output_params,
            'output_width': settings.output_width,
            'output_height': settings.output_height,
        }

        if settings.layout_mode == "timeline":
             enriched_data = []
             for item in state.thumbnail_metadata:
                 enriched_data.append({
                     'image_path': item['frame_path'],
                     'width_ratio': item.get('duration_frames', 1.0)
                 })
             grid_params['image_source_data'] = enriched_data

        success, layout = DependencyManager.image_grid.create_image_grid(**grid_params)
        
        self.state_manager.get_state().thumbnail_layout_data = layout
        if success:
            self.preview_zoomable_canvas.set_image(grid_path)

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
                elif msg_type == "update_thumbnail":
                    self.update_thumbnail_in_preview(data['index'], data['image'], data['timestamp'])
                self.update_idletasks()
        except queue.Empty: pass
        self.after(100, self._start_queue_poller)

    def start_thumbnail_preview_generation(self):
        if self.input_tabs.get() == "Batch Queue":
            messagebox.showinfo("Mode Info", "Switch to 'Single Source' tab to preview tweaks.")
            return

        if not self._internal_input_paths: return
        
        # --- NEW: Check if input is directory and resolve to first video ---
        preview_target_path = self._internal_input_paths[0]
        if os.path.isdir(preview_target_path):
            self.status_lbl.configure(text="Scanning directory for preview...")
            # Use maker's discovery logic to find first valid video
            valid_exts = ".mp4,.avi,.mov,.mkv,.flv,.wmv"
            # We don't recurse for preview scan to save time, just check root
            videos = DependencyManager.movieprint_maker.discover_video_files([preview_target_path], valid_exts, False, logging.getLogger("preview_scan"))
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
            'rounded': int(self.rounded_corners_var.get()),
            'show_header': self.show_header_var.get(),
            'target_row_height': int(self.target_row_height_var.get() or 150),
            'frame_info_show': self.frame_info_show_var.get(),
            'hdr_tonemap': self.hdr_tonemap_var.get(),
            'hdr_algorithm': self.hdr_algorithm_var.get(),
            'fit_to_output_params': self.fit_to_output_params_var.get(),
            'output_width': int(self.output_width_var.get()),
            'output_height': int(self.output_height_var.get())
        }

        self.status_lbl.configure(text="Generating Preview...")
        self.progress_bar.configure(mode="indeterminate")
        self.progress_bar.start()
        
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
            
            if success and meta:
                self._process_preview_thumbnails(meta, config, logger)

                self.queue.put(("log", f"Generating {config['layout_mode']} layout..."))
                grid_path = os.path.join(temp_dir, "preview_initial.jpg")
                
                if config['layout_mode'] == 'timeline':
                    image_source_data = [{'image_path': m['frame_path'], 'width_ratio': m.get('duration_frames', 1.0)} for m in meta]
                else:
                    image_source_data = [m['frame_path'] for m in meta]

                grid_success, layout = DependencyManager.image_grid.create_image_grid(
                    image_source_data=image_source_data,
                    output_path=grid_path,
                    layout_mode=config['layout_mode'],
                    columns=config['cols'],
                    rows=config['rows'],
                    target_row_height=config['target_row_height'],
                    background_color_hex=config['bg_color'],
                    padding=config['padding'],
                    logger=logger,
                    rounded_corners=config['rounded'], 
                    rotation=config['rotate_thumbnails'],
                    frame_info_show=config['frame_info_show'],
                    fit_to_output_params=config['fit_to_output_params'],
                    output_width=config['output_width'],
                    output_height=config['output_height']
                )
                
                if grid_success:
                    self.queue.put(("preview_done", {
                        "grid_path": grid_path, "meta": meta,
                        "layout": layout, "temp_dir": temp_dir
                    }))
            else: self.queue.put(("log", "Failed to extract frames."))
        except Exception as e:
            self.queue.put(("log", f"Error: {e}"))
            import traceback
            traceback.print_exc()
        finally:
            self.queue.put(("progress", (0, 0, "")))

    def _process_preview_thumbnails(self, meta_list, config, logger):
        cv2 = DependencyManager.video_processing.cv2
        if config['rotate_thumbnails'] != 0:
            self.queue.put(("log", "Rotating thumbnails..."))
            rot_flag = {90: cv2.ROTATE_90_CLOCKWISE, 180: cv2.ROTATE_180, 270: cv2.ROTATE_90_COUNTERCLOCKWISE}.get(config['rotate_thumbnails'])
            if rot_flag is not None:
                for item in meta_list:
                    try:
                        img = cv2.imread(item['frame_path'])
                        if img is not None:
                            img = cv2.rotate(img, rot_flag)
                            cv2.imwrite(item['frame_path'], img)
                    except: pass
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
        self.state_manager.get_state().thumbnail_metadata = data.get("meta")
        self.state_manager.get_state().thumbnail_layout_data = data.get("layout")
        
        if self.is_landing_state:
            self.landing_frame.grid_remove()
            self.preview_zoomable_canvas.grid(row=0, column=0, sticky="nsew")
            self.is_landing_state = False
            
        if data.get("grid_path"):
            self.preview_zoomable_canvas.set_image(data.get("grid_path"))
            
        self.progress_bar.stop()
        self._update_live_math()
        self.state_manager.snapshot()

    def quick_refresh_layout(self, value=None):
        if not self.state_manager.get_state().thumbnail_metadata or not self.preview_temp_dir:
            return
        meta = self.state_manager.get_state().thumbnail_metadata
        layout_mode = self.layout_mode_var.get()
        if layout_mode == 'timeline':
             image_source_data = [{'image_path': m['frame_path'], 'width_ratio': m.get('duration_frames', 1.0)} for m in meta]
        else:
             image_source_data = [m['frame_path'] for m in meta]
        grid_path = os.path.join(self.preview_temp_dir, "preview_refresh.jpg")
        success, layout = DependencyManager.image_grid.create_image_grid(
            image_source_data=image_source_data,
            output_path=grid_path,
            layout_mode=layout_mode,
            columns=int(self.num_columns_var.get()),
            rows=int(self.num_rows_var.get()),
            target_row_height=int(self.target_row_height_var.get() or 150),
            background_color_hex=self.background_color_var.get(),
            padding=int(self.padding_var.get()),
            logger=logging.getLogger("refresh"),
            rounded_corners=int(self.rounded_corners_var.get()),
            rotation=int(self.rotate_thumbnails_var.get()),
            frame_info_show=self.frame_info_show_var.get(),
            fit_to_output_params=self.fit_to_output_params_var.get(),
            output_width=int(self.output_width_var.get()),
            output_height=int(self.output_height_var.get())
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
        canvas = self.preview_zoomable_canvas.canvas
        canvas_x = canvas.canvasx(event.x)
        canvas_y = canvas.canvasy(event.y)
        for i, thumb_info in enumerate(layout):
            if thumb_info['x'] <= canvas_x <= thumb_info['x'] + thumb_info['width'] and \
               thumb_info['y'] <= canvas_y <= thumb_info['y'] + thumb_info['height']:
                self.state_manager.snapshot()
                meta = self.state_manager.get_state().thumbnail_metadata[i]
                video_path = self._internal_input_paths[0] if self._internal_input_paths else ""
                self.scrubbing_handler.start(event, i, meta.get('timestamp_sec', 0.0), video_path)
                return True
        return False
    def handle_scrubbing(self, event): self.scrubbing_handler.handle_motion(event)
    def stop_scrubbing(self, event): self.scrubbing_handler.stop(event)
    def update_thumbnail_in_preview(self, index, new_thumb_img, new_timestamp):
        try: self.state_manager.get_state().thumbnail_metadata[index]['timestamp_sec'] = new_timestamp
        except IndexError: pass
        canvas_handler = self.preview_zoomable_canvas
        layout = self.state_manager.get_state().thumbnail_layout_data
        if not canvas_handler.original_image or index >= len(layout): return
        try:
            thumb_info = layout[index]
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
                draw.rounded_rectangle([(0, 0), resized.size], radius=radius, fill=255)
                existing_alpha = resized.split()[3]
                final_alpha = ImageChops.multiply(existing_alpha, mask)
                resized.putalpha(final_alpha)
            canvas_handler.original_image.paste(resized, (thumb_info['x'], thumb_info['y']), mask=resized if radius > 0 else None)
            canvas_handler._apply_zoom()
        except Exception as e: print(f"Error updating thumbnail: {e}")

    # --- FINAL GENERATION ---
    def generate_movieprint_action(self):
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
            if not self._internal_input_paths:
                if input_paths_str: self._internal_input_paths = [p.strip() for p in input_paths_str.split(';') if p.strip()]
                else: 
                    messagebox.showerror("Input Error", "Please select video file(s).")
                    return
            final_input_list = self._internal_input_paths
        
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
            
            # --- NEW SETTINGS ---
            settings.recursive_scan = self.recursive_scan_var.get()
            settings.overwrite_mode = self.overwrite_mode_var.get()

            rows = int(self.num_rows_var.get())
            cols = int(self.num_columns_var.get())
            
            if settings.layout_mode == "grid":
                settings.rows = rows
                settings.columns = cols
                settings.max_frames_for_print = rows * cols
                settings.target_row_height = None
                settings.interval_seconds = None
                if active_tab == "Single Source":
                    current_meta = self.state_manager.get_state().thumbnail_metadata
                    if current_meta and len(current_meta) == (rows * cols):
                        settings.manual_timestamps = [m.get('timestamp_sec', 0.0) for m in current_meta]
                else:
                    settings.manual_timestamps = None
            else:
                settings.rows = None
                settings.columns = None
                settings.max_frames_for_print = None
                settings.target_row_height = int(self.target_row_height_var.get() or 150)
                settings.interval_seconds = None

            settings.padding = int(self.padding_var.get())
            settings.background_color = self.background_color_var.get()
            settings.frame_format = self.frame_format_var.get()
            settings.save_metadata_json = False 
            settings.start_time = None
            settings.end_time = None
            settings.exclude_frames = None
            settings.exclude_shots = None
            settings.output_naming_mode = self.output_naming_mode_var.get()
            settings.output_filename_suffix = self.output_filename_suffix_var.get()
            settings.output_filename = self.output_filename_var.get()
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
        
        self.status_lbl.configure(text="Generating...")
        self.progress_bar.configure(mode="determinate")
        
        threading.Thread(
            target=self.run_generation_in_thread, 
            args=(settings, self._gui_progress_callback),
            daemon=True
        ).start()

    def run_generation_in_thread(self, settings, progress_cb):
        thread_logger = logging.getLogger(f"gui_thread_{threading.get_ident()}")
        thread_logger.setLevel(logging.INFO)
        thread_logger.addHandler(QueueHandler(self.queue))
        try:
            DependencyManager.movieprint_maker(settings, thread_logger, progress_cb, fast_preview=False)
        except Exception as e:
            thread_logger.exception(f"Error: {e}")
        finally:
            self.queue.put(("log", "Done."))
            self.queue.put(("progress", (100, 100, "Done")))

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

    def handle_drop(self, event):
        paths = self.tk.splitlist(event.data)
        if not paths: return
        active_tab = self.input_tabs.get()
        if active_tab == "Batch Queue":
            for p in paths:
                if p not in self.batch_file_list:
                    self.batch_file_list.append(p)
                    self.batch_listbox.insert(tk.END, p)
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

    def browse_output_dir(self): pass
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
            with open(SETTINGS_FILE, 'r') as f:
                settings = json.load(f)
                self.input_paths_var.set(settings.get("input_paths", ""))
                if self.input_paths_var.get():
                     self._internal_input_paths = [p.strip() for p in self.input_paths_var.get().split(';') if p.strip()]
                for var_name, key in self.settings_map.items():
                    if key in settings and hasattr(self, var_name): getattr(self, var_name).set(settings[key])
                self.col_slider.set(int(self.num_columns_var.get() or 5))
                self.row_slider.set(int(self.num_rows_var.get() or 5))
                if hasattr(self, 'layout_mode_seg'): self.layout_mode_seg.set(self.layout_mode_var.get())
                if hasattr(self, 'extraction_mode_seg'): self.extraction_mode_seg.set(self.extraction_mode_var.get())
                if hasattr(self, 'rotate_seg'): self.rotate_seg.set(str(self.rotate_thumbnails_var.get()))
                if hasattr(self, 'format_seg'): self.format_seg.set(self.frame_format_var.get())
                if hasattr(self, 'overwrite_seg'): self.overwrite_seg.set(self.overwrite_mode_var.get())
                self.update_visibility_state()
                self._toggle_naming_inputs()
                self._toggle_hdr_options()
        except Exception: pass

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