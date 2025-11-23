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
from typing import Optional, List, Dict, Any, Tuple, Union
from PIL import ImageTk, Image

# --- DEPENDENCY MANAGEMENT ---
class DependencyManager:
    """Handles optional imports and graceful degradation."""
    MISSING_LIBS: List[str] = []
    video_processing = None
    state_manager_cls = None
    movieprint_maker = None
    image_grid = None
    
    @classmethod
    def load(cls):
        try:
            import video_processing
            cls.video_processing = video_processing
        except ImportError as e:
            cls.MISSING_LIBS.append(f"video_processing.py ({e})")

        try:
            import image_grid
            cls.image_grid = image_grid
        except ImportError as e:
            cls.MISSING_LIBS.append(f"image_grid.py ({e})")

        try:
            from state_manager import StateManager
            cls.state_manager_cls = StateManager
        except ImportError as e:
            cls.MISSING_LIBS.append(f"state_manager.py ({e})")

        try:
            from movieprint_maker import execute_movieprint_generation
            cls.movieprint_maker = execute_movieprint_generation
        except ImportError as e:
            cls.MISSING_LIBS.append(f"movieprint_maker ({e})")

        try:
            from version import __version__
            cls.version = __version__
        except ImportError:
            cls.version = "0.0.0"

DependencyManager.load()

# Handle TkinterDnD2 (Drag and Drop)
DND_ENABLED = False
try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    DND_ENABLED = True
except ImportError:
    # Dummy fallback class if DND is missing
    class TkinterDnD:
        class DnDWrapper:
            pass
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
    
    # 1. User Profile Log (Persistent)
    log_dir = os.path.expanduser(os.path.join("~", ".pymovieprint", "logs"))
    try:
        os.makedirs(log_dir, exist_ok=True)
        log_file = os.path.join(log_dir, "pymovieprint.log")
        handler = RotatingFileHandler(log_file, maxBytes=5*1024*1024, backupCount=3, encoding='utf-8')
        handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
        root_logger.addHandler(handler)
    except Exception as e:
        print(f"Failed to create user profile log: {e}")

    # 2. Session Log (Local)
    try:
        program_dir = os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else os.path.dirname(os.path.abspath(__file__))
        local_log_path = os.path.join(program_dir, "pymovieprint_session.log")
        local_handler = logging.FileHandler(local_log_path, mode='w', encoding='utf-8') 
        local_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
        root_logger.addHandler(local_handler)
    except Exception as e:
        print(f"Failed to create local program log: {e}")

    # 3. Console Log
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
    """Redirects logs to a thread-safe queue for GUI display."""
    def __init__(self, queue_instance: queue.Queue):
        super().__init__()
        self.queue = queue_instance

    def emit(self, record):
        log_entry = self.format(record)
        self.queue.put(("log", log_entry))

# --- UI COMPONENTS ---

class ScrubbingHandler:
    """Manages the state and logic for scrubbing through video thumbnails."""
    def __init__(self, app: 'MoviePrintApp'):
        self.app = app
        self.active: bool = False
        self.thumbnail_index: int = -1
        self.start_x: int = 0
        self.original_timestamp: float = 0.0
        self.last_update_time: float = 0.0
        self.debounce_interval: float = 0.05 # Limit updates to 20fps

    def start(self, event, thumbnail_index: int, original_timestamp: float):
        self.active = True
        self.thumbnail_index = thumbnail_index
        self.original_timestamp = original_timestamp
        self.start_x = event.x
        self.app.preview_zoomable_canvas.canvas.config(cursor="sb_h_double_arrow")

    def stop(self, event):
        if self.active:
            self.app.queue.put(("log", f"Scrubbing finished for thumbnail {self.thumbnail_index}."))
            self.active = False
            self.thumbnail_index = -1
            self.app.preview_zoomable_canvas.canvas.config(cursor="")

class ZoomableCanvas(ctk.CTkFrame):
    """A Canvas that supports zooming, panning, and drag-and-drop."""
    def __init__(self, master, app_ref: 'MoviePrintApp', **kwargs):
        super().__init__(master, **kwargs)
        self.app_ref = app_ref
        
        # UI Setup
        self.canvas = tk.Canvas(self, background=Theme.BG_PRIMARY, highlightthickness=0)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        
        self.vsb = ctk.CTkScrollbar(self, orientation="vertical", command=self.canvas.yview, fg_color=Theme.BG_SECONDARY)
        self.hsb = ctk.CTkScrollbar(self, orientation="horizontal", command=self.canvas.xview, fg_color=Theme.BG_SECONDARY)
        self.canvas.configure(yscrollcommand=self.vsb.set, xscrollcommand=self.hsb.set)
        
        self.vsb.grid(row=0, column=1, sticky="ns")
        self.hsb.grid(row=1, column=0, sticky="ew")
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)

        # State
        self.image_id: Optional[int] = None
        self.original_image: Optional[Image.Image] = None
        self.photo_image: Optional[ImageTk.PhotoImage] = None
        self._zoom_level: float = 1.0

        # Bindings
        self.canvas.bind("<ButtonPress-1>", self.on_button_press)
        self.canvas.bind("<B1-Motion>", self.on_mouse_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_button_release)
        self.canvas.bind("<MouseWheel>", self.on_mouse_wheel) # Windows
        self.canvas.bind("<Button-4>", self.on_mouse_wheel)   # Linux Scroll Up
        self.canvas.bind("<Button-5>", self.on_mouse_wheel)   # Linux Scroll Down
        
        if DND_ENABLED:
            try:
                self.canvas.drop_target_register(DND_FILES)
                self.canvas.dnd_bind('<<Drop>>', self.app_ref.handle_drop)
            except Exception as e:
                logging.warning(f"Failed to bind DND to canvas: {e}")

    def on_button_press(self, event):
        if self.app_ref.is_scrubbing_active():
            self.app_ref.stop_scrubbing(event)
            return
        
        # Check if user clicked on a specific thumbnail to start scrubbing
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
        if self.app_ref.is_scrubbing_active():
            return
        
        scale_factor = 1.1
        # Cross-platform scroll detection
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
        if not self.original_image or not self.image_id:
            return
        
        new_width = int(self.original_image.width * self._zoom_level)
        new_height = int(self.original_image.height * self._zoom_level)
        new_width = max(1, new_width)
        new_height = max(1, new_height)
        
        # Use Nearest Neighbor for fast previews when zooming out, Bilinear for zooming in
        resample_filter = Image.Resampling.BILINEAR if self._zoom_level < 1.0 else Image.Resampling.NEAREST
        
        zoomed_image = self.original_image.resize((new_width, new_height), resample_filter)
        self.photo_image = ImageTk.PhotoImage(zoomed_image)
        self.canvas.itemconfig(self.image_id, image=self.photo_image)
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def set_image(self, image_path: str):
        if not image_path or not os.path.exists(image_path):
            self.clear()
            return
        try:
            self.original_image = Image.open(image_path)
            # Reset zoom on new image load
            self.app_ref.zoom_level_var.set(1.0)
            self._zoom_level = 1.0
            
            self.photo_image = ImageTk.PhotoImage(self.original_image)
            if self.image_id:
                self.canvas.delete(self.image_id)
            self.image_id = self.canvas.create_image(0, 0, anchor="nw", image=self.photo_image)
            self.canvas.configure(scrollregion=self.canvas.bbox(self.image_id))
        except Exception as e:
            logging.error(f"Error setting image: {e}")
            self.clear()

    def clear(self):
        if self.image_id:
            self.canvas.delete(self.image_id)
        self.image_id = None
        self.original_image = None
        self.photo_image = None
        self.canvas.configure(scrollregion=(0,0,0,0))

class CTkCollapsibleFrame(ctk.CTkFrame):
    """A standard collapsible frame for advanced settings."""
    def __init__(self, master, title="", **kwargs):
        super().__init__(master, **kwargs)
        self.grid_columnconfigure(0, weight=1)
        self.variable = ctk.BooleanVar(value=True)

        self.title_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.title_frame.grid(row=0, column=0, sticky="ew")
        self.title_frame.grid_columnconfigure(1, weight=1)

        self.toggle_button = ctk.CTkButton(
            self.title_frame,
            text=f"- {title}",
            command=self.toggle,
            width=30,
            fg_color="transparent",
            text_color=Theme.ACCENT_CYAN,
            hover=False,
            anchor="w",
            font=Theme.FONT_BOLD
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

    def get_content_frame(self):
        return self.sub_frame

# --- MAIN APPLICATION ---

class MoviePrintApp(ctk.CTk, TkinterDnD.DnDWrapper):
    def __init__(self):
        super().__init__()
        
        # 1. Dependency Check
        if DependencyManager.MISSING_LIBS:
            self.withdraw()
            error_msg = "Required dependencies missing:\n" + "\n".join(DependencyManager.MISSING_LIBS)
            messagebox.showerror("Startup Error", error_msg)
            sys.exit(1)

        # 2. Initialization
        self.title(f"PyMoviePrint Generator v{DependencyManager.version}")
        self.geometry("1500x950")
        self.configure(fg_color=Theme.BG_PRIMARY)
        
        # 3. State & Logic Setup
        self._init_dnd()
        self.scrubbing_handler = ScrubbingHandler(self)
        self.active_scrubs: Dict[int, bool] = {} # Lock map for scrub threads
        self.temp_dirs_to_cleanup: List[str] = []
        self._internal_input_paths: List[str] = []
        self.thumbnail_paths: List[str] = [] 
        self.queue = queue.Queue()
        self.preview_temp_dir: Optional[str] = None
        self.is_landing_state = True
        
        self.state_manager = DependencyManager.state_manager_cls()
        
        self._init_variables()
        self._bind_settings_to_state()
        
        # 4. UI Construction
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self._build_sidebar()
        self._build_main_area()
        self._build_toolbar()
        self._build_action_footer()

        self._load_persistent_settings()
        self._start_queue_poller()
        
        # 5. Bindings
        self.protocol("WM_DELETE_WINDOW", self._on_closing)
        self.bind("<Control-z>", self.perform_undo)
        self.bind("<Control-y>", self.perform_redo)
        self._update_live_math()

    # --- INITIALIZATION HELPERS ---
    
    def _init_dnd(self):
        self.dnd_active = False
        if DND_ENABLED:
            try:
                self.TkdndVersion = TkinterDnD._require(self)
                self.dnd_active = True
            except Exception as e:
                logging.error(f"Drag and Drop init failed: {e}")
    
    def _init_variables(self):
        """Initializes Tkinter variables and maps them to settings keys."""
        # Defaults
        defaults = {
            "input_paths_var": "", "output_dir_var": "", "extraction_mode_var": "interval",
            "interval_seconds_var": "5.0", "interval_frames_var": "", "shot_threshold_var": "27.0",
            "exclude_frames_var": "", "exclude_shots_var": "", "layout_mode_var": "grid",
            "num_columns_var": "5", "num_rows_var": "5", "target_row_height_var": "150",
            "output_image_width_var": "1920", "padding_var": "5", "background_color_var": "#1e1e1e",
            "frame_format_var": "jpg", "save_metadata_json_var": True, "detect_faces_var": False,
            "rotate_thumbnails_var": 0, "start_time_var": "", "end_time_var": "",
            "output_filename_suffix_var": "-thumb", "output_filename_var": "",
            "video_extensions_var": ".mp4,.avi,.mov,.mkv,.flv,.wmv", "recursive_scan_var": False,
            "temp_dir_var": "", "haar_cascade_xml_var": "", "max_frames_for_print_var": "100",
            "target_thumbnail_width_var": "", "output_width_var": "", "output_height_var": "",
            "target_thumbnail_height_var": "", "max_output_filesize_kb_var": "", 
            "preview_quality_var": 75, "output_quality_var": 95,
            "grid_margin_var": "0", "show_header_var": True, "show_file_path_var": True,
            "show_timecode_var": True, "show_frame_num_var": True, "rounded_corners_var": 20,
            "frame_info_show_var": False, "frame_info_timecode_or_frame_var": "timecode",
            "frame_info_font_color_var": "#FFFFFF", "frame_info_bg_color_var": "#000000",
            "frame_info_position_var": "bottom_left", "frame_info_size_var": "10", 
            "frame_info_margin_var": "5", "use_gpu_var": False
        }

        # Check for GPU (Pragmatist check)
        startup_logger = logging.getLogger("startup_check")
        startup_logger.addHandler(logging.NullHandler())
        gpu_detected = False
        try:
            gpu_detected = DependencyManager.video_processing.check_ffmpeg_gpu(startup_logger)
        except Exception: pass
        defaults["use_gpu_var"] = gpu_detected

        # Create Vars
        for k, v in defaults.items():
            if not hasattr(self, k):
                if isinstance(v, bool): setattr(self, k, tk.BooleanVar(value=v))
                elif isinstance(v, int): setattr(self, k, tk.IntVar(value=v))
                elif isinstance(v, float): setattr(self, k, tk.DoubleVar(value=v))
                else: setattr(self, k, tk.StringVar(value=v))
        
        self.zoom_level_var = tk.DoubleVar(value=1.0)
        
        # Mapping for State Manager
        self.settings_map = {
            "input_paths_var": "input_paths", "output_dir_var": "output_dir",
            "extraction_mode_var": "extraction_mode", "interval_seconds_var": "interval_seconds",
            "layout_mode_var": "layout_mode", "num_columns_var": "num_columns",
            "num_rows_var": "num_rows", "use_gpu_var": "use_gpu",
            "background_color_var": "background_color", "padding_var": "padding",
            "grid_margin_var": "grid_margin", "rounded_corners_var": "rounded_corners",
            "rotate_thumbnails_var": "rotate_thumbnails", "show_header_var": "show_header",
            "show_timecode_var": "show_timecode", "frame_info_show_var": "frame_info_show",
            "output_quality_var": "output_quality", "frame_format_var": "frame_format",
            "frame_info_font_color_var": "frame_info_font_color",
            "frame_info_bg_color_var": "frame_info_bg_color",
            "frame_info_position_var": "frame_info_position",
            "frame_info_size_var": "frame_info_size",
            "frame_info_margin_var": "frame_info_margin",
        }

    # --- UI BUILDING BLOCKS ---

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
        
        ctk.CTkButton(btn_frame, text="PREVIEW", command=self.start_thumbnail_preview_generation,
                      fg_color="transparent", border_width=1, border_color=Theme.ACCENT_CYAN,
                      text_color=Theme.ACCENT_CYAN).pack(side="left", padx=5)
                      
        ctk.CTkButton(btn_frame, text="APPLY / SAVE", command=self.generate_movieprint_action,
                      fg_color=Theme.ACCENT_CYAN, text_color=Theme.BG_PRIMARY,
                      hover_color=Theme.BUTTON_HOVER, font=Theme.FONT_BOLD,
                      width=150).pack(side="left", padx=5)

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
        steps = [("1", "Drag and Drop", "Video files"), ("2", "Customise", "Layout & Style"), ("3", "Save", "Export Image")]
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
        colors = ["#008B8B", "#00CED1", "#2F4F4F", "#1E1E1E"]
        import random
        self.hero_canvas.delete("all")
        w, h = 500, 300
        col_count = 5
        col_w = w / col_count
        y_offsets = [0] * col_count
        for _ in range(30):
            c = random.randint(0, col_count - 1)
            block_h = random.randint(40, 100)
            color = random.choice(colors)
            x = c * col_w
            y = y_offsets[c]
            self.hero_canvas.create_rectangle(x + 2, y + 2, x + col_w - 2, y + block_h - 2, fill=color, outline="")
            y_offsets[c] += block_h

    def _create_grid_controller(self, parent):
        # Math Display
        self.live_math_frame = ctk.CTkFrame(parent, fg_color="transparent")
        self.live_math_frame.pack(fill="x", padx=10, pady=20)
        
        font_lg = ("Roboto", 32, "bold")
        font_md = ("Roboto", 24)
        
        self.math_lbl_cols = ctk.CTkLabel(self.live_math_frame, text="5", font=font_lg, text_color="white")
        self.math_lbl_cols.pack(side="left", expand=True)
        ctk.CTkLabel(self.live_math_frame, text="×", font=font_md, text_color=Theme.TEXT_MUTED).pack(side="left")
        self.math_lbl_rows = ctk.CTkLabel(self.live_math_frame, text="?", font=font_lg, text_color="white")
        self.math_lbl_rows.pack(side="left", expand=True)
        ctk.CTkLabel(self.live_math_frame, text="=", font=font_md, text_color=Theme.TEXT_MUTED).pack(side="left")
        self.math_lbl_res = ctk.CTkLabel(self.live_math_frame, text="?", font=font_lg, text_color=Theme.ACCENT_CYAN)
        self.math_lbl_res.pack(side="left", expand=True)

        # Input Source
        input_frame = ctk.CTkFrame(parent, fg_color="#2B2B2B")
        input_frame.pack(fill="x", padx=10, pady=10)
        ctk.CTkLabel(input_frame, text="INPUT SOURCE", font=Theme.FONT_BOLD).pack(anchor="w", padx=10, pady=5)
        
        self.input_entry = ctk.CTkEntry(input_frame, textvariable=self.input_paths_var, placeholder_text="Drag files here...", border_color=Theme.ACCENT_CYAN)
        self.input_entry.pack(fill="x", padx=10, pady=(0,5))
        
        if self.dnd_active:
            try:
                self.input_entry.drop_target_register(DND_FILES)
                self.input_entry.dnd_bind('<<Drop>>', self.handle_drop)
            except Exception: pass
            
        ctk.CTkButton(input_frame, text="Browse", command=self.browse_input_paths, fg_color=Theme.ACCENT_CYAN, 
                      text_color=Theme.BG_PRIMARY, hover_color=Theme.BUTTON_HOVER).pack(fill="x", padx=10, pady=10)

        # Sliders
        self._create_cyber_slider_section(parent)
        
        # Advanced
        adv_frame = CTkCollapsibleFrame(parent, title="Advanced Settings")
        adv_frame.pack(fill="x", padx=10, pady=5)
        self._populate_advanced_settings(adv_frame.get_content_frame())

    def _create_cyber_slider_section(self, parent):
        self.slider_frame = ctk.CTkFrame(parent, fg_color="transparent")
        self.slider_frame.pack(fill="x", padx=10, pady=10)
        
        # Columns
        ctk.CTkLabel(self.slider_frame, text="COLUMNS", font=Theme.FONT_BOLD, text_color=Theme.TEXT_MAIN).pack(anchor="w")
        self.col_slider = ctk.CTkSlider(self.slider_frame, from_=1, to=20, number_of_steps=19, variable=None, 
                                       command=self._on_col_slider_change, progress_color=Theme.ACCENT_CYAN, 
                                       button_color=Theme.ACCENT_GLOW, button_hover_color="white")
        self.col_slider.set(5)
        self.col_slider.pack(fill="x", pady=(0, 15))
        
        # Rows
        ctk.CTkLabel(self.slider_frame, text="ROWS", font=Theme.FONT_BOLD, text_color=Theme.TEXT_MAIN).pack(anchor="w")
        self.row_slider = ctk.CTkSlider(self.slider_frame, from_=1, to=20, number_of_steps=19, variable=None, 
                                       command=self._on_row_slider_change, progress_color=Theme.ACCENT_CYAN, 
                                       button_color=Theme.ACCENT_GLOW, button_hover_color="white")
        self.row_slider.set(5)
        self.row_slider.pack(fill="x", pady=(0, 15))

    def _populate_advanced_settings(self, parent):
        # Modes
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
        
        # Conditional Frames
        self.shot_threshold_frame = ctk.CTkFrame(parent, fg_color="transparent")
        self.shot_threshold_frame.pack(fill="x", pady=5)
        ctk.CTkLabel(self.shot_threshold_frame, text="Shot Threshold:").pack(side="left")
        ctk.CTkEntry(self.shot_threshold_frame, textvariable=self.shot_threshold_var, width=60).pack(side="left", padx=5)
        
        self.row_height_frame = ctk.CTkFrame(parent, fg_color="transparent")
        self.row_height_frame.pack(fill="x", pady=5)
        ctk.CTkLabel(self.row_height_frame, text="Target Row Height:").pack(side="left")
        ctk.CTkEntry(self.row_height_frame, textvariable=self.target_row_height_var, width=60).pack(side="left", padx=5)
        
        # Paths
        ctk.CTkLabel(parent, text="Output Directory:").pack(anchor="w")
        ctk.CTkEntry(parent, textvariable=self.output_dir_var).pack(fill="x", pady=5)
        ctk.CTkButton(parent, text="Select Output", command=self.browse_output_dir, fg_color=Theme.BG_SECONDARY, 
                      border_width=1, border_color=Theme.ACCENT_CYAN).pack(fill="x", pady=5)
        
        # Toggles
        ctk.CTkSwitch(parent, text="Show Frame Info/Timecode", variable=self.frame_info_show_var, progress_color=Theme.ACCENT_CYAN, command=self.quick_refresh_layout).pack(anchor="w", pady=5)
        ctk.CTkCheckBox(parent, text="Detect Faces", variable=self.detect_faces_var, fg_color=Theme.ACCENT_CYAN, hover_color=Theme.BUTTON_HOVER).pack(anchor="w", pady=2)
        ctk.CTkCheckBox(parent, text="Use GPU (FFmpeg)", variable=self.use_gpu_var, fg_color=Theme.ACCENT_CYAN, hover_color=Theme.BUTTON_HOVER).pack(anchor="w", pady=2)
        ctk.CTkCheckBox(parent, text="Show Header", variable=self.show_header_var, fg_color=Theme.ACCENT_CYAN, hover_color=Theme.BUTTON_HOVER, command=self.quick_refresh_layout).pack(anchor="w", pady=2)
        ctk.CTkCheckBox(parent, text="Show Timecode", variable=self.show_timecode_var, fg_color=Theme.ACCENT_CYAN, hover_color=Theme.BUTTON_HOVER, command=self.quick_refresh_layout).pack(anchor="w", pady=2)
        
        # Aesthetics
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

        # Quality
        ctk.CTkLabel(parent, text="Output Format:").pack(anchor="w", pady=(10, 0))
        self.format_seg = ctk.CTkSegmentedButton(parent, values=["jpg", "png"], variable=self.frame_format_var, 
                                                 selected_color=Theme.ACCENT_CYAN, selected_hover_color=Theme.BUTTON_HOVER)
        self.format_seg.pack(fill="x", pady=5)
        
        ctk.CTkLabel(parent, text="Preview Quality (Fast):").pack(anchor="w", pady=(10,0))
        ctk.CTkSlider(parent, from_=10, to=100, variable=self.preview_quality_var).pack(fill="x")
        
        ctk.CTkLabel(parent, text="Output Quality (JPG):").pack(anchor="w", pady=(10,0))
        ctk.CTkSlider(parent, from_=10, to=100, variable=self.output_quality_var, progress_color=Theme.ACCENT_CYAN).pack(fill="x")
        
        self.update_visibility_state()

    # --- LOGIC & EVENT HANDLING ---

    def _bind_settings_to_state(self):
        for var_name, setting_key in self.settings_map.items():
            if hasattr(self, var_name):
                var = getattr(self, var_name)
                # Use lambda capture to bind specific args
                var.trace_add("write", lambda *args, v=var_name, s=setting_key: self._on_setting_change(v, s))

    def _on_setting_change(self, var_name, setting_key):
        try:
            var = getattr(self, var_name)
            val = var.get()
            
            # Simple type coercion logic
            current_settings = self.state_manager.get_settings()
            if hasattr(current_settings, setting_key):
                target_type = type(getattr(current_settings, setting_key))
                if target_type is int:
                    try: val = int(val) if val else 0
                    except ValueError: val = 0
                elif target_type is float:
                    try: val = float(val) if val else 0.0
                    except ValueError: val = 0.0
                elif target_type is list:
                    if setting_key == "input_paths" and isinstance(val, str):
                         val = [p.strip() for p in val.split(';') if p.strip()]

            # Update State
            self.state_manager.update_settings({setting_key: val}, commit=False)
        except Exception: 
            pass # Suppress transient casting errors

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
        
        # 1. Restore UI Variables
        for var_name, setting_key in self.settings_map.items():
            if hasattr(self, var_name) and hasattr(settings, setting_key):
                val = getattr(settings, setting_key)
                if setting_key == "input_paths" and isinstance(val, list):
                    val = "; ".join(val)
                getattr(self, var_name).set(val)

        # 2. Restore Visual Sliders
        try:
            self.col_slider.set(settings.num_columns)
            self.row_slider.set(settings.num_rows)
            self.rounded_corners_var.set(settings.rounded_corners)
        except AttributeError: pass

        # 3. Restore Grid Image
        if state.thumbnail_metadata and self.preview_temp_dir:
            self._restore_grid_visuals(state, settings)
                
        self._update_live_math()

    def _restore_grid_visuals(self, state, settings):
        image_paths = [item.get('frame_path') for item in state.thumbnail_metadata]
        grid_path = os.path.join(self.preview_temp_dir, "preview_restored.jpg")
        
        success, layout = DependencyManager.image_grid.create_image_grid(
            image_source_data=image_paths,
            output_path=grid_path,
            columns=settings.num_columns,
            background_color_hex=settings.background_color,
            padding=settings.padding,
            logger=logging.getLogger("restore"),
            rounded_corners=settings.rounded_corners,
            rotation=settings.rotate_thumbnails,
            grid_margin=settings.grid_margin,
            show_header=settings.show_header,
            show_timecode=settings.show_timecode,
            frame_info_show=settings.frame_info_show,
            frame_info_font_color=settings.frame_info_font_color,
            frame_info_bg_color=settings.frame_info_bg_color,
            frame_info_position=settings.frame_info_position,
            frame_info_size=settings.frame_info_size,
            frame_info_margin=settings.frame_info_margin
        )
        
        self.thumbnail_layout_data = layout
        if success:
            self.preview_zoomable_canvas.set_image(grid_path)

    # --- STATE PROPERTIES WRAPPERS ---
    # Wrappers to access state directly for compatibility
    @property
    def thumbnail_metadata(self): return self.state_manager.get_state().thumbnail_metadata
    @thumbnail_metadata.setter
    def thumbnail_metadata(self, value): self.state_manager.get_state().thumbnail_metadata = value
    
    @property
    def cached_pool_metadata(self): return self.state_manager.get_state().cached_pool_metadata
    @cached_pool_metadata.setter
    def cached_pool_metadata(self, value): self.state_manager.get_state().cached_pool_metadata = value

    @property
    def thumbnail_layout_data(self): return self.state_manager.get_state().thumbnail_layout_data
    @thumbnail_layout_data.setter
    def thumbnail_layout_data(self, value): self.state_manager.get_state().thumbnail_layout_data = value

    # --- ACTION HANDLERS ---

    def _start_queue_poller(self):
        """Polls the queue for thread messages."""
        try:
            while True:
                msg_type, data = self.queue.get_nowait()
                if msg_type == "log":
                    self.status_lbl.configure(text=data)
                elif msg_type == "progress":
                    current, total, fname = data
                    if total > 0:
                        self.progress_bar.set(current / total)
                        if current < total:
                            self.status_lbl.configure(text=f"Processing {current}/{total}...")
                        else:
                            self.status_lbl.configure(text="Processing Complete.")
                elif msg_type == "preview_done":
                    self._handle_preview_done(data)
                elif msg_type == "update_thumbnail":
                    self.update_thumbnail_in_preview(data['index'], data['image'])
                self.update_idletasks()
        except queue.Empty: pass
        self.after(100, self._start_queue_poller)

    def start_thumbnail_preview_generation(self):
        if not self._internal_input_paths: return
        
        # Cleanup old temp
        if self.preview_temp_dir and os.path.exists(self.preview_temp_dir):
            self.temp_dirs_to_cleanup.append(self.preview_temp_dir)
            
        new_temp_dir = tempfile.mkdtemp(prefix="movieprint_preview_")
        self.preview_temp_dir = new_temp_dir
        self._cleanup_garbage_dirs()
        
        self.status_lbl.configure(text="Generating Preview...")
        self.progress_bar.configure(mode="indeterminate")
        self.progress_bar.start()
        
        threading.Thread(
            target=self._thumbnail_preview_thread, 
            args=(self._internal_input_paths[0], new_temp_dir),
            daemon=True
        ).start()

    def _thumbnail_preview_thread(self, video_path, temp_dir):
        import numpy as np
        
        thread_logger = logging.getLogger(f"preview_{threading.get_ident()}")
        thread_logger.addHandler(QueueHandler(self.queue))
        thread_logger.setLevel(logging.INFO)
        
        try:
            # 1. Calculate Timestamps
            cap = DependencyManager.video_processing.cv2.VideoCapture(video_path)
            duration = 600
            if cap.isOpened():
                fps = cap.get(DependencyManager.video_processing.cv2.CAP_PROP_FPS)
                frames = cap.get(DependencyManager.video_processing.cv2.CAP_PROP_FRAME_COUNT)
                duration = frames / fps if fps > 0 else 600
                cap.release()

            cols = int(self.num_columns_var.get())
            rows = int(self.num_rows_var.get())
            total_frames = cols * rows
            timestamps = np.linspace(0, duration, total_frames+2)[1:-1]
            
            # 2. Extract
            self.queue.put(("log", f"Extracting {total_frames} frames..."))
            success, meta = DependencyManager.video_processing.extract_frames_from_timestamps(
                video_path, timestamps, temp_dir, thread_logger, fast_preview=True
            )
            
            if success and meta:
                # 3. Generate Grid
                self.queue.put(("log", "Generating grid layout..."))
                paths = [m['frame_path'] for m in meta]
                grid_path = os.path.join(temp_dir, "preview_initial.jpg")
                
                grid_success, layout = DependencyManager.image_grid.create_image_grid(
                    image_source_data=paths,
                    output_path=grid_path,
                    columns=cols,
                    background_color_hex=self.background_color_var.get(),
                    padding=int(self.padding_var.get()),
                    logger=thread_logger,
                    rounded_corners=int(self.rounded_corners_var.get()), 
                    rotation=int(self.rotate_thumbnails_var.get()),
                    frame_info_show=self.frame_info_show_var.get(),
                    frame_info_timecode_or_frame=self.frame_info_timecode_or_frame_var.get(),
                    frame_info_font_color=self.frame_info_font_color_var.get(),
                    frame_info_bg_color=self.frame_info_bg_color_var.get(),
                    frame_info_position=self.frame_info_position_var.get(),
                    frame_info_size=int(self.frame_info_size_var.get()),
                    frame_info_margin=int(self.frame_info_margin_var.get())
                )
                
                if grid_success:
                    self.queue.put(("preview_done", {
                        "grid_path": grid_path, "meta": meta,
                        "layout": layout, "temp_dir": temp_dir
                    }))
                else:
                    self.queue.put(("log", "Error creating preview grid."))
            else:
                self.queue.put(("log", "Failed to extract frames."))
        except Exception as e:
            self.queue.put(("log", f"Error: {e}"))
            logging.error(e, exc_info=True)
        finally:
            self.queue.put(("progress", (0, 0, "")))

    def _handle_preview_done(self, data):
        grid_path = data.get("grid_path")
        meta = data.get("meta")
        layout = data.get("layout")
        
        # Update State
        self.cached_pool_metadata = meta
        self.thumbnail_metadata = meta
        self.thumbnail_paths = [m['frame_path'] for m in meta]
        self.thumbnail_layout_data = layout
        
        # Update UI
        if self.is_landing_state:
            self.landing_frame.grid_remove()
            self.preview_zoomable_canvas.grid(row=0, column=0, sticky="nsew")
            self.is_landing_state = False
            
        if grid_path and os.path.exists(grid_path):
            self.preview_zoomable_canvas.set_image(grid_path)
            self.status_lbl.configure(text="Preview Generated.")
            
        self.progress_bar.stop()
        self._update_live_math()
        
        # Commit State
        current_state = self.state_manager.get_state()
        current_state.cached_pool_metadata = meta
        current_state.thumbnail_metadata = meta
        current_state.thumbnail_layout_data = layout
        self.state_manager.update_state(current_state, commit=True)

    def quick_refresh_layout(self, value=None):
        """Regenerates the grid using existing frames (no re-extraction)."""
        if not self.thumbnail_metadata or not self.preview_temp_dir:
            return

        paths = [item['frame_path'] for item in self.thumbnail_metadata]
        if not paths: return

        grid_path = os.path.join(self.preview_temp_dir, "preview_refresh.jpg")
        
        logger = logging.getLogger("quick_refresh")
        success, layout = DependencyManager.image_grid.create_image_grid(
            image_source_data=paths,
            output_path=grid_path,
            columns=int(self.num_columns_var.get()),
            background_color_hex=self.background_color_var.get(),
            padding=int(self.padding_var.get()),
            logger=logger,
            rounded_corners=int(self.rounded_corners_var.get()),
            rotation=int(self.rotate_thumbnails_var.get()),
            frame_info_show=self.frame_info_show_var.get(),
            frame_info_timecode_or_frame=self.frame_info_timecode_or_frame_var.get(),
            frame_info_font_color=self.frame_info_font_color_var.get(),
            frame_info_bg_color=self.frame_info_bg_color_var.get(),
            frame_info_position=self.frame_info_position_var.get(),
            frame_info_size=int(self.frame_info_size_var.get()),
            frame_info_margin=int(self.frame_info_margin_var.get())
        )

        if success:
            self.preview_zoomable_canvas.set_image(grid_path)
            self.thumbnail_layout_data = layout

    # --- SCRUBBING LOGIC ---

    def is_scrubbing_active(self):
        return self.scrubbing_handler.active

    def start_scrubbing(self, event):
        if not self.thumbnail_layout_data or not self.preview_zoomable_canvas.original_image:
            return False
            
        # Map canvas coords to image coords
        canvas = self.preview_zoomable_canvas.canvas
        canvas_x = canvas.canvasx(event.x)
        canvas_y = canvas.canvasy(event.y)
        
        # Detect which thumbnail was clicked
        for i, thumb_info in enumerate(self.thumbnail_layout_data):
            x1, y1 = thumb_info['x'], thumb_info['y']
            x2, y2 = x1 + thumb_info['width'], y1 + thumb_info['height']
            
            if x1 <= canvas_x <= x2 and y1 <= canvas_y <= y2:
                self.state_manager.snapshot()
                self.queue.put(("log", f"Scrubbing initiated for thumbnail {i}."))
                
                original_meta = self.thumbnail_metadata[i]
                original_timestamp = original_meta.get('timestamp_sec', 0.0)
                self.scrubbing_handler.start(event, i, original_timestamp)
                return True
        return False

    def handle_scrubbing(self, event):
        if not self.scrubbing_handler.active: return
        
        # Debounce to prevent UI lag
        now = time.time()
        if now - self.scrubbing_handler.last_update_time < self.scrubbing_handler.debounce_interval:
            return
        self.scrubbing_handler.last_update_time = now

        dx = event.x - self.scrubbing_handler.start_x
        pixels_per_second = 50.0 # Sensitivity
        time_offset = dx / pixels_per_second
        
        # Bounds checking
        new_timestamp = self.scrubbing_handler.original_timestamp + time_offset
        new_timestamp = max(0, new_timestamp) # Only lower bound check for speed
        
        thumb_idx = self.scrubbing_handler.thumbnail_index
        
        # Check thread lock
        if self.active_scrubs.get(thumb_idx, False):
            return

        self.active_scrubs[thumb_idx] = True
        
        scrub_temp = os.path.join(self.preview_temp_dir, "scrub")
        os.makedirs(scrub_temp, exist_ok=True)
        frame_filename = f"scrub_thumb_{thumb_idx}.jpg"
        output_path = os.path.join(scrub_temp, frame_filename)
        
        threading.Thread(
            target=self._scrub_frame_extraction_thread,
            args=(self._internal_input_paths[0], new_timestamp, output_path, thumb_idx),
            daemon=True
        ).start()

    def _scrub_frame_extraction_thread(self, video_path, timestamp, output_path, thumb_index):
        thread_logger = logging.getLogger(f"scrub_{threading.get_ident()}")
        try:
            success = DependencyManager.video_processing.extract_specific_frame(
                video_path, timestamp, output_path, thread_logger, use_gpu=self.use_gpu_var.get()
            )
            if success:
                # Load image in thread to avoid blocking UI
                with Image.open(output_path) as img:
                    img_copy = img.copy()
                    
                self.queue.put(("update_thumbnail", {"index": thumb_index, "image": img_copy}))
                
                # Update State Metadata
                if thumb_index < len(self.thumbnail_metadata):
                    self.thumbnail_metadata[thumb_index]['timestamp_sec'] = timestamp
                    self.thumbnail_metadata[thumb_index]['frame_path'] = output_path
                    
        except Exception as e:
            print(f"Scrub error: {e}")
        finally:
            self.active_scrubs[thumb_index] = False

    def stop_scrubbing(self, event):
        if self.scrubbing_handler.active:
            self.scrubbing_handler.stop(event)

    def update_thumbnail_in_preview(self, index, new_thumb_img):
        """Hot-swaps a thumbnail in the main canvas image."""
        canvas_handler = self.preview_zoomable_canvas
        if not canvas_handler.original_image or index >= len(self.thumbnail_layout_data):
            return
            
        try:
            thumb_info = self.thumbnail_layout_data[index]
            resized_thumb = new_thumb_img.resize((thumb_info['width'], thumb_info['height']), Image.Resampling.BILINEAR)
            canvas_handler.original_image.paste(resized_thumb, (thumb_info['x'], thumb_info['y']))
            canvas_handler._apply_zoom()
        except Exception as e:
            print(f"Error updating thumbnail: {e}")
        finally:
            if new_thumb_img: new_thumb_img.close()

    # --- FINAL GENERATION ---

    def generate_movieprint_action(self):
        self.status_lbl.configure(text="Starting Generation...")
        
        # Validate Inputs
        input_paths_str = self.input_paths_var.get()
        if not hasattr(self, '_internal_input_paths') or not self._internal_input_paths:
            if input_paths_str: 
                self._internal_input_paths = [p.strip() for p in input_paths_str.split(';') if p.strip()]
            else: 
                messagebox.showerror("Input Error", "Please select video file(s).")
                return
                
        if not self.output_dir_var.get(): 
            messagebox.showerror("Input Error", "Please select output directory.")
            return

        # Prepare Settings Object
        settings = argparse.Namespace()
        settings.input_paths = self._internal_input_paths
        settings.output_dir = self.output_dir_var.get()
        
        try:
            # Map GUI vars to namespace
            settings.layout_mode = self.layout_mode_var.get()
            settings.extraction_mode = self.extraction_mode_var.get()
            settings.shot_threshold = float(self.shot_threshold_var.get())
            settings.frame_info_show = self.frame_info_show_var.get()
            settings.detect_faces = self.detect_faces_var.get()
            settings.rotate_thumbnails = int(self.rotate_thumbnails_var.get())
            settings.output_quality = int(self.output_quality_var.get())

            rows = int(self.num_rows_var.get())
            cols = int(self.num_columns_var.get())
            
            if settings.layout_mode == "grid":
                settings.rows = rows
                settings.columns = cols
                settings.max_frames_for_print = rows * cols
                settings.target_row_height = None
                settings.interval_seconds = None # Calculated dynamically by maker
            else:
                settings.rows = None
                settings.columns = None
                settings.max_frames_for_print = None
                settings.target_row_height = int(self.target_row_height_var.get() or 150)
                settings.interval_seconds = None

            # Common
            settings.padding = int(self.padding_var.get())
            settings.background_color = self.background_color_var.get()
            settings.frame_format = self.frame_format_var.get()
            settings.save_metadata_json = True
            settings.start_time = None
            settings.end_time = None
            settings.exclude_frames = None
            settings.exclude_shots = None
            settings.output_filename_suffix = self.output_filename_suffix_var.get()
            settings.output_filename = self.output_filename_var.get() or None
            settings.recursive_scan = False
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
            settings.output_image_width = 1920
            settings.target_thumbnail_width = None
            settings.output_width = None
            settings.output_height = None
            settings.target_thumbnail_height = None
            settings.video_extensions = ".mp4,.avi,.mov,.mkv,.flv,.wmv"

            # Frame Info Styles
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
            self.status_lbl.configure(text="Ready to Preview")

    def handle_drop(self, event):
        data = event.data
        if not data: return
        paths = self.tk.splitlist(data)
        valid_paths = [p for p in paths if os.path.exists(p)]
        if valid_paths:
            self._internal_input_paths = valid_paths
            self.input_paths_var.set("; ".join(valid_paths))
            self.input_entry.delete(0, tk.END)
            self.input_entry.insert(0, self.input_paths_var.get())
            self.status_lbl.configure(text="Ready to Preview")

    def browse_output_dir(self):
        d = filedialog.askdirectory()
        if d: self.output_dir_var.set(d)

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
        if value == "interval" and self.layout_mode_var.get() == "timeline":
            self.layout_mode_var.set("grid")
        self.update_visibility_state()

    def _on_layout_mode_change(self, value):
        if value == "timeline" and self.extraction_mode_var.get() == "interval":
            self.extraction_mode_var.set("shot")
        self.update_visibility_state()

    def update_visibility_state(self, *args):
        layout = self.layout_mode_var.get()
        extraction = self.extraction_mode_var.get()
        
        # Grid vs Timeline
        if layout == "grid":
            self.slider_frame.pack(fill="x", padx=10, pady=10, after=self.input_entry.master)
            self.row_height_frame.pack_forget()
        else:
            self.slider_frame.pack_forget()
            self.row_height_frame.pack(fill="x", pady=5, after=self.layout_mode_seg)
            
        # Interval vs Shot
        if extraction == "shot":
            self.shot_threshold_frame.pack(fill="x", pady=5, after=self.layout_mode_seg)
        else:
            self.shot_threshold_frame.pack_forget()
        self._update_live_math()

    def _cleanup_garbage_dirs(self):
        remaining_dirs = []
        for d in self.temp_dirs_to_cleanup:
            try:
                if os.path.exists(d): shutil.rmtree(d)
            except OSError: remaining_dirs.append(d)
        self.temp_dirs_to_cleanup = remaining_dirs

    def _load_persistent_settings(self):
        if not os.path.exists(SETTINGS_FILE): return
        try:
            with open(SETTINGS_FILE, 'r') as f:
                settings = json.load(f)
                
                # Load paths specially
                self.input_paths_var.set(settings.get("input_paths", ""))
                if self.input_paths_var.get():
                     p_str = self.input_paths_var.get()
                     self._internal_input_paths = [p.strip() for p in p_str.split(';') if p.strip()]
                
                # Load remaining simple settings
                for var_name, key in self.settings_map.items():
                    if key in settings and hasattr(self, var_name):
                        getattr(self, var_name).set(settings[key])
                
                # Update UI visuals
                self.col_slider.set(int(self.num_columns_var.get() or 5))
                self.row_slider.set(int(self.num_rows_var.get() or 5))
                
                # Update Segmented Buttons
                if hasattr(self, 'layout_mode_seg'): self.layout_mode_seg.set(self.layout_mode_var.get())
                if hasattr(self, 'extraction_mode_seg'): self.extraction_mode_seg.set(self.extraction_mode_var.get())
                if hasattr(self, 'rotate_seg'): self.rotate_seg.set(str(self.rotate_thumbnails_var.get()))
                if hasattr(self, 'format_seg'): self.format_seg.set(self.frame_format_var.get())
                
                self.update_visibility_state()

        except Exception as e: print(f"Error loading settings: {e}")

    def _save_persistent_settings(self):
        settings = {}
        for var_name, key in self.settings_map.items():
            if hasattr(self, var_name):
                settings[key] = getattr(self, var_name).get()
        try:
            with open(SETTINGS_FILE, 'w') as f: json.dump(settings, f, indent=4)
        except: pass

    def _on_closing(self):
        self._save_persistent_settings()
        if self.preview_temp_dir and os.path.exists(self.preview_temp_dir):
            self.temp_dirs_to_cleanup.append(self.preview_temp_dir)
        self._cleanup_garbage_dirs()
        self.destroy()

if __name__ == "__main__":
    setup_file_logging()
    try:
        app = MoviePrintApp()
        app.mainloop()
    except Exception as e:
        logging.critical(f"App crashed: {e}", exc_info=True)
        try:
            root = tk.Tk()
            root.withdraw()
            messagebox.showerror("Critical Error", f"The application crashed unexpectedly:\n\n{e}\n\nCheck the log file.")
        except:
            print(f"CRITICAL ERROR: {e}")