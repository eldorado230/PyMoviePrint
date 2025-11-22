import customtkinter as ctk
import tkinter as tk
import logging
from tkinter import ttk, filedialog, scrolledtext, messagebox, colorchooser
import os
import argparse
import threading
import queue
import cv2
import json
import video_processing
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
# We will define specific colors for widgets manually to match the "Cyan/Black" request
COLOR_BG_PRIMARY = "#121212"
COLOR_BG_SECONDARY = "#1E1E1E"
COLOR_ACCENT_CYAN = "#008B8B"  # Dark Cyan/Teal
COLOR_ACCENT_GLOW = "#00FFFF"  # Bright Cyan for glows/highlights
COLOR_TEXT_MAIN = "#FFFFFF"
COLOR_TEXT_MUTED = "#888888"
COLOR_BUTTON_HOVER = "#00CED1" # Slightly lighter cyan

class QueueHandler(logging.Handler):
    def __init__(self, queue_instance):
        super().__init__()
        self.queue = queue_instance

    def emit(self, record):
        log_entry = self.format(record)
        self.queue.put(("log", log_entry))

class Tooltip:
    def __init__(self, widget, text):
        self.widget = widget
        self.text = text
        self.tooltip_window = None
        widget.bind("<Enter>", self.show_tooltip)
        widget.bind("<Leave>", self.hide_tooltip)

    def show_tooltip(self, event=None):
        x, y, _, _ = self.widget.bbox("insert")
        if x is None : x,y = 0,0
        x += self.widget.winfo_rootx() + self.widget.winfo_width() // 2
        y += self.widget.winfo_rooty() + self.widget.winfo_height() + 5
        self.tooltip_window = tk.Toplevel(self.widget)
        self.tooltip_window.wm_overrideredirect(True)
        self.tooltip_window.wm_geometry(f"+{x}+{y}")
        # Use standard tk label for tooltip as Toplevel is standard tk
        label = tk.Label(self.tooltip_window, text=self.text, justify='left',
                         background="#1E1E1E", foreground="#FFFFFF", relief='solid', borderwidth=1,
                         font=("Roboto", "10", "normal"), wraplength=300)
        label.pack(ipadx=4, ipady=4)

    def hide_tooltip(self, event=None):
        if self.tooltip_window:
            self.tooltip_window.destroy()
        self.tooltip_window = None

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

        # Use standard tk Canvas for complex image manipulation
        self.canvas = tk.Canvas(self, background=COLOR_BG_PRIMARY, highlightthickness=0)
        self.canvas.grid(row=0, column=0, sticky="nsew")

        # CustomTkinter scrollbars don't work directly with standard canvas commands easily,
        # but we can wrap them.
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

        # Allow dropping files directly onto the preview canvas
        # We access the main app's handle_drop via app_ref
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
        # Don't zoom while scrubbing
        if self.app_ref.is_scrubbing_active():
            return

        scale_factor = 1.1
        if (event.num == 5 or event.delta < 0): # Scroll down/zoom out
            self.canvas.scale("all", event.x, event.y, 1/scale_factor, 1/scale_factor)
        elif (event.num == 4 or event.delta > 0): # Scroll up/zoom in
            self.canvas.scale("all", event.x, event.y, scale_factor, scale_factor)

        # Re-center the view after scaling
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
        resample_filter = Image.Resampling.LANCZOS if self._zoom_level < 1.0 else Image.Resampling.NEAREST
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
        self._internal_input_paths = []
        self.thumbnail_images = []
        self.thumbnail_paths = []
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
            # Add other mappings as needed
        }

        self._init_variables()
        self._bind_settings_to_state()
        self._load_persistent_settings()

        # Layout
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # Left Sidebar (Settings/Grid Controller)
        self.sidebar_frame = ctk.CTkScrollableFrame(self, width=350, corner_radius=0, fg_color=COLOR_BG_SECONDARY)
        self.sidebar_frame.grid(row=0, column=0, sticky="nsew")
        self._create_grid_controller(self.sidebar_frame)

        # Right Main Area (Dashboard/Preview)
        self.main_area = ctk.CTkFrame(self, fg_color=COLOR_BG_PRIMARY, corner_radius=0)
        self.main_area.grid(row=0, column=1, sticky="nsew", padx=0, pady=0)
        self.main_area.grid_rowconfigure(0, weight=1)
        self.main_area.grid_columnconfigure(0, weight=1)

        # Preview Canvas (Hidden initially)
        self.preview_zoomable_canvas = ZoomableCanvas(self.main_area, app_ref=self)

        # Landing Page (Visible initially)
        self.landing_frame = ctk.CTkFrame(self.main_area, fg_color=COLOR_BG_PRIMARY)
        self.landing_frame.grid(row=0, column=0, sticky="nsew")
        self._create_landing_page(self.landing_frame)

        # Zoom Slider (Toolbar above action footer)
        self.toolbar_frame = ctk.CTkFrame(self, height=30, fg_color=COLOR_BG_PRIMARY)
        self.toolbar_frame.grid(row=1, column=1, sticky="ew", padx=10)
        self._create_toolbar(self.toolbar_frame)

        # Action Footer (Bottom)
        self.action_frame = ctk.CTkFrame(self, height=60, fg_color=COLOR_BG_SECONDARY)
        self.action_frame.grid(row=2, column=0, columnspan=2, sticky="ew")
        self._create_action_footer(self.action_frame)

        self.check_queue()
        self.protocol("WM_DELETE_WINDOW", self._on_closing)

        self.bind("<Control-z>", self.perform_undo)
        self.bind("<Control-y>", self.perform_redo)

        # Initial Live Math Update
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
        # 1. Update Settings Variables
        settings = state.settings
        for var_name, setting_key in self.settings_map.items():
            if hasattr(self, var_name) and hasattr(settings, setting_key):
                val = getattr(settings, setting_key)

                # Convert back to Tkinter friendly format if needed
                if setting_key == "input_paths" and isinstance(val, list):
                    val = "; ".join(val)

                getattr(self, var_name).set(val)

        # 2. Update Visuals (Sliders explicitly if needed, though set() usually handles it)
        # self.col_slider.set(settings.num_columns) # Redundant if variable is bound, but safe
        if hasattr(self, 'col_slider'):
             self.col_slider.set(settings.num_columns)
        if hasattr(self, 'row_slider'):
             self.row_slider.set(settings.num_rows)

        # 3. Re-render Grid using the state's thumbnail metadata
        # We need to trigger the grid creation. We can reuse on_layout_change logic
        # BUT we must force it to use the state's metadata, not generate new ones from pool if possible.
        # However, on_layout_change is designed to slice the pool.
        # If the user Undid a "Scrub" action, the pool logic in on_layout_change would OVERWRITE the scrubbed frame.
        # So we must NOT call on_layout_change if we want to preserve specific frame changes.

        # Instead, we directly call image_grid with the metadata from state.
        # We need to extract the paths.
        if state.thumbnail_metadata:
            # Construct list of paths from metadata
            # Note: metadata items are dicts with 'frame_path'
            image_paths = [item.get('frame_path') for item in state.thumbnail_metadata]

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

                # Crucial: Update layout data in state (or sync it)
                # But wait, the layout data in state *should* be correct if we just undid.
                # Re-running create_image_grid might produce slightly different coordinates if logic changed?
                # Ideally we trust the create_image_grid to be deterministic.
                # We update the layout data in the current state to match the newly generated grid.
                self.thumbnail_layout_data = layout

                if grid_success:
                    self.preview_zoomable_canvas.set_image(grid_path)

            except Exception as e:
                print(f"Error restoring grid: {e}")

        self._update_live_math()

    @property
    def thumbnail_metadata(self):
        return self.state_manager.get_state().thumbnail_metadata

    @thumbnail_metadata.setter
    def thumbnail_metadata(self, value):
        self.state_manager.get_state().thumbnail_metadata = value

    @property
    def cached_pool_metadata(self):
        return self.state_manager.get_state().cached_pool_metadata

    @cached_pool_metadata.setter
    def cached_pool_metadata(self, value):
        self.state_manager.get_state().cached_pool_metadata = value

    @property
    def thumbnail_layout_data(self):
        return self.state_manager.get_state().thumbnail_layout_data

    @thumbnail_layout_data.setter
    def thumbnail_layout_data(self, value):
        self.state_manager.get_state().thumbnail_layout_data = value

    def _bind_settings_to_state(self):
        for var_name, setting_key in self.settings_map.items():
            if hasattr(self, var_name):
                var = getattr(self, var_name)
                # Use lambda with default args to capture current loop values
                var.trace_add("write", lambda *args, v=var_name, s=setting_key: self._on_setting_change(v, s))

    def _on_setting_change(self, var_name, setting_key):
        try:
            var = getattr(self, var_name)
            val = var.get()

            # Basic type handling based on variable type or explicit logic
            # Since ProjectSettings expects specific types, we might need conversion.
            # However, Tkinter vars often hold strings.
            current_settings = self.state_manager.get_settings()

            # Check target type on the settings object
            if hasattr(current_settings, setting_key):
                target_type = type(getattr(current_settings, setting_key))
                if target_type is int:
                    try:
                        val = int(val) if val else 0
                    except ValueError:
                        val = 0
                elif target_type is float:
                    try:
                        val = float(val) if val else 0.0
                    except ValueError:
                        val = 0.0
                elif target_type is list:
                    # Handle input_paths specially if it's a semicolon string
                    if setting_key == "input_paths" and isinstance(val, str):
                         val = [p.strip() for p in val.split(';') if p.strip()]

            self.state_manager.update_settings({setting_key: val}, commit=False)
        except Exception as e:
            print(f"Error updating state from {var_name}: {e}")

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
        self.num_rows_var = tk.StringVar()
        self.target_row_height_var = tk.StringVar(value="150")
        self.max_frames_for_print_var = tk.StringVar(value="100")
        self.max_frames_for_print_var.trace_add("write", self._handle_max_frames_change)
        self.padding_var = tk.StringVar(value="5")
        self.background_color_var = tk.StringVar(value="#1e1e1e")
        self.preview_quality_var = tk.IntVar(value=75)
        self.zoom_level_var = tk.DoubleVar(value=1.0)

        # 1. Create a temporary logger for the check
        startup_logger = logging.getLogger("startup_check")
        startup_logger.addHandler(logging.NullHandler())

        # 2. Run the check
        gpu_detected = False
        try:
            # Check if ffmpeg supports cuda
            gpu_detected = video_processing.check_ffmpeg_gpu(startup_logger)
        except Exception:
            pass

        # 3. Initialize the variable with the result
        self.use_gpu_var = tk.BooleanVar(value=gpu_detected)

        # Other vars initialized on demand or just use defaults if not bound to main UI frequently
        for k, v in self.default_settings.items():
            if not hasattr(self, k):
                if isinstance(v, bool): setattr(self, k, tk.BooleanVar(value=v))
                elif isinstance(v, int): setattr(self, k, tk.IntVar(value=v))
                else: setattr(self, k, tk.StringVar(value=v))

    def _create_landing_page(self, parent):
        parent.grid_columnconfigure(0, weight=1)
        parent.grid_rowconfigure(0, weight=1) # Spacer
        parent.grid_rowconfigure(4, weight=1) # Spacer

        # Header
        header_lbl = ctk.CTkLabel(parent, text="PYMOVIEPRINT", font=("Impact", 60), text_color=COLOR_TEXT_MAIN)
        header_lbl.grid(row=1, column=0, pady=(20, 5))
        sub_lbl = ctk.CTkLabel(parent, text="create screenshots of entire movies in an instant.", font=("Roboto", 16), text_color=COLOR_TEXT_MUTED)
        sub_lbl.grid(row=2, column=0, pady=(0, 30))

        # Masonry Hero (Simulated with Canvas)
        self.hero_canvas = ctk.CTkCanvas(parent, width=500, height=300, bg=COLOR_BG_PRIMARY, highlightthickness=0)
        self.hero_canvas.grid(row=3, column=0, pady=20)
        self._draw_masonry_placeholder()

        # 1-2-3 Workflow
        workflow_frame = ctk.CTkFrame(parent, fg_color="transparent")
        workflow_frame.grid(row=5, column=0, pady=40)

        steps = [("1", "Drag and Drop", "Video files"), ("2", "Customise", "Layout & Style"), ("3", "Save", "Export Image")]
        for i, (num, title, desc) in enumerate(steps):
            f = ctk.CTkFrame(workflow_frame, fg_color="transparent")
            f.grid(row=0, column=i, padx=40)
            ctk.CTkLabel(f, text=num, font=("Roboto", 40, "bold"), text_color=COLOR_ACCENT_CYAN).pack()
            ctk.CTkLabel(f, text=title, font=("Roboto", 16, "bold"), text_color=COLOR_TEXT_MAIN).pack()
            ctk.CTkLabel(f, text=desc, font=("Roboto", 12), text_color=COLOR_TEXT_MUTED).pack()

        # Register the landing frame as a drop target
        parent.drop_target_register(DND_FILES)
        parent.dnd_bind('<<Drop>>', self.handle_drop)

        # Also register the hero canvas so dropping on the "bricks" works
        self.hero_canvas.drop_target_register(DND_FILES)
        self.hero_canvas.dnd_bind('<<Drop>>', self.handle_drop)

    def _draw_masonry_placeholder(self):
        # Simple drawing to simulate the masonry look
        colors = ["#D35400", "#E59866", "#8B4513", "#BA4A00"] # Fallback bricks
        # Use Cyan/Dark Grey theme for 2025 look
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
        # Live Math Header
        self.live_math_frame = ctk.CTkFrame(parent, fg_color="transparent")
        self.live_math_frame.pack(fill="x", padx=10, pady=20)

        self.math_lbl_cols = ctk.CTkLabel(self.live_math_frame, text="5", font=("Roboto", 32, "bold"), text_color="white")
        self.math_lbl_cols.pack(side="left", expand=True)

        ctk.CTkLabel(self.live_math_frame, text="×", font=("Roboto", 24), text_color=COLOR_TEXT_MUTED).pack(side="left")

        self.math_lbl_rows = ctk.CTkLabel(self.live_math_frame, text="?", font=("Roboto", 32, "bold"), text_color="white")
        self.math_lbl_rows.pack(side="left", expand=True)

        ctk.CTkLabel(self.live_math_frame, text="=", font=("Roboto", 24), text_color=COLOR_TEXT_MUTED).pack(side="left")

        self.math_lbl_res = ctk.CTkLabel(self.live_math_frame, text="?", font=("Roboto", 32, "bold"), text_color=COLOR_ACCENT_CYAN) # Cyan Result
        self.math_lbl_res.pack(side="left", expand=True)

        # Sublabels
        sub_frame = ctk.CTkFrame(parent, fg_color="transparent")
        sub_frame.pack(fill="x", padx=10, pady=(0, 20))
        ctk.CTkLabel(sub_frame, text="COLS", font=("Roboto", 10), text_color=COLOR_TEXT_MUTED).pack(side="left", expand=True)
        ctk.CTkLabel(sub_frame, text="ROWS", font=("Roboto", 10), text_color=COLOR_TEXT_MUTED).pack(side="left", expand=True)
        ctk.CTkLabel(sub_frame, text="TOTAL", font=("Roboto", 10), text_color=COLOR_TEXT_MUTED).pack(side="left", expand=True)

        # Input Section (Drop Area)
        input_frame = ctk.CTkFrame(parent, fg_color="#2B2B2B")
        input_frame.pack(fill="x", padx=10, pady=10)

        ctk.CTkLabel(input_frame, text="INPUT SOURCE", font=("Roboto", 12, "bold")).pack(anchor="w", padx=10, pady=5)
        self.input_entry = ctk.CTkEntry(input_frame, textvariable=self.input_paths_var, placeholder_text="Drag files here...", border_color=COLOR_ACCENT_CYAN)
        self.input_entry.pack(fill="x", padx=10, pady=(0,5))
        self.input_entry.drop_target_register(DND_FILES)
        self.input_entry.dnd_bind('<<Drop>>', self.handle_drop)

        ctk.CTkButton(input_frame, text="Browse", command=self.browse_input_paths, fg_color=COLOR_ACCENT_CYAN, text_color=COLOR_BG_PRIMARY, hover_color=COLOR_BUTTON_HOVER).pack(fill="x", padx=10, pady=10)

        # Settings Sections
        self._create_cyber_slider_section(parent)

        # More Settings (Collapsible)
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

        # Columns Slider
        frame = self.slider_frame
        ctk.CTkLabel(frame, text="COLUMNS", font=("Roboto", 12, "bold"), text_color=COLOR_TEXT_MAIN).pack(anchor="w")
        self.col_slider = ctk.CTkSlider(frame, from_=1, to=20, number_of_steps=19, variable=None, command=self._on_col_slider_change, progress_color=COLOR_ACCENT_CYAN, button_color=COLOR_ACCENT_GLOW, button_hover_color="white")
        self.col_slider.set(5)
        self.col_slider.pack(fill="x", pady=(0, 15))

        # Rows Slider
        ctk.CTkLabel(frame, text="ROWS", font=("Roboto", 12, "bold"), text_color=COLOR_TEXT_MAIN).pack(anchor="w")
        self.row_slider = ctk.CTkSlider(frame, from_=1, to=20, number_of_steps=19, variable=None, command=self._on_row_slider_change, progress_color=COLOR_ACCENT_CYAN, button_color=COLOR_ACCENT_GLOW, button_hover_color="white")
        self.row_slider.set(5)
        self.row_slider.pack(fill="x", pady=(0, 15))

    def _populate_advanced_settings(self, parent):
        # Extraction Mode
        ctk.CTkLabel(parent, text="Extraction Mode:").pack(anchor="w", pady=(5, 0))
        self.extraction_mode_seg = ctk.CTkSegmentedButton(parent, values=["interval", "shot"], variable=self.extraction_mode_var,
                                                          selected_color=COLOR_ACCENT_CYAN, selected_hover_color=COLOR_BUTTON_HOVER,
                                                          command=self._on_extraction_mode_change)
        self.extraction_mode_seg.pack(fill="x", pady=(0, 5))

        # Layout Mode
        ctk.CTkLabel(parent, text="Layout Mode:").pack(anchor="w", pady=(5, 0))
        self.layout_mode_seg = ctk.CTkSegmentedButton(parent, values=["grid", "timeline"], variable=self.layout_mode_var,
                                                      selected_color=COLOR_ACCENT_CYAN, selected_hover_color=COLOR_BUTTON_HOVER,
                                                      command=self._on_layout_mode_change)
        self.layout_mode_seg.pack(fill="x", pady=(0, 5))

        # Shot Threshold (initially hidden or shown based on extraction)
        self.shot_threshold_frame = ctk.CTkFrame(parent, fg_color="transparent")
        self.shot_threshold_frame.pack(fill="x", pady=5)
        self.shot_threshold_label = ctk.CTkLabel(self.shot_threshold_frame, text="Shot Threshold:")
        self.shot_threshold_label.pack(side="left")
        self.shot_threshold_entry = ctk.CTkEntry(self.shot_threshold_frame, textvariable=self.shot_threshold_var, width=60)
        self.shot_threshold_entry.pack(side="left", padx=5)

        # Target Row Height (for Timeline)
        self.row_height_frame = ctk.CTkFrame(parent, fg_color="transparent")
        self.row_height_frame.pack(fill="x", pady=5)
        self.row_height_label = ctk.CTkLabel(self.row_height_frame, text="Target Row Height:")
        self.row_height_label.pack(side="left")
        self.row_height_entry = ctk.CTkEntry(self.row_height_frame, textvariable=self.target_row_height_var, width=60)
        self.row_height_entry.pack(side="left", padx=5)

        ctk.CTkLabel(parent, text="Output Directory:").pack(anchor="w")
        ctk.CTkEntry(parent, textvariable=self.output_dir_var).pack(fill="x", pady=5)
        ctk.CTkButton(parent, text="Select Output", command=self.browse_output_dir, fg_color=COLOR_BG_SECONDARY, border_width=1, border_color=COLOR_ACCENT_CYAN).pack(fill="x", pady=5)

        # Switches & Checks
        ctk.CTkSwitch(parent, text="Show Frame Info/Timecode", variable=self.frame_info_show_var, progress_color=COLOR_ACCENT_CYAN).pack(anchor="w", pady=5)
        ctk.CTkCheckBox(parent, text="Detect Faces", variable=self.detect_faces_var, fg_color=COLOR_ACCENT_CYAN, hover_color=COLOR_BUTTON_HOVER).pack(anchor="w", pady=2)
        ctk.CTkCheckBox(parent, text="Use GPU (FFmpeg)", variable=self.use_gpu_var, fg_color=COLOR_ACCENT_CYAN, hover_color=COLOR_BUTTON_HOVER).pack(anchor="w", pady=2)

        ctk.CTkCheckBox(parent, text="Show Header", variable=self.show_header_var, fg_color=COLOR_ACCENT_CYAN, hover_color=COLOR_BUTTON_HOVER).pack(anchor="w", pady=2)
        ctk.CTkCheckBox(parent, text="Show Timecode", variable=self.show_timecode_var, fg_color=COLOR_ACCENT_CYAN, hover_color=COLOR_BUTTON_HOVER).pack(anchor="w", pady=2)

        # Rotation
        ctk.CTkLabel(parent, text="Rotate Thumbnails:").pack(anchor="w", pady=(10, 0))
        self.rotate_seg = ctk.CTkSegmentedButton(parent, values=["0", "90", "180", "270"], variable=self.rotate_thumbnails_var,
                                                 selected_color=COLOR_ACCENT_CYAN, selected_hover_color=COLOR_BUTTON_HOVER)
        self.rotate_seg.pack(fill="x", pady=5)

        ctk.CTkLabel(parent, text="Background Color:").pack(anchor="w", pady=(10,0))
        ctk.CTkEntry(parent, textvariable=self.background_color_var).pack(fill="x", pady=5)
        ctk.CTkButton(parent, text="Pick Color", command=self.pick_bg_color, width=80, fg_color=COLOR_BG_SECONDARY).pack(anchor="w")

        ctk.CTkLabel(parent, text="Preview Quality:").pack(anchor="w", pady=(10,0))
        ctk.CTkSlider(parent, from_=10, to=100, variable=self.preview_quality_var).pack(fill="x")

        # Initialize visibility state
        self.update_visibility_state()

    def _create_action_footer(self, parent):
        parent.grid_columnconfigure(0, weight=1)

        # Status / Progress
        self.status_lbl = ctk.CTkLabel(parent, text="Ready", text_color=COLOR_TEXT_MUTED)
        self.status_lbl.grid(row=0, column=0, sticky="w", padx=20)

        self.progress_bar = ctk.CTkProgressBar(parent, width=300, progress_color=COLOR_ACCENT_CYAN)
        self.progress_bar.set(0)
        self.progress_bar.grid(row=0, column=1, padx=20)

        # Buttons
        btn_frame = ctk.CTkFrame(parent, fg_color="transparent")
        btn_frame.grid(row=0, column=2, sticky="e", padx=20, pady=10)

        ctk.CTkButton(btn_frame, text="PREVIEW", command=self.start_thumbnail_preview_generation, fg_color="transparent", border_width=1, border_color=COLOR_ACCENT_CYAN, text_color=COLOR_ACCENT_CYAN).pack(side="left", padx=5)
        ctk.CTkButton(btn_frame, text="APPLY / SAVE", command=self.generate_movieprint_action, fg_color=COLOR_ACCENT_CYAN, text_color=COLOR_BG_PRIMARY, hover_color=COLOR_BUTTON_HOVER, font=("Roboto", 14, "bold"), width=150).pack(side="left", padx=5)

    # --- Live Math & Slider Logic ---
    def _on_col_slider_change(self, value):
        self.num_columns_var.set(int(value))
        self.on_layout_change(value)
        self._update_live_math()

    def _on_row_slider_change(self, value):
        self.num_rows_var.set(int(value))
        self.on_layout_change(value)
        self._update_live_math()

    def _on_extraction_mode_change(self, value):
        # If user selects Interval while in Timeline, force Grid
        if value == "interval" and self.layout_mode_var.get() == "timeline":
            self.layout_mode_var.set("grid")
            self.queue.put(("log", "Interval extraction requires Grid layout. Switched."))
        self.update_visibility_state()

    def _on_layout_mode_change(self, value):
        # If user selects Timeline while in Interval, force Shot
        if value == "timeline" and self.extraction_mode_var.get() == "interval":
            self.extraction_mode_var.set("shot")
            self.queue.put(("log", "Timeline layout requires Shot extraction. Switched."))
        self.update_visibility_state()

    def update_visibility_state(self, *args):
        layout = self.layout_mode_var.get()
        extraction = self.extraction_mode_var.get()

        # Visibility Update
        if layout == "grid":
            # Position after input frame is roughly correct
            self.slider_frame.pack(fill="x", padx=10, pady=10, after=self.input_entry.master)
            self.row_height_frame.pack_forget()
        else:
            self.slider_frame.pack_forget()
            self.row_height_frame.pack(fill="x", pady=5, after=self.layout_mode_seg)

        if extraction == "shot":
            self.shot_threshold_frame.pack(fill="x", pady=5, after=self.layout_mode_seg)
        else:
            self.shot_threshold_frame.pack_forget()

        # Re-trigger live math or other updates if needed
        self._update_live_math()

    def _update_live_math(self, *args):
        try:
            cols = int(self.num_columns_var.get())
            rows = int(self.num_rows_var.get() or 5)

            self.math_lbl_cols.configure(text=str(cols))
            self.math_lbl_rows.configure(text=str(rows))
            self.math_lbl_res.configure(text=str(cols * rows))

        except Exception:
            pass

    def on_layout_change(self, val):
        # Live update of the preview grid based on slider values

        # SNAPSHOT: Capture state before destructive layout change
        self.state_manager.snapshot()

        if not hasattr(self, 'cached_pool') or not self.cached_pool:
            return

        cols = int(self.num_columns_var.get())
        rows = int(self.num_rows_var.get() or 5)
        total_needed = cols * rows

        # Select 'total_needed' frames from cached_pool evenly
        import numpy as np
        pool_size = len(self.cached_pool)
        if pool_size == 0: return

        if pool_size <= total_needed:
            selected_paths = self.cached_pool # Use all if we have fewer than needed
        else:
            indices = np.linspace(0, pool_size - 1, total_needed, dtype=int)
            selected_paths = [self.cached_pool[i] for i in indices]

        self.thumbnail_paths = list(selected_paths)

        # We also need to fake the metadata list for the scrubbing handler
        # We can reconstruct a temporary metadata list if needed, but for scrubbing
        # we need original timestamps. We can store the full metadata pool too.
        if hasattr(self, 'cached_pool_metadata'):
             if pool_size <= total_needed:
                 selected_meta = self.cached_pool_metadata
             else:
                 selected_meta = [self.cached_pool_metadata[i] for i in indices]
             self.thumbnail_metadata = selected_meta

        # Render new grid
        # We run this on the main thread for responsiveness, but image_grid is fast for ~100 images.
        # If it lags, we might need to debounce or thread it.
        import image_grid
        grid_path = os.path.join(self.preview_temp_dir, "preview_live.jpg")

        # Note: We use a simpler call here, or we can reuse create_image_grid.
        # We need to be careful not to block GUI too much.
        # For now, direct call.
        try:
            grid_success, layout = image_grid.create_image_grid(
                image_source_data=selected_paths,
                output_path=grid_path,
                columns=cols,
                background_color_hex=self.background_color_var.get(),
                padding=int(self.padding_var.get()),
                logger=logging.getLogger("layout_change") # Dummy logger
            )
            self.thumbnail_layout_data = layout
            if grid_success:
                self.preview_zoomable_canvas.set_image(grid_path)
        except Exception as e:
            print(f"Layout update error: {e}")

    # --- Functionality Hooks (Adapting old methods) ---
    def _on_closing(self):
        self._save_persistent_settings()
        if self.preview_temp_dir and os.path.exists(self.preview_temp_dir):
            import shutil
            shutil.rmtree(self.preview_temp_dir, ignore_errors=True)
        self.destroy()

    def _load_persistent_settings(self):
        try:
            if os.path.exists(SETTINGS_FILE):
                with open(SETTINGS_FILE, 'r') as f:
                    settings = json.load(f)
                    self.input_paths_var.set(settings.get("input_paths", ""))
                    if self.input_paths_var.get():
                         paths_str = self.input_paths_var.get()
                         if ";" in paths_str:
                             self._internal_input_paths = [p.strip() for p in paths_str.split(';') if p.strip()]
                         else:
                             self._internal_input_paths = [paths_str.strip()]

                    self.output_dir_var.set(settings.get("output_dir", ""))
                    self.temp_dir_var.set(settings.get("custom_temp_dir", ""))
                    self.max_frames_for_print_var.set(settings.get("max_frames_for_print", "100"))
                    self.num_columns_var.set(settings.get("num_columns", "5"))

                    # Update sliders from loaded settings
                    try: self.col_slider.set(int(self.num_columns_var.get()))
                    except: pass

                    self.interval_seconds_var.set(settings.get("interval_seconds", "5.0"))

                    if "use_gpu" in settings:
                        self.use_gpu_var.set(settings["use_gpu"])

        except Exception as e:
            print(f"Error loading settings: {e}")

    def _save_persistent_settings(self):
        settings = {
            "input_paths": self.input_paths_var.get(),
            "output_dir": self.output_dir_var.get(),
            "num_columns": self.num_columns_var.get(),
            "max_frames_for_print": self.max_frames_for_print_var.get(),
            "interval_seconds": self.interval_seconds_var.get(),
            "use_gpu": self.use_gpu_var.get(),
            # ... add others as needed
        }
        try:
            with open(SETTINGS_FILE, 'w') as f:
                json.dump(settings, f, indent=4)
        except: pass

    def check_queue(self):
        try:
            while True:
                msg_type, data = self.queue.get_nowait()
                if msg_type == "log":
                    self.status_lbl.configure(text=data) # Simple status update
                elif msg_type == "progress":
                    current, total, fname = data
                    if total > 0:
                        self.progress_bar.set(current / total)
                        self.status_lbl.configure(text=f"Processing {current}/{total}...")
                elif msg_type == "state":
                    # Enable/Disable buttons logic if needed
                    pass
                elif msg_type == "preview_grid":
                    self._display_thumbnail_preview(data)
                    # Explicitly trigger layout update if we have new pool data but no grid yet
                    if not data.get("grid_path") and hasattr(self, 'cached_pool') and self.cached_pool:
                        self.on_layout_change(None)
                    self._update_live_math()
                elif msg_type == "update_thumbnail":
                    self.update_thumbnail_in_preview(data['index'], data['image'])

                self.update_idletasks()
        except queue.Empty:
            pass
        self.after(100, self.check_queue)

    def _display_thumbnail_preview(self, data):
        if self.is_landing_state:
            self.landing_frame.grid_remove()
            self.preview_zoomable_canvas.grid(row=0, column=0, sticky="nsew")
            self.is_landing_state = False

        if isinstance(data, dict):
            grid_path = data.get("grid_path")
            temp_dir = data.get("temp_dir")
        else:
            grid_path = data
            temp_dir = None

        if grid_path: # Only set if path exists (might be empty for initial pool load)
            self.preview_zoomable_canvas.set_image(grid_path)

        # Removed auto-cleanup to allow preview to persist
        # if temp_dir:
        #     import shutil
        #     self.after(1000, lambda: shutil.rmtree(temp_dir, ignore_errors=True))

    # --- Action Wrappers ---
    def browse_input_paths(self):
        filepaths = filedialog.askopenfilenames(title="Select Video File(s)")
        if filepaths:
            self._internal_input_paths = list(filepaths)
            self.input_paths_var.set("; ".join(self._internal_input_paths))
            self.input_entry.delete(0, tk.END)
            self.input_entry.insert(0, self.input_paths_var.get())
            if len(self._internal_input_paths) == 1:
                self.after(200, lambda p=self._internal_input_paths[0]: self._auto_calculate_and_set_interval(p))
                self.start_thumbnail_preview_generation()

    def handle_drop(self, event):
        data = event.data
        # Basic cleaning of DnD data
        paths = self.tk.splitlist(data)
        valid_paths = [p for p in paths if os.path.exists(p)]
        if valid_paths:
            self._internal_input_paths = valid_paths
            self.input_paths_var.set("; ".join(valid_paths))
            self.input_entry.delete(0, tk.END)
            self.input_entry.insert(0, self.input_paths_var.get())
            if len(valid_paths) == 1 and os.path.isfile(valid_paths[0]):
                self.after(200, lambda p=valid_paths[0]: self._auto_calculate_and_set_interval(p))
                self.start_thumbnail_preview_generation()

    def browse_output_dir(self):
        d = filedialog.askdirectory()
        if d: self.output_dir_var.set(d)

    def pick_bg_color(self):
        c = colorchooser.askcolor(color=self.background_color_var.get())
        if c[1]: self.background_color_var.set(c[1])

    # --- Reused Logic (Simplified for brevity, copying core logic) ---
    def _auto_calculate_and_set_interval(self, video_path):
        # ... Same logic as before ...
        duration = self._get_video_duration_sync(video_path)
        if duration:
            frames = int(self.max_frames_for_print_var.get() or 60)
            interval = max(0.1, duration / frames)
            self.interval_seconds_var.set(f"{interval:.2f}")

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
        # Re-trigger auto calc if single file
        if len(self._internal_input_paths) == 1:
            self._auto_calculate_and_set_interval(self._internal_input_paths[0])

    def start_thumbnail_preview_generation(self):
        # ... Adaptation of previous method ...
        import tempfile, shutil
        if not self._internal_input_paths: return

        if self.preview_temp_dir and os.path.exists(self.preview_temp_dir):
            shutil.rmtree(self.preview_temp_dir, ignore_errors=True)
        self.preview_temp_dir = tempfile.mkdtemp(prefix="movieprint_preview_")

        self.status_lbl.configure(text="Generating Preview...")
        self.progress_bar.configure(mode="indeterminate")
        self.progress_bar.start()

        thread = threading.Thread(target=self._thumbnail_preview_thread, args=(self._internal_input_paths[0],))
        thread.daemon = True
        thread.start()

    def _thumbnail_preview_thread(self, video_path):
        # ... Logic from original ...
        # Minimal implementation for brevity
        import image_grid
        from movieprint_maker import parse_time_to_seconds

        thread_logger = logging.getLogger(f"preview_{threading.get_ident()}")
        thread_logger.addHandler(QueueHandler(self.queue))
        thread_logger.setLevel(logging.INFO)

        temp_dir = self.preview_temp_dir
        try:
            # New Logic: Extraction Pool
            duration = self._get_video_duration_sync(video_path)
            if not duration: duration = 600 # Fallback

            # Target pool size ~400
            interval = duration / 400.0
            if interval < 0.1: interval = 0.1

            success, meta = video_processing.extract_frames(video_path, temp_dir, thread_logger, interval_seconds=interval, fast_preview=True)
            
            if success:
                self.cached_pool_metadata = meta
                self.cached_pool = [m['frame_path'] for m in meta]

                # Trigger initial layout render (using default or current slider values)
                # Since we are in a thread, we can't update GUI directly or call on_layout_change easily if it touches GUI.
                # But on_layout_change mostly does logic. However, setting image on canvas must be on main thread.
                # We'll use the queue to trigger the initial render on main thread.
                self.queue.put(("preview_grid", {"grid_path": "", "temp_dir": temp_dir})) # Payload triggers update via on_layout_change

        except Exception as e:
            self.queue.put(("log", f"Error: {e}"))
        finally:
            self.queue.put(("progress", (0, 0, ""))) # Stop progress bar logic
            # self.progress_bar.stop() # Needs to be on main thread

    def generate_movieprint_action(self):
        # Use existing logic, adapt to new UI feedback
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
        settings.extraction_mode = self.extraction_mode_var.get()
        settings.layout_mode = self.layout_mode_var.get()

        try:
            # Map settings from GUI variables
            settings.layout_mode = self.layout_mode_var.get()
            settings.extraction_mode = self.extraction_mode_var.get()
            settings.shot_threshold = float(self.shot_threshold_var.get())
            settings.frame_info_show = self.frame_info_show_var.get()
            settings.detect_faces = self.detect_faces_var.get()
            settings.rotate_thumbnails = int(self.rotate_thumbnails_var.get())

            # Layout specific logic
            if settings.layout_mode == "grid":
                rows = int(self.num_rows_var.get() or 5)
                cols = int(self.num_columns_var.get() or 5)
                total_target = rows * cols
                settings.rows = rows
                settings.columns = cols
                settings.max_frames_for_print = total_target
                settings.target_row_height = None

                # Interval Calculation (Overshoot strategy) for Interval mode
                if settings.extraction_mode == "interval":
                    video_path = self._internal_input_paths[0]
                    duration = self._get_video_duration_sync(video_path)
                    if duration:
                        settings.interval_seconds = duration / (total_target * 1.1)
                    else:
                        settings.interval_seconds = 1.0
            else:
                # Timeline Mode Defaults
                settings.rows = None
                settings.columns = None
                settings.max_frames_for_print = None
                settings.target_row_height = int(self.target_row_height_var.get() or 150)
                settings.interval_seconds = None # Not used in shot mode

            # Common settings
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
            
            # Add missing required fields with None or Defaults
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
            execute_movieprint_generation(settings, thread_logger, progress_cb)
        except Exception as e:
            thread_logger.exception(f"Error: {e}")
        finally:
            self.queue.put(("log", "Done."))
            self.queue.put(("progress", (100, 100, "Done")))

    def _gui_progress_callback(self, current, total, filename):
        self.queue.put(("progress", (current, total, filename)))

    # Scrubbing Implementation
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
                # SNAPSHOT: Capture state before scrubbing starts (transaction start)
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
        pixels_per_second = 50.0 # Sensitivity
        time_offset = dx / pixels_per_second

        new_timestamp = self.scrubbing_handler.original_timestamp + time_offset

        video_path = self._internal_input_paths[0]
        duration = self._get_video_duration_sync(video_path)
        if duration is not None:
            new_timestamp = max(0, min(new_timestamp, duration))

        import tempfile
        # We use a separate temp dir for scrub shots or just overwrite in preview temp
        # Ideally separate to avoid conflicts if generating
        scrub_temp = os.path.join(self.preview_temp_dir, "scrub")
        os.makedirs(scrub_temp, exist_ok=True)

        frame_filename = f"scrub_thumb_{self.scrubbing_handler.thumbnail_index}.jpg"
        output_path = os.path.join(scrub_temp, frame_filename)

        # Run extraction in thread
        thread = threading.Thread(target=self._scrub_frame_extraction_thread,
                                  args=(video_path, new_timestamp, output_path, self.scrubbing_handler.thumbnail_index))
        thread.daemon = True
        thread.start()

    def _scrub_frame_extraction_thread(self, video_path, timestamp, output_path, thumb_index):
        # Simple direct extraction
        thread_logger = logging.getLogger(f"scrub_{threading.get_ident()}")
        try:
            success = video_processing.extract_specific_frame(video_path, timestamp, output_path, thread_logger, use_gpu=self.use_gpu_var.get())
            if success:
                with Image.open(output_path) as img:
                    self.queue.put(("update_thumbnail", {"index": thumb_index, "image": img.copy()}))

                # Update metadata in memory
                if thumb_index < len(self.thumbnail_metadata):
                    self.thumbnail_metadata[thumb_index]['timestamp_sec'] = timestamp
                    self.thumbnail_metadata[thumb_index]['frame_path'] = output_path

                if thumb_index < len(self.thumbnail_paths):
                    self.thumbnail_paths[thumb_index] = output_path
        except Exception as e:
            print(f"Scrub error: {e}")

    def stop_scrubbing(self, event):
        if self.scrubbing_handler.active:
            self.scrubbing_handler.stop(event)

    def update_thumbnail_in_preview(self, index, new_thumb_img):
        canvas_handler = self.preview_zoomable_canvas
        if not canvas_handler.original_image or index >= len(self.thumbnail_layout_data):
            return

        try:
            thumb_info = self.thumbnail_layout_data[index]
            resized_thumb = new_thumb_img.resize((thumb_info['width'], thumb_info['height']), Image.Resampling.LANCZOS)
            canvas_handler.original_image.paste(resized_thumb, (thumb_info['x'], thumb_info['y']))
            canvas_handler._apply_zoom()
        except Exception as e:
            print(f"Error updating thumbnail: {e}")
        finally:
            if new_thumb_img: new_thumb_img.close()

if __name__ == "__main__":
    app = MoviePrintApp()
    app.mainloop()
