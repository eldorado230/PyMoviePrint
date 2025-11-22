import customtkinter as ctk
import tkinter as tk
import logging
from logging.handlers import RotatingFileHandler
from tkinter import ttk, filedialog, scrolledtext, messagebox, colorchooser
import os
import sys
import platform
import shutil
import tempfile
import argparse
import threading
import queue
import cv2
import json
import math
import time
import video_processing
import numpy as np # Ensure numpy is imported for linspace
from version import __version__
from tkinterdnd2 import DND_FILES, TkinterDnD
from PIL import ImageTk, Image
from state_manager import StateManager

# Attempt to import the backend logic
try:
    from movieprint_maker import execute_movieprint_generation
except ImportError as e:
    messagebox.showerror("Import Error",
                         f"Failed to import 'movieprint_maker'. Ensure it's in the Python path.\nError: {e}")
    exit()

SETTINGS_FILE = "movieprint_gui_settings.json"

# --- Theme Configuration ---
ctk.set_appearance_mode("Dark")
COLOR_BG_PRIMARY = "#121212"
COLOR_BG_SECONDARY = "#1E1E1E"
COLOR_ACCENT_CYAN = "#008B8B" 
COLOR_ACCENT_GLOW = "#00FFFF"
COLOR_TEXT_MAIN = "#FFFFFF"
COLOR_TEXT_MUTED = "#888888"
COLOR_BUTTON_HOVER = "#00CED1"

def setup_file_logging():
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    
    log_dir = os.path.expanduser(os.path.join("~", ".pymovieprint", "logs"))
    try:
        os.makedirs(log_dir, exist_ok=True)
        log_file = os.path.join(log_dir, "pymovieprint.log")
        handler = RotatingFileHandler(log_file, maxBytes=5*1024*1024, backupCount=3, encoding='utf-8')
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        handler.setFormatter(formatter)
        root_logger.addHandler(handler)
    except Exception as e:
        print(f"Failed to create user profile log: {e}")

    try:
        if getattr(sys, 'frozen', False):
            program_dir = os.path.dirname(sys.executable)
        else:
            program_dir = os.path.dirname(os.path.abspath(__file__))
            
        local_log_path = os.path.join(program_dir, "pymovieprint_session.log")
        local_handler = logging.FileHandler(local_log_path, mode='w', encoding='utf-8') 
        local_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        local_handler.setFormatter(local_formatter)
        root_logger.addHandler(local_handler)
    except Exception as e:
        print(f"Failed to create local program log: {e}")

    def handle_exception(exc_type, exc_value, exc_traceback):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return
        logging.critical("Uncaught exception", exc_info=(exc_type, exc_value, exc_traceback))

    sys.excepthook = handle_exception

class QueueHandler(logging.Handler):
    def __init__(self, queue_instance):
        super().__init__()
        self.queue = queue_instance

    def emit(self, record):
        log_entry = self.format(record)
        self.queue.put(("log", log_entry))

class ScrubbingHandler:
    def __init__(self, app):
        self.app = app
        self.active = False
        self.thumbnail_index = -1
        self.start_x = 0
        self.last_x = 0
        self.original_timestamp = 0

    def start(self, event, thumbnail_index, original_timestamp):
        self.active = True
        self.thumbnail_index = thumbnail_index
        self.original_timestamp = original_timestamp
        self.start_x = event.x
        self.last_x = event.x
        self.app.preview_zoomable_canvas.canvas.config(cursor="sb_h_double_arrow")

    def stop(self, event):
        self.app.queue.put(("log", f"Scrubbing finished for thumbnail {self.thumbnail_index}."))
        self.active = False
        self.thumbnail_index = -1
        self.app.preview_zoomable_canvas.canvas.config(cursor="")

class ZoomableCanvas(ctk.CTkFrame):
    def __init__(self, master, app_ref, **kwargs):
        super().__init__(master, **kwargs)
        self.app_ref = app_ref
        self.canvas = tk.Canvas(self, background=COLOR_BG_PRIMARY, highlightthickness=0)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.vsb = ctk.CTkScrollbar(self, orientation="vertical", command=self.canvas.yview, fg_color=COLOR_BG_SECONDARY)
        self.hsb = ctk.CTkScrollbar(self, orientation="horizontal", command=self.canvas.xview, fg_color=COLOR_BG_SECONDARY)
        self.canvas.configure(yscrollcommand=self.vsb.set, xscrollcommand=self.hsb.set)
        self.vsb.grid(row=0, column=1, sticky="ns")
        self.hsb.grid(row=1, column=0, sticky="ew")
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)
        self.image_id = None
        self.original_image = None
        self.photo_image = None
        self._zoom_level = 1.0

        self.canvas.bind("<ButtonPress-1>", self.on_button_press)
        self.canvas.bind("<B1-Motion>", self.on_mouse_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_button_release)
        self.canvas.bind("<MouseWheel>", self.on_mouse_wheel)
        self.canvas.bind("<Button-4>", self.on_mouse_wheel)
        self.canvas.bind("<Button-5>", self.on_mouse_wheel)
        self.canvas.drop_target_register(DND_FILES)
        self.canvas.dnd_bind('<<Drop>>', self.app_ref.handle_drop)

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
        if self.app_ref.is_scrubbing_active():
            return
        scale_factor = 1.1
        if (event.num == 5 or event.delta < 0):
            self.canvas.scale("all", event.x, event.y, 1/scale_factor, 1/scale_factor)
        elif (event.num == 4 or event.delta > 0):
            self.canvas.scale("all", event.x, event.y, scale_factor, scale_factor)
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def set_zoom(self, scale_level):
        scale_level = float(scale_level)
        if self._zoom_level == scale_level:
            return
        self._zoom_level = scale_level
        self._apply_zoom()

    def _apply_zoom(self):
        if not self.original_image or not self.image_id:
            return
        new_width = int(self.original_image.width * self._zoom_level)
        new_height = int(self.original_image.height * self._zoom_level)
        if new_width < 1: new_width = 1
        if new_height < 1: new_height = 1
        resample_filter = Image.Resampling.BILINEAR if self._zoom_level < 1.0 else Image.Resampling.NEAREST
        zoomed_image = self.original_image.resize((new_width, new_height), resample_filter)
        self.photo_image = ImageTk.PhotoImage(zoomed_image)
        self.canvas.itemconfig(self.image_id, image=self.photo_image)
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def set_image(self, image_path):
        if not image_path or not os.path.exists(image_path):
            self.clear()
            return
        try:
            self.original_image = Image.open(image_path)
            self.app_ref.zoom_level_var.set(1.0)
            self._zoom_level = 1.0
            self.photo_image = ImageTk.PhotoImage(self.original_image)
            if self.image_id:
                self.canvas.delete(self.image_id)
            self.image_id = self.canvas.create_image(0, 0, anchor="nw", image=self.photo_image)
            self.canvas.configure(scrollregion=self.canvas.bbox(self.image_id))
        except Exception as e:
            print(f"Error setting image: {e}")
            self.clear()

    def clear(self):
        if self.image_id:
            self.canvas.delete(self.image_id)
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
            self.title_frame,
            text=f"- {title}",
            command=self.toggle,
            width=30,
            fg_color="transparent",
            text_color=COLOR_ACCENT_CYAN,
            hover=False,
            anchor="w",
            font=("Roboto", 12, "bold")
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

class MoviePrintApp(ctk.CTk, TkinterDnD.DnDWrapper):
    def __init__(self):
        super().__init__()
        self.TkdndVersion = TkinterDnD._require(self)

        self.title(f"PyMoviePrint Generator v{__version__}")
        self.geometry("1500x950")
        self.configure(fg_color=COLOR_BG_PRIMARY)

        self.scrubbing_handler = ScrubbingHandler(self)
        self.active_scrubs = {}
        self.temp_dirs_to_cleanup = []
        self._internal_input_paths = []
        self.queue = queue.Queue()
        self.preview_temp_dir = None
        self.is_landing_state = True

        self.state_manager = StateManager()
        self.settings_map = {
            "input_paths_var": "input_paths",
            "output_dir_var": "output_dir",
            "extraction_mode_var": "extraction_mode",
            "interval_seconds_var": "interval_seconds",
            "layout_mode_var": "layout_mode",
            "num_columns_var": "num_columns",
            "num_rows_var": "num_rows",
            "use_gpu_var": "use_gpu",
            "background_color_var": "background_color",
            "padding_var": "padding",
            "grid_margin_var": "grid_margin",
        }

        self._init_variables()
        self._bind_settings_to_state()
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self.sidebar_frame = ctk.CTkScrollableFrame(self, width=350, corner_radius=0, fg_color=COLOR_BG_SECONDARY)
        self.sidebar_frame.grid(row=0, column=0, sticky="nsew")
        self._create_grid_controller(self.sidebar_frame)

        self.main_area = ctk.CTkFrame(self, fg_color=COLOR_BG_PRIMARY, corner_radius=0)
        self.main_area.grid(row=0, column=1, sticky="nsew", padx=0, pady=0)
        self.main_area.grid_rowconfigure(0, weight=1)
        self.main_area.grid_columnconfigure(0, weight=1)

        self.preview_zoomable_canvas = ZoomableCanvas(self.main_area, app_ref=self)
        self.landing_frame = ctk.CTkFrame(self.main_area, fg_color=COLOR_BG_PRIMARY)
        self.landing_frame.grid(row=0, column=0, sticky="nsew")
        self._create_landing_page(self.landing_frame)

        self.toolbar_frame = ctk.CTkFrame(self, height=30, fg_color=COLOR_BG_PRIMARY)
        self.toolbar_frame.grid(row=1, column=1, sticky="ew", padx=10)
        self._create_toolbar(self.toolbar_frame)

        self.action_frame = ctk.CTkFrame(self, height=60, fg_color=COLOR_BG_SECONDARY)
        self.action_frame.grid(row=2, column=0, columnspan=2, sticky="ew")
        self._create_action_footer(self.action_frame)

        self._load_persistent_settings()

        self.check_queue()
        self.protocol("WM_DELETE_WINDOW", self._on_closing)

        self.bind("<Control-z>", self.perform_undo)
        self.bind("<Control-y>", self.perform_redo)
        self._update_live_math()

    def perform_undo(self, event=None):
        new_state = self.state_manager.undo()
        if new_state:
            self.refresh_ui_from_state(new_state)

    def perform_redo(self, event=None):
        new_state = self.state_manager.redo()
        if new_state:
            self.refresh_ui_from_state(new_state)

    def refresh_ui_from_state(self, state):
        settings = state.settings
        for var_name, setting_key in self.settings_map.items():
            if hasattr(self, var_name) and hasattr(settings, setting_key):
                val = getattr(settings, setting_key)
                if setting_key == "input_paths" and isinstance(val, list):
                    val = "; ".join(val)
                getattr(self, var_name).set(val)

        if hasattr(self, 'col_slider'): self.col_slider.set(settings.num_columns)
        if hasattr(self, 'row_slider'): self.row_slider.set(settings.num_rows)

        # Restore Grid from Metadata
        if state.thumbnail_metadata:
            image_paths = [item.get('frame_path') for item in state.thumbnail_metadata]
            # Re-render grid image
            import image_grid
            grid_path = os.path.join(self.preview_temp_dir, "preview_restored.jpg")
            try:
                grid_success, layout = image_grid.create_image_grid(
                    image_source_data=image_paths,
                    output_path=grid_path,
                    columns=settings.num_columns,
                    background_color_hex=settings.background_color,
                    padding=settings.padding,
                    logger=logging.getLogger("restore")
                )
                self.thumbnail_layout_data = layout
                if grid_success:
                    self.preview_zoomable_canvas.set_image(grid_path)
            except Exception as e:
                print(f"Error restoring grid: {e}")
        self._update_live_math()

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

    def _bind_settings_to_state(self):
        for var_name, setting_key in self.settings_map.items():
            if hasattr(self, var_name):
                var = getattr(self, var_name)
                var.trace_add("write", lambda *args, v=var_name, s=setting_key: self._on_setting_change(v, s))

    def _on_setting_change(self, var_name, setting_key):
        try:
            var = getattr(self, var_name)
            val = var.get()
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
            self.state_manager.update_settings({setting_key: val}, commit=False)
        except Exception as e: pass

    def _init_variables(self):
        self.default_settings = {
            "input_paths_var": "", "output_dir_var": "", "extraction_mode_var": "interval",
            "interval_seconds_var": "5.0", "interval_frames_var": "", "shot_threshold_var": "27.0",
            "exclude_frames_var": "", "exclude_shots_var": "", "layout_mode_var": "grid",
            "num_columns_var": "5", "num_rows_var": "5", "target_row_height_var": "150",
            "output_image_width_var": "1920", "padding_var": "5", "background_color_var": "#1e1e1e",
            "frame_format_var": "jpg", "save_metadata_json_var": True, "detect_faces_var": False,
            "rotate_thumbnails_var": 0, "start_time_var": "", "end_time_var": "",
            "output_filename_suffix_var": "_movieprint", "output_filename_var": "",
            "video_extensions_var": ".mp4,.avi,.mov,.mkv,.flv,.wmv", "recursive_scan_var": False,
            "temp_dir_var": "", "haar_cascade_xml_var": "", "max_frames_for_print_var": "100",
            "target_thumbnail_width_var": "", "output_width_var": "", "output_height_var": "",
            "target_thumbnail_height_var": "", "max_output_filesize_kb_var": "", "preview_quality_var": 75,
            "grid_margin_var": "0", "show_header_var": True, "show_file_path_var": True,
            "show_timecode_var": True, "show_frame_num_var": True, "rounded_corners_var": "0",
            "frame_info_show_var": True, "frame_info_timecode_or_frame_var": "timecode",
            "frame_info_font_color_var": "#FFFFFF", "frame_info_bg_color_var": "#000000",
            "frame_info_position_var": "bottom_left", "frame_info_size_var": "10", "frame_info_margin_var": "5",
            "use_gpu_var": False
        }
        self.input_paths_var = tk.StringVar()
        self.output_dir_var = tk.StringVar()
        self.extraction_mode_var = tk.StringVar(value="interval")
        self.interval_seconds_var = tk.StringVar(value="5.0")
        self.interval_frames_var = tk.StringVar()
        self.shot_threshold_var = tk.StringVar(value="27.0")
        self.layout_mode_var = tk.StringVar(value="grid")
        self.num_columns_var = tk.StringVar(value="5")
        self.num_rows_var = tk.StringVar(value="5")
        self.target_row_height_var = tk.StringVar(value="150")
        self.max_frames_for_print_var = tk.StringVar(value="100")
        # self.max_frames_for_print_var.trace_add("write", self._handle_max_frames_change) # Removed for dynamic mode
        self.padding_var = tk.StringVar(value="5")
        self.background_color_var = tk.StringVar(value="#1e1e1e")
        self.preview_quality_var = tk.IntVar(value=75)
        self.zoom_level_var = tk.DoubleVar(value=1.0)

        startup_logger = logging.getLogger("startup_check")
        startup_logger.addHandler(logging.NullHandler())
        gpu_detected = False
        try:
            gpu_detected = video_processing.check_ffmpeg_gpu(startup_logger)
        except Exception: pass
        self.use_gpu_var = tk.BooleanVar(value=gpu_detected)

        for k, v in self.default_settings.items():
            if not hasattr(self, k):
                if isinstance(v, bool): setattr(self, k, tk.BooleanVar(value=v))
                elif isinstance(v, int): setattr(self, k, tk.IntVar(value=v))
                else: setattr(self, k, tk.StringVar(value=v))

    def _create_landing_page(self, parent):
        parent.grid_columnconfigure(0, weight=1)
        parent.grid_rowconfigure(0, weight=1)
        parent.grid_rowconfigure(4, weight=1)
        header_lbl = ctk.CTkLabel(parent, text="PYMOVIEPRINT", font=("Impact", 60), text_color=COLOR_TEXT_MAIN)
        header_lbl.grid(row=1, column=0, pady=(20, 5))
        sub_lbl = ctk.CTkLabel(parent, text="create screenshots of entire movies in an instant.", font=("Roboto", 16), text_color=COLOR_TEXT_MUTED)
        sub_lbl.grid(row=2, column=0, pady=(0, 30))
        self.hero_canvas = ctk.CTkCanvas(parent, width=500, height=300, bg=COLOR_BG_PRIMARY, highlightthickness=0)
        self.hero_canvas.grid(row=3, column=0, pady=20)
        self._draw_masonry_placeholder()
        workflow_frame = ctk.CTkFrame(parent, fg_color="transparent")
        workflow_frame.grid(row=5, column=0, pady=40)
        steps = [("1", "Drag and Drop", "Video files"), ("2", "Customise", "Layout & Style"), ("3", "Save", "Export Image")]
        for i, (num, title, desc) in enumerate(steps):
            f = ctk.CTkFrame(workflow_frame, fg_color="transparent")
            f.grid(row=0, column=i, padx=40)
            ctk.CTkLabel(f, text=num, font=("Roboto", 40, "bold"), text_color=COLOR_ACCENT_CYAN).pack()
            ctk.CTkLabel(f, text=title, font=("Roboto", 16, "bold"), text_color=COLOR_TEXT_MAIN).pack()
            ctk.CTkLabel(f, text=desc, font=("Roboto", 12), text_color=COLOR_TEXT_MUTED).pack()
        parent.drop_target_register(DND_FILES)
        parent.dnd_bind('<<Drop>>', self.handle_drop)
        self.hero_canvas.drop_target_register(DND_FILES)
        self.hero_canvas.dnd_bind('<<Drop>>', self.handle_drop)

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
        self.live_math_frame = ctk.CTkFrame(parent, fg_color="transparent")
        self.live_math_frame.pack(fill="x", padx=10, pady=20)
        self.math_lbl_cols = ctk.CTkLabel(self.live_math_frame, text="5", font=("Roboto", 32, "bold"), text_color="white")
        self.math_lbl_cols.pack(side="left", expand=True)
        ctk.CTkLabel(self.live_math_frame, text="×", font=("Roboto", 24), text_color=COLOR_TEXT_MUTED).pack(side="left")
        self.math_lbl_rows = ctk.CTkLabel(self.live_math_frame, text="?", font=("Roboto", 32, "bold"), text_color="white")
        self.math_lbl_rows.pack(side="left", expand=True)
        ctk.CTkLabel(self.live_math_frame, text="=", font=("Roboto", 24), text_color=COLOR_TEXT_MUTED).pack(side="left")
        self.math_lbl_res = ctk.CTkLabel(self.live_math_frame, text="?", font=("Roboto", 32, "bold"), text_color=COLOR_ACCENT_CYAN)
        self.math_lbl_res.pack(side="left", expand=True)

        sub_frame = ctk.CTkFrame(parent, fg_color="transparent")
        sub_frame.pack(fill="x", padx=10, pady=(0, 20))
        ctk.CTkLabel(sub_frame, text="COLS", font=("Roboto", 10), text_color=COLOR_TEXT_MUTED).pack(side="left", expand=True)
        ctk.CTkLabel(sub_frame, text="ROWS", font=("Roboto", 10), text_color=COLOR_TEXT_MUTED).pack(side="left", expand=True)
        ctk.CTkLabel(sub_frame, text="TOTAL", font=("Roboto", 10), text_color=COLOR_TEXT_MUTED).pack(side="left", expand=True)

        input_frame = ctk.CTkFrame(parent, fg_color="#2B2B2B")
        input_frame.pack(fill="x", padx=10, pady=10)
        ctk.CTkLabel(input_frame, text="INPUT SOURCE", font=("Roboto", 12, "bold")).pack(anchor="w", padx=10, pady=5)
        self.input_entry = ctk.CTkEntry(input_frame, textvariable=self.input_paths_var, placeholder_text="Drag files here...", border_color=COLOR_ACCENT_CYAN)
        self.input_entry.pack(fill="x", padx=10, pady=(0,5))
        self.input_entry.drop_target_register(DND_FILES)
        self.input_entry.dnd_bind('<<Drop>>', self.handle_drop)
        ctk.CTkButton(input_frame, text="Browse", command=self.browse_input_paths, fg_color=COLOR_ACCENT_CYAN, text_color=COLOR_BG_PRIMARY, hover_color=COLOR_BUTTON_HOVER).pack(fill="x", padx=10, pady=10)

        self._create_cyber_slider_section(parent)
        adv_frame = CTkCollapsibleFrame(parent, title="Advanced Settings")
        adv_frame.pack(fill="x", padx=10, pady=5)
        self._populate_advanced_settings(adv_frame.get_content_frame())

    def _create_toolbar(self, parent):
        ctk.CTkLabel(parent, text="Zoom:", text_color=COLOR_TEXT_MUTED).pack(side="left", padx=5)
        self.zoom_slider = ctk.CTkSlider(parent, from_=0.1, to=5.0, variable=self.zoom_level_var, command=self.preview_zoomable_canvas.set_zoom, width=150, progress_color=COLOR_ACCENT_CYAN)
        self.zoom_slider.pack(side="left", padx=5)

    def _create_cyber_slider_section(self, parent):
        self.slider_frame = ctk.CTkFrame(parent, fg_color="transparent")
        self.slider_frame.pack(fill="x", padx=10, pady=10)
        frame = self.slider_frame
        ctk.CTkLabel(frame, text="COLUMNS", font=("Roboto", 12, "bold"), text_color=COLOR_TEXT_MAIN).pack(anchor="w")
        self.col_slider = ctk.CTkSlider(frame, from_=1, to=20, number_of_steps=19, variable=None, command=self._on_col_slider_change, progress_color=COLOR_ACCENT_CYAN, button_color=COLOR_ACCENT_GLOW, button_hover_color="white")
        self.col_slider.set(5)
        self.col_slider.pack(fill="x", pady=(0, 15))
        ctk.CTkLabel(frame, text="ROWS", font=("Roboto", 12, "bold"), text_color=COLOR_TEXT_MAIN).pack(anchor="w")
        self.row_slider = ctk.CTkSlider(frame, from_=1, to=20, number_of_steps=19, variable=None, command=self._on_row_slider_change, progress_color=COLOR_ACCENT_CYAN, button_color=COLOR_ACCENT_GLOW, button_hover_color="white")
        self.row_slider.set(5)
        self.row_slider.pack(fill="x", pady=(0, 15))

    def _populate_advanced_settings(self, parent):
        ctk.CTkLabel(parent, text="Extraction Mode:").pack(anchor="w", pady=(5, 0))
        self.extraction_mode_seg = ctk.CTkSegmentedButton(parent, values=["interval", "shot"], variable=self.extraction_mode_var, selected_color=COLOR_ACCENT_CYAN, selected_hover_color=COLOR_BUTTON_HOVER, command=self._on_extraction_mode_change)
        self.extraction_mode_seg.pack(fill="x", pady=(0, 5))
        ctk.CTkLabel(parent, text="Layout Mode:").pack(anchor="w", pady=(5, 0))
        self.layout_mode_seg = ctk.CTkSegmentedButton(parent, values=["grid", "timeline"], variable=self.layout_mode_var, selected_color=COLOR_ACCENT_CYAN, selected_hover_color=COLOR_BUTTON_HOVER, command=self._on_layout_mode_change)
        self.layout_mode_seg.pack(fill="x", pady=(0, 5))
        self.shot_threshold_frame = ctk.CTkFrame(parent, fg_color="transparent")
        self.shot_threshold_frame.pack(fill="x", pady=5)
        self.shot_threshold_label = ctk.CTkLabel(self.shot_threshold_frame, text="Shot Threshold:")
        self.shot_threshold_label.pack(side="left")
        self.shot_threshold_entry = ctk.CTkEntry(self.shot_threshold_frame, textvariable=self.shot_threshold_var, width=60)
        self.shot_threshold_entry.pack(side="left", padx=5)
        self.row_height_frame = ctk.CTkFrame(parent, fg_color="transparent")
        self.row_height_frame.pack(fill="x", pady=5)
        self.row_height_label = ctk.CTkLabel(self.row_height_frame, text="Target Row Height:")
        self.row_height_label.pack(side="left")
        self.row_height_entry = ctk.CTkEntry(self.row_height_frame, textvariable=self.target_row_height_var, width=60)
        self.row_height_entry.pack(side="left", padx=5)
        ctk.CTkLabel(parent, text="Output Directory:").pack(anchor="w")
        ctk.CTkEntry(parent, textvariable=self.output_dir_var).pack(fill="x", pady=5)
        ctk.CTkButton(parent, text="Select Output", command=self.browse_output_dir, fg_color=COLOR_BG_SECONDARY, border_width=1, border_color=COLOR_ACCENT_CYAN).pack(fill="x", pady=5)
        ctk.CTkSwitch(parent, text="Show Frame Info/Timecode", variable=self.frame_info_show_var, progress_color=COLOR_ACCENT_CYAN).pack(anchor="w", pady=5)
        ctk.CTkCheckBox(parent, text="Detect Faces", variable=self.detect_faces_var, fg_color=COLOR_ACCENT_CYAN, hover_color=COLOR_BUTTON_HOVER).pack(anchor="w", pady=2)
        ctk.CTkCheckBox(parent, text="Use GPU (FFmpeg)", variable=self.use_gpu_var, fg_color=COLOR_ACCENT_CYAN, hover_color=COLOR_BUTTON_HOVER).pack(anchor="w", pady=2)
        ctk.CTkCheckBox(parent, text="Show Header", variable=self.show_header_var, fg_color=COLOR_ACCENT_CYAN, hover_color=COLOR_BUTTON_HOVER).pack(anchor="w", pady=2)
        ctk.CTkCheckBox(parent, text="Show Timecode", variable=self.show_timecode_var, fg_color=COLOR_ACCENT_CYAN, hover_color=COLOR_BUTTON_HOVER).pack(anchor="w", pady=2)
        ctk.CTkLabel(parent, text="Rotate Thumbnails:").pack(anchor="w", pady=(10, 0))
        self.rotate_seg = ctk.CTkSegmentedButton(parent, values=["0", "90", "180", "270"], variable=self.rotate_thumbnails_var, selected_color=COLOR_ACCENT_CYAN, selected_hover_color=COLOR_BUTTON_HOVER)
        self.rotate_seg.pack(fill="x", pady=5)
        ctk.CTkLabel(parent, text="Background Color:").pack(anchor="w", pady=(10,0))
        ctk.CTkEntry(parent, textvariable=self.background_color_var).pack(fill="x", pady=5)
        ctk.CTkButton(parent, text="Pick Color", command=self.pick_bg_color, width=80, fg_color=COLOR_BG_SECONDARY).pack(anchor="w")
        ctk.CTkLabel(parent, text="Preview Quality:").pack(anchor="w", pady=(10,0))
        ctk.CTkSlider(parent, from_=10, to=100, variable=self.preview_quality_var).pack(fill="x")
        self.update_visibility_state()

    def _create_action_footer(self, parent):
        parent.grid_columnconfigure(0, weight=1)
        self.status_lbl = ctk.CTkLabel(parent, text="Ready", text_color=COLOR_TEXT_MUTED)
        self.status_lbl.grid(row=0, column=0, sticky="w", padx=20)
        self.progress_bar = ctk.CTkProgressBar(parent, width=300, progress_color=COLOR_ACCENT_CYAN)
        self.progress_bar.set(0)
        self.progress_bar.grid(row=0, column=1, padx=20)
        btn_frame = ctk.CTkFrame(parent, fg_color="transparent")
        btn_frame.grid(row=0, column=2, sticky="e", padx=20, pady=10)
        ctk.CTkButton(btn_frame, text="PREVIEW", command=self.start_thumbnail_preview_generation, fg_color="transparent", border_width=1, border_color=COLOR_ACCENT_CYAN, text_color=COLOR_ACCENT_CYAN).pack(side="left", padx=5)
        ctk.CTkButton(btn_frame, text="APPLY / SAVE", command=self.generate_movieprint_action, fg_color=COLOR_ACCENT_CYAN, text_color=COLOR_BG_PRIMARY, hover_color=COLOR_BUTTON_HOVER, font=("Roboto", 14, "bold"), width=150).pack(side="left", padx=5)

    def _on_col_slider_change(self, value):
        self.num_columns_var.set(int(value))
        # self.on_layout_change(value) # Disabled dynamic layout change for v004 style
        self._update_live_math()

    def _on_row_slider_change(self, value):
        self.num_rows_var.set(int(value))
        # self.on_layout_change(value) # Disabled dynamic layout change for v004 style
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
        if layout == "grid":
            self.slider_frame.pack(fill="x", padx=10, pady=10, after=self.input_entry.master)
            self.row_height_frame.pack_forget()
        else:
            self.slider_frame.pack_forget()
            self.row_height_frame.pack(fill="x", pady=5, after=self.layout_mode_seg)
        if extraction == "shot":
            self.shot_threshold_frame.pack(fill="x", pady=5, after=self.layout_mode_seg)
        else:
            self.shot_threshold_frame.pack_forget()
        self._update_live_math()

    def _update_live_math(self, *args):
        try:
            cols = int(self.num_columns_var.get())
            rows = int(self.num_rows_var.get() or 5)
            self.math_lbl_cols.configure(text=str(cols))
            self.math_lbl_rows.configure(text=str(rows))
            self.math_lbl_res.configure(text=str(cols * rows))
        except Exception: pass

    def on_layout_change(self, val):
        # DEPRECATED in v004 Style (Dynamic)
        # We don't re-render grid on slider drag anymore, as we need to re-extract
        pass

    def _cleanup_garbage_dirs(self):
        remaining_dirs = []
        for d in self.temp_dirs_to_cleanup:
            try:
                if os.path.exists(d): shutil.rmtree(d)
            except OSError: remaining_dirs.append(d)
        self.temp_dirs_to_cleanup = remaining_dirs

    def _on_closing(self):
        self._save_persistent_settings()
        if self.preview_temp_dir and os.path.exists(self.preview_temp_dir):
            self.temp_dirs_to_cleanup.append(self.preview_temp_dir)
        for d in self.temp_dirs_to_cleanup:
            try:
                if os.path.exists(d): shutil.rmtree(d, ignore_errors=True)
            except Exception: pass
        self.destroy()

    def _load_persistent_settings(self):
        try:
            if os.path.exists(SETTINGS_FILE):
                with open(SETTINGS_FILE, 'r') as f:
                    settings = json.load(f)
                    # Paths
                    self.input_paths_var.set(settings.get("input_paths", ""))
                    if self.input_paths_var.get():
                         paths_str = self.input_paths_var.get()
                         if ";" in paths_str: self._internal_input_paths = [p.strip() for p in paths_str.split(';') if p.strip()]
                         else: self._internal_input_paths = [paths_str.strip()]
                    self.output_dir_var.set(settings.get("output_dir", ""))
                    self.temp_dir_var.set(settings.get("custom_temp_dir", ""))
                    
                    # Core Settings
                    self.max_frames_for_print_var.set(settings.get("max_frames_for_print", "100"))
                    self.num_columns_var.set(settings.get("num_columns", "5"))
                    self.num_rows_var.set(settings.get("num_rows", "5"))
                    
                    # Sliders visual update
                    try: self.col_slider.set(int(self.num_columns_var.get()))
                    except: pass
                    try: self.row_slider.set(int(self.num_rows_var.get()))
                    except: pass

                    self.interval_seconds_var.set(settings.get("interval_seconds", "5.0"))
                    if "use_gpu" in settings: self.use_gpu_var.set(settings["use_gpu"])
                    
                    # Full Restore
                    if "padding" in settings: self.padding_var.set(settings["padding"])
                    if "background_color" in settings: self.background_color_var.set(settings["background_color"])
                    if "layout_mode" in settings: 
                        self.layout_mode_var.set(settings["layout_mode"])
                        self.layout_mode_seg.set(settings["layout_mode"])
                    if "extraction_mode" in settings: 
                        self.extraction_mode_var.set(settings["extraction_mode"])
                        self.extraction_mode_seg.set(settings["extraction_mode"])
                    if "shot_threshold" in settings: self.shot_threshold_var.set(settings["shot_threshold"])
                    if "rotate_thumbnails" in settings: 
                        self.rotate_thumbnails_var.set(settings["rotate_thumbnails"])
                        self.rotate_seg.set(str(settings["rotate_thumbnails"]))
                    if "detect_faces" in settings: self.detect_faces_var.set(settings["detect_faces"])
                    if "show_header" in settings: self.show_header_var.set(settings["show_header"])
                    if "show_timecode" in settings: self.show_timecode_var.set(settings["show_timecode"])
                    if "preview_quality" in settings: self.preview_quality_var.set(settings["preview_quality"])
                    
                    # Force visibility update based on loaded modes
                    self.update_visibility_state()

        except Exception as e: print(f"Error loading settings: {e}")

    def _save_persistent_settings(self):
        settings = {
            "input_paths": self.input_paths_var.get(),
            "output_dir": self.output_dir_var.get(),
            "num_columns": self.num_columns_var.get(),
            "num_rows": self.num_rows_var.get(),
            "max_frames_for_print": self.max_frames_for_print_var.get(),
            "interval_seconds": self.interval_seconds_var.get(),
            "use_gpu": self.use_gpu_var.get(),
            "padding": self.padding_var.get(),
            "background_color": self.background_color_var.get(),
            "layout_mode": self.layout_mode_var.get(),
            "extraction_mode": self.extraction_mode_var.get(),
            "shot_threshold": self.shot_threshold_var.get(),
            "rotate_thumbnails": self.rotate_thumbnails_var.get(),
            "detect_faces": self.detect_faces_var.get(),
            "show_header": self.show_header_var.get(),
            "show_timecode": self.show_timecode_var.get(),
            "preview_quality": self.preview_quality_var.get()
        }
        try:
            with open(SETTINGS_FILE, 'w') as f: json.dump(settings, f, indent=4)
        except: pass

    def check_queue(self):
        try:
            while True:
                msg_type, data = self.queue.get_nowait()
                if msg_type == "log":
                    self.status_lbl.configure(text=data)
                elif msg_type == "progress":
                    current, total, fname = data
                    if total > 0:
                        self.progress_bar.set(current / total)
                        self.status_lbl.configure(text=f"Processing {current}/{total}...")
                elif msg_type == "preview_done":
                    self._handle_preview_done(data)
                elif msg_type == "update_thumbnail":
                    self.update_thumbnail_in_preview(data['index'], data['image'])
                self.update_idletasks()
        except queue.Empty: pass
        self.after(100, self.check_queue)

    def _handle_preview_done(self, data):
        grid_path = data.get("grid_path")
        meta = data.get("meta")
        layout = data.get("layout")
        
        self.thumbnail_metadata = meta
        self.thumbnail_layout_data = layout
        
        if self.is_landing_state:
            self.landing_frame.grid_remove()
            self.preview_zoomable_canvas.grid(row=0, column=0, sticky="nsew")
            self.is_landing_state = False
        if grid_path and os.path.exists(grid_path):
            self.preview_zoomable_canvas.set_image(grid_path)
            self.status_lbl.configure(text="Preview Generated.")
        self.progress_bar.stop()
        self._update_live_math()
        
        current_state = self.state_manager.get_state()
        current_state.thumbnail_metadata = meta
        current_state.thumbnail_layout_data = layout
        self.state_manager.update_state(current_state, commit=True)

    def browse_input_paths(self):
        filepaths = filedialog.askopenfilenames(title="Select Video File(s)")
        if filepaths:
            self._internal_input_paths = list(filepaths)
            self.input_paths_var.set("; ".join(self._internal_input_paths))
            self.input_entry.delete(0, tk.END)
            self.input_entry.insert(0, self.input_paths_var.get())
            if len(self._internal_input_paths) == 1:
                self.after(200, lambda p=self._internal_input_paths[0]: self._auto_calculate_and_set_interval(p))
                self.status_lbl.configure(text="Ready to Preview")

    def handle_drop(self, event):
        data = event.data
        paths = self.tk.splitlist(data)
        valid_paths = [p for p in paths if os.path.exists(p)]
        if valid_paths:
            self._internal_input_paths = valid_paths
            self.input_paths_var.set("; ".join(valid_paths))
            self.input_entry.delete(0, tk.END)
            self.input_entry.insert(0, self.input_paths_var.get())
            if len(valid_paths) == 1 and os.path.isfile(valid_paths[0]):
                self.after(200, lambda p=valid_paths[0]: self._auto_calculate_and_set_interval(p))
                self.status_lbl.configure(text="Ready to Preview")

    def browse_output_dir(self):
        d = filedialog.askdirectory()
        if d: self.output_dir_var.set(d)

    def pick_bg_color(self):
        c = colorchooser.askcolor(color=self.background_color_var.get())
        if c[1]: self.background_color_var.set(c[1])

    def _auto_calculate_and_set_interval(self, video_path):
        pass # No longer needed in dynamic mode

    def _get_video_duration_sync(self, video_path):
        try:
            cap = cv2.VideoCapture(video_path)
            if cap.isOpened():
                fps = cap.get(cv2.CAP_PROP_FPS)
                cnt = cap.get(cv2.CAP_PROP_FRAME_COUNT)
                cap.release()
                if fps > 0: return cnt / fps
        except: pass
        return None

    def _handle_max_frames_change(self, *args):
        pass # No longer needed in dynamic mode

    def start_thumbnail_preview_generation(self):
        if not self._internal_input_paths: return
        if self.preview_temp_dir and os.path.exists(self.preview_temp_dir):
            self.temp_dirs_to_cleanup.append(self.preview_temp_dir)
        new_temp_dir = tempfile.mkdtemp(prefix="movieprint_preview_")
        self.preview_temp_dir = new_temp_dir
        self._cleanup_garbage_dirs()
        self.status_lbl.configure(text="Generating Preview...")
        self.progress_bar.configure(mode="indeterminate")
        self.progress_bar.start()
        thread = threading.Thread(target=self._thumbnail_preview_thread, args=(self._internal_input_paths[0], new_temp_dir))
        thread.daemon = True
        thread.start()

    def _thumbnail_preview_thread(self, video_path, temp_dir):
        import image_grid
        import numpy as np
        thread_logger = logging.getLogger(f"preview_{threading.get_ident()}")
        thread_logger.addHandler(QueueHandler(self.queue))
        thread_logger.setLevel(logging.INFO)
        start_time = time.time()
        try:
            duration = self._get_video_duration_sync(video_path)
            if not duration: duration = 600
            
            # DYNAMIC MODE: Calculate exact timestamps
            cols = int(self.num_columns_var.get())
            rows = int(self.num_rows_var.get())
            total_frames = cols * rows
            
            timestamps = np.linspace(0, duration, total_frames+2)[1:-1] # Start slightly in, end slightly before
            
            self.queue.put(("log", f"Extracting {total_frames} frames (Dynamic Mode)..."))
            success, meta = video_processing.extract_frames_from_timestamps(
                video_path, timestamps, temp_dir, thread_logger,
                fast_preview=True
            )
            
            if success and meta:
                self.queue.put(("log", "Generating grid layout..."))
                paths = [m['frame_path'] for m in meta]
                grid_path = os.path.join(temp_dir, "preview_initial.jpg")
                
                grid_success, layout = image_grid.create_image_grid(
                    image_source_data=paths,
                    output_path=grid_path,
                    columns=cols,
                    background_color_hex=self.background_color_var.get(),
                    padding=int(self.padding_var.get()),
                    logger=thread_logger
                )
                if grid_success:
                    elapsed = time.time() - start_time
                    thread_logger.info(f"Dynamic Preview generation took {elapsed:.2f}s")
                    
                    self.queue.put(("preview_done", {
                        "grid_path": grid_path,
                        "meta": meta,
                        "layout": layout,
                        "temp_dir": temp_dir
                    }))
                else:
                    self.queue.put(("log", "Error creating preview grid."))
            else:
                self.queue.put(("log", "Failed to extract frames."))
        except Exception as e:
            self.queue.put(("log", f"Error: {e}"))
        finally:
            self.queue.put(("progress", (0, 0, "")))

    def generate_movieprint_action(self):
        self.status_lbl.configure(text="Starting Generation...")
        input_paths_str = self.input_paths_var.get()
        output_dir = self.output_dir_var.get()
        if not hasattr(self, '_internal_input_paths') or not self._internal_input_paths:
            if input_paths_str: self._internal_input_paths = [p.strip() for p in input_paths_str.split(';') if p.strip()]
            else: messagebox.showerror("Input Error", "Please select video file(s) or a directory."); return
        if not output_dir: messagebox.showerror("Input Error", "Please select an output directory."); return
        settings = argparse.Namespace()
        settings.input_paths = self._internal_input_paths
        settings.output_dir = output_dir
        try:
            settings.layout_mode = self.layout_mode_var.get()
            settings.extraction_mode = self.extraction_mode_var.get()
            settings.shot_threshold = float(self.shot_threshold_var.get())
            settings.frame_info_show = self.frame_info_show_var.get()
            settings.detect_faces = self.detect_faces_var.get()
            settings.rotate_thumbnails = int(self.rotate_thumbnails_var.get())
            
            # Force grid logic for dynamic mode
            rows = int(self.num_rows_var.get())
            cols = int(self.num_columns_var.get())
            settings.rows = rows
            settings.columns = cols
            settings.max_frames_for_print = rows * cols # Explicit count
            settings.target_row_height = None
            
            # Calculate interval for final output based on exact count
            video_path = self._internal_input_paths[0]
            duration = self._get_video_duration_sync(video_path)
            if duration:
                settings.interval_seconds = duration / (rows * cols)
            else:
                settings.interval_seconds = 1.0

            settings.padding = int(self.padding_var.get())
            settings.background_color = self.background_color_var.get()
            settings.frame_format = "jpg"
            settings.save_metadata_json = True
            settings.start_time = None
            settings.end_time = None
            settings.exclude_frames = None
            settings.exclude_shots = None
            settings.output_filename_suffix = "_movieprint"
            settings.output_filename = None
            settings.video_extensions = ".mp4,.avi"
            settings.recursive_scan = False
            settings.temp_dir = None
            settings.haar_cascade_xml = None
            settings.grid_margin = 0
            settings.show_header = self.show_header_var.get()
            settings.show_file_path = self.show_file_path_var.get()
            settings.show_timecode = self.show_timecode_var.get()
            settings.show_frame_num = self.show_frame_num_var.get()
            settings.rounded_corners = 0
            settings.max_output_filesize_kb = None
            settings.use_gpu = self.use_gpu_var.get()
            settings.interval_frames = None
            settings.output_image_width = 1920
            settings.target_thumbnail_width = None
            settings.output_width = None
            settings.output_height = None
            settings.target_thumbnail_height = None
            settings.frame_info_timecode_or_frame = "timecode"
            settings.frame_info_font_color = "#FFFFFF"
            settings.frame_info_bg_color = "#000000"
            settings.frame_info_position = "bottom_left"
            settings.frame_info_size = 10
            settings.frame_info_margin = 5
        except Exception as e:
             messagebox.showerror("Error", str(e))
             return
        self.status_lbl.configure(text="Generating...")
        self.progress_bar.configure(mode="determinate")
        thread = threading.Thread(target=self.run_generation_in_thread, args=(settings, self._gui_progress_callback))
        thread.daemon = True
        thread.start()

    def run_generation_in_thread(self, settings, progress_cb):
        thread_logger = logging.getLogger(f"gui_thread_{threading.get_ident()}")
        thread_logger.setLevel(logging.INFO)
        thread_logger.addHandler(QueueHandler(self.queue))
        try:
            execute_movieprint_generation(settings, thread_logger, progress_cb, fast_preview=False)
        except Exception as e:
            thread_logger.exception(f"Error: {e}")
        finally:
            self.queue.put(("log", "Done."))
            self.queue.put(("progress", (100, 100, "Done")))

    def _gui_progress_callback(self, current, total, filename):
        self.queue.put(("progress", (current, total, filename)))

    def is_scrubbing_active(self):
        return self.scrubbing_handler.active

    def start_scrubbing(self, event):
        if not self.thumbnail_layout_data or not self.preview_zoomable_canvas.original_image:
            return False
        canvas = self.preview_zoomable_canvas.canvas
        canvas_x = canvas.canvasx(event.x)
        canvas_y = canvas.canvasy(event.y)
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
        if not self.scrubbing_handler.active:
            return
        dx = event.x - self.scrubbing_handler.start_x
        pixels_per_second = 50.0
        time_offset = dx / pixels_per_second
        new_timestamp = self.scrubbing_handler.original_timestamp + time_offset
        video_path = self._internal_input_paths[0]
        duration = self._get_video_duration_sync(video_path)
        if duration is not None:
            new_timestamp = max(0, min(new_timestamp, duration))
        thumb_idx = self.scrubbing_handler.thumbnail_index
        if self.active_scrubs.get(thumb_idx, False):
            return
        self.active_scrubs[thumb_idx] = True
        scrub_temp = os.path.join(self.preview_temp_dir, "scrub")
        os.makedirs(scrub_temp, exist_ok=True)
        frame_filename = f"scrub_thumb_{thumb_idx}.jpg"
        output_path = os.path.join(scrub_temp, frame_filename)
        thread = threading.Thread(target=self._scrub_frame_extraction_thread,
                                  args=(video_path, new_timestamp, output_path, thumb_idx))
        thread.daemon = True
        thread.start()

    def _scrub_frame_extraction_thread(self, video_path, timestamp, output_path, thumb_index):
        thread_logger = logging.getLogger(f"scrub_{threading.get_ident()}")
        try:
            success = video_processing.extract_specific_frame(
                video_path, timestamp, output_path, thread_logger, use_gpu=self.use_gpu_var.get()
            )
            if success:
                with Image.open(output_path) as img:
                    self.queue.put(("update_thumbnail", {"index": thumb_index, "image": img.copy()}))
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

if __name__ == "__main__":
    setup_file_logging()
    app = MoviePrintApp()
    app.mainloop()