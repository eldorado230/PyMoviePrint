import tkinter as tk
import customtkinter as ctk
import logging
from tkinter import filedialog, scrolledtext, messagebox, colorchooser
import os
import argparse
import threading
import queue
import shutil
import uuid
import cv2
import json
import video_processing
from version import __version__
from tkinterdnd2 import DND_FILES, TkinterDnD
from PIL import ImageTk, Image

# Attempt to import the backend logic
try:
    from movieprint_maker import execute_movieprint_generation
except ImportError as e:
    messagebox.showerror("Import Error",
                         f"Failed to import 'movieprint_maker'. Ensure it's in the Python path.\nError: {e}")
    exit()

SETTINGS_FILE = "movieprint_gui_settings.json"

# Configure CustomTkinter
ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("dark-blue")

class QueueHandler(logging.Handler):
    def __init__(self, queue_instance):
        super().__init__()
        self.queue = queue_instance

    def emit(self, record):
        log_entry = self.format(record)
        self.queue.put(("log", log_entry))

class Tooltip:
    """
    Simple tooltip class for Tkinter/CustomTkinter widgets.
    """
    def __init__(self, widget, text):
        self.widget = widget
        self.text = text
        self.tooltip_window = None
        widget.bind("<Enter>", self.show_tooltip)
        widget.bind("<Leave>", self.hide_tooltip)

    def show_tooltip(self, event=None):
        x, y, _, _ = self.widget.bbox("insert")
        if x is None: x, y = 0, 0
        x += self.widget.winfo_rootx() + self.widget.winfo_width() // 2
        y += self.widget.winfo_rooty() + self.widget.winfo_height() + 5
        self.tooltip_window = tk.Toplevel(self.widget)
        self.tooltip_window.wm_overrideredirect(True)
        self.tooltip_window.wm_geometry(f"+{x}+{y}")
        label = tk.Label(self.tooltip_window, text=self.text, justify='left',
                         background="#ffffe0", relief='solid', borderwidth=1,
                         font=("tahoma", "8", "normal"), wraplength=300)
        label.pack(ipadx=2, ipady=2)

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
        self.temp_dir = None

    def start(self, event, thumbnail_index, original_timestamp):
        self.active = True
        self.thumbnail_index = thumbnail_index
        self.original_timestamp = original_timestamp
        self.start_x = event.x
        self.last_x = event.x
        import tempfile
        self.temp_dir = tempfile.mkdtemp(prefix="movieprint_scrub_")
        # Change cursor to indicate scrubbing is active
        self.app.preview_zoomable_canvas.canvas.config(cursor="sb_h_double_arrow")

    def stop(self, event):
        self.app.queue.put(("log", f"Scrubbing finished for thumbnail {self.thumbnail_index}."))
        self.active = False
        self.thumbnail_index = -1
        self.app.preview_zoomable_canvas.canvas.config(cursor="")
        if self.temp_dir and os.path.exists(self.temp_dir):
            try:
                shutil.rmtree(self.temp_dir, ignore_errors=True)
            except Exception as e:
                print(f"Error cleaning up scrubbing temp dir: {e}")
            self.temp_dir = None

class ZoomableCanvas(ctk.CTkFrame):
    def __init__(self, master, app_ref, **kwargs):
        super().__init__(master, **kwargs)
        self.app_ref = app_ref

        # Embed a standard Tkinter Canvas
        self.canvas = tk.Canvas(self, background="#1e1e1e", highlightthickness=0)
        self.canvas.grid(row=0, column=0, sticky="nsew")

        # Scrollbars
        # Use CTkScrollbar if possible, but linking to tk.Canvas requires standard command protocol
        self.vsb = ctk.CTkScrollbar(self, orientation="vertical", command=self.canvas.yview)
        self.hsb = ctk.CTkScrollbar(self, orientation="horizontal", command=self.canvas.xview)
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

    def set_zoom(self, scale_level):
        # scale_level comes from a float slider now
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
            # Reset zoom to 1.0, but don't force the slider reset to avoid jarring UI loops if unnecessary
            # or maybe we should? Let's reset it to be safe.
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
        self.grid_rowconfigure(1, weight=1) # Content row

        self.is_expanded = False

        self.title_button = ctk.CTkButton(
            self,
            text=f"+ {title}",
            command=self.toggle,
            anchor="w",
            fg_color="transparent",
            text_color="#00bfa5", # Teal accent
            hover_color=("#3a3a3a", "#3a3a3a"),
            font=ctk.CTkFont(weight="bold")
        )
        self.title_button.grid(row=0, column=0, sticky="ew", padx=0, pady=0)

        self.content_frame = ctk.CTkFrame(self, fg_color="transparent")
        # Start collapsed

        self.title_text = title

    def toggle(self):
        if self.is_expanded:
            self.content_frame.grid_forget()
            self.title_button.configure(text=f"+ {self.title_text}")
            self.is_expanded = False
        else:
            self.content_frame.grid(row=1, column=0, sticky="ew", padx=5, pady=5)
            self.title_button.configure(text=f"− {self.title_text}")
            self.is_expanded = True

    def get_content_frame(self):
        return self.content_frame


class TkinterDnD_CTk(ctk.CTk, TkinterDnD.DnDWrapper):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.TkdndVersion = TkinterDnD._require(self)


class MoviePrintApp(TkinterDnD_CTk):
    def __init__(self):
        super().__init__()
        self.title(f"MoviePrint Generator v{__version__}")
        self.geometry("1400x900")

        self.scrubbing_handler = ScrubbingHandler(self)

        # Variables
        self._internal_input_paths = []
        self.thumbnail_images = []
        self.thumbnail_paths = []
        self.thumbnail_layout_data = []
        self.thumbnail_metadata = []
        self.queue = queue.Queue()
        self.preview_temp_dir = None

        # Settings Variables (mapped to CTk widgets)
        self._init_variables()
        self._load_persistent_settings()

        # Layout
        self.grid_columnconfigure(0, weight=4) # Preview Canvas
        self.grid_columnconfigure(1, weight=1) # Control Deck (Sidebar)
        self.grid_rowconfigure(0, weight=0) # Top Bar
        self.grid_rowconfigure(1, weight=1) # Main Content

        # 1. Top Bar
        self._create_top_bar()

        # 2. Preview Area
        self._create_preview_area()

        # 3. Control Deck (Sidebar)
        self._create_sidebar()

        # 4. Log / Progress (Bottom Overlay or Integrated?)
        # Let's integrate a small status bar or use the console for now,
        # but the plan said "Action Log Section".
        # I'll put a log text box at the bottom of the Sidebar or below the preview.
        # Given the layout, below the preview makes sense.
        self._create_log_section()

        self.update_options_visibility()
        self.after(100, self.check_queue)
        self.protocol("WM_DELETE_WINDOW", self._on_closing)

    def _init_variables(self):
        self.default_settings = {
             "input_paths_var": "",
             "output_dir_var": "",
             "num_columns_var": "3",
             "num_rows_var": "3",
             # ... other defaults ...
             "extraction_mode_var": "interval",
             "interval_seconds_var": "5.0",
             "shot_threshold_var": "27.0",
             "layout_mode_var": "grid",
             "padding_var": "5",
             "background_color_var": "#1e1e1e",
             "preview_quality_var": 75,
             "max_frames_for_print_var": "100",
        }

        # Initialize vars
        self.input_paths_var = ctk.StringVar()
        self.output_dir_var = ctk.StringVar()

        self.num_columns_var = ctk.IntVar(value=3)
        self.num_rows_var = ctk.IntVar(value=3)
        self.num_columns_var.trace_add("write", self._update_equation)
        self.num_rows_var.trace_add("write", self._update_equation)

        self.layout_mode_var = ctk.StringVar(value="grid")
        self.extraction_mode_var = ctk.StringVar(value="interval")
        self.interval_seconds_var = ctk.StringVar(value="5.0")
        self.interval_frames_var = ctk.StringVar(value="")
        self.shot_threshold_var = ctk.StringVar(value="27.0")
        self.exclude_frames_var = ctk.StringVar(value="")
        self.exclude_shots_var = ctk.StringVar(value="")

        self.padding_var = ctk.StringVar(value="5")
        self.background_color_var = ctk.StringVar(value="#1e1e1e")
        self.frame_format_var = ctk.StringVar(value="jpg")
        self.save_metadata_json_var = ctk.BooleanVar(value=True)
        self.detect_faces_var = ctk.BooleanVar(value=False)
        self.rotate_thumbnails_var = ctk.IntVar(value=0)

        self.start_time_var = ctk.StringVar(value="")
        self.end_time_var = ctk.StringVar(value="")
        self.output_filename_suffix_var = ctk.StringVar(value="_movieprint")
        self.output_filename_var = ctk.StringVar(value="")
        self.video_extensions_var = ctk.StringVar(value=".mp4,.avi,.mov,.mkv,.flv,.wmv")
        self.recursive_scan_var = ctk.BooleanVar(value=False)
        self.temp_dir_var = ctk.StringVar(value="")
        self.haar_cascade_xml_var = ctk.StringVar(value="")
        self.max_frames_for_print_var = ctk.StringVar(value="100")

        self.target_thumbnail_width_var = ctk.StringVar(value="")
        self.target_thumbnail_height_var = ctk.StringVar(value="")
        self.output_width_var = ctk.StringVar(value="")
        self.output_height_var = ctk.StringVar(value="")
        self.target_row_height_var = ctk.StringVar(value="150")
        self.output_image_width_var = ctk.StringVar(value="1920")

        self.max_output_filesize_kb_var = ctk.StringVar(value="")
        self.preview_quality_var = ctk.IntVar(value=75)
        self.zoom_level_var = ctk.DoubleVar(value=1.0)

        self.grid_margin_var = ctk.StringVar(value="0")
        self.show_header_var = ctk.BooleanVar(value=True)
        self.show_file_path_var = ctk.BooleanVar(value=True)
        self.show_timecode_var = ctk.BooleanVar(value=True)
        self.show_frame_num_var = ctk.BooleanVar(value=True)
        self.rounded_corners_var = ctk.StringVar(value="0")

        self.frame_info_show_var = ctk.BooleanVar(value=True)
        self.frame_info_timecode_or_frame_var = ctk.StringVar(value="timecode")
        self.frame_info_font_color_var = ctk.StringVar(value="#FFFFFF")
        self.frame_info_bg_color_var = ctk.StringVar(value="#000000")
        self.frame_info_position_var = ctk.StringVar(value="bottom_left")
        self.frame_info_size_var = ctk.StringVar(value="10")
        self.frame_info_margin_var = ctk.StringVar(value="5")

    def _create_top_bar(self):
        self.top_bar = ctk.CTkFrame(self, corner_radius=0, fg_color="#1a1a1a")
        self.top_bar.grid(row=0, column=0, columnspan=2, sticky="ew", padx=0, pady=0)

        # Input
        self.btn_browse_input = ctk.CTkButton(self.top_bar, text="+ Add Movie / Folder",
                                              command=self.browse_input_paths,
                                              width=150, height=32, corner_radius=6)
        self.btn_browse_input.pack(side="left", padx=15, pady=10)

        self.lbl_input_path = ctk.CTkLabel(self.top_bar, textvariable=self.input_paths_var,
                                           text_color="gray", anchor="w")
        self.lbl_input_path.pack(side="left", padx=10, pady=10, fill="x", expand=True)

        # Output
        self.btn_browse_output = ctk.CTkButton(self.top_bar, text="Set Output Dir",
                                               command=self.browse_output_dir,
                                               fg_color="transparent", border_width=1, text_color="gray")
        self.btn_browse_output.pack(side="right", padx=15, pady=10)

        # Register DnD
        self.drop_target_register(DND_FILES)
        self.dnd_bind('<<Drop>>', self.handle_drop)

    def _create_preview_area(self):
        # Frame for canvas + zoom slider below
        self.preview_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.preview_frame.grid(row=1, column=0, sticky="nsew", padx=10, pady=10)

        self.preview_frame.grid_rowconfigure(0, weight=1)
        self.preview_frame.grid_columnconfigure(0, weight=1)

        self.preview_zoomable_canvas = ZoomableCanvas(self.preview_frame, app_ref=self)
        self.preview_zoomable_canvas.grid(row=0, column=0, sticky="nsew")

        # Bottom strip in preview area for zoom and log
        self.preview_controls = ctk.CTkFrame(self.preview_frame, fg_color="transparent")
        self.preview_controls.grid(row=1, column=0, sticky="ew", pady=(5,0))

        self.zoom_slider = ctk.CTkSlider(self.preview_controls, from_=0.1, to=5.0,
                                         variable=self.zoom_level_var, command=self.preview_zoomable_canvas.set_zoom)
        self.zoom_slider.pack(side="left", fill="x", expand=True, padx=10)
        Tooltip(self.zoom_slider, "Preview Zoom")

    def _create_log_section(self):
        # Use a CTkTextbox for logs, positioned below the preview
        self.log_frame = ctk.CTkFrame(self.preview_frame, height=100, fg_color="transparent")
        self.log_frame.grid(row=2, column=0, sticky="ew", pady=(5,0))

        self.log_text = ctk.CTkTextbox(self.log_frame, height=80, activate_scrollbars=True, state="disabled")
        self.log_text.pack(fill="both", expand=True)

        self.progress_bar = ctk.CTkProgressBar(self.log_frame, orientation="horizontal")
        self.progress_bar.set(0)
        self.progress_bar.pack(fill="x", pady=(5,0))

    def _create_sidebar(self):
        self.sidebar = ctk.CTkScrollbar(self) # Actually, let's use a frame inside a scrollable frame
        # ctk.CTkScrollableFrame is better
        self.sidebar_frame = ctk.CTkScrollableFrame(self, width=350, corner_radius=0, fg_color="#222222")
        self.sidebar_frame.grid(row=1, column=1, sticky="nsew")

        # --- The Equation ---
        self.equation_label = ctk.CTkLabel(self.sidebar_frame, text="3 COLUMNS × 3 ROWS = 9 COUNT",
                                           font=("Arial", 14, "bold"), text_color="#FFFFFF")
        self.equation_label.pack(pady=(20, 10), padx=10)

        # --- Sliders ---
        self.slider_frame = ctk.CTkFrame(self.sidebar_frame, fg_color="transparent")
        self.slider_frame.pack(fill="x", padx=10, pady=10)

        ctk.CTkLabel(self.slider_frame, text="Columns").pack(anchor="w")
        self.col_slider = ctk.CTkSlider(self.slider_frame, from_=1, to=20, number_of_steps=19, variable=self.num_columns_var)
        self.col_slider.pack(fill="x", pady=(0, 10))

        ctk.CTkLabel(self.slider_frame, text="Rows").pack(anchor="w")
        self.row_slider = ctk.CTkSlider(self.slider_frame, from_=1, to=20, number_of_steps=19, variable=self.num_rows_var)
        self.row_slider.pack(fill="x", pady=(0, 10))

        # --- Apply Button ---
        self.btn_apply = ctk.CTkButton(self.sidebar_frame, text="APPLY / UPDATE PREVIEW",
                                       command=self.start_thumbnail_preview_generation,
                                       fg_color="#333333", hover_color="#444444")
        self.btn_apply.pack(fill="x", padx=10, pady=10)

        # --- Accordion Menus ---

        # 1. Extraction & Layout
        self.grp_extraction = CTkCollapsibleFrame(self.sidebar_frame, title="Extraction & Layout")
        self.grp_extraction.pack(fill="x", padx=5, pady=2)
        self._populate_extraction_settings(self.grp_extraction.get_content_frame())

        # 2. Appearance & Styling
        self.grp_styling = CTkCollapsibleFrame(self.sidebar_frame, title="Styling")
        self.grp_styling.pack(fill="x", padx=5, pady=2)
        self._populate_appearance_settings(self.grp_styling.get_content_frame())

        # 3. Output & Advanced
        self.grp_output = CTkCollapsibleFrame(self.sidebar_frame, title="Output & Advanced")
        self.grp_output.pack(fill="x", padx=5, pady=2)
        self._populate_output_settings(self.grp_output.get_content_frame())

        # --- Spacer ---
        ctk.CTkFrame(self.sidebar_frame, height=20, fg_color="transparent").pack()

        # --- Save Button (Orange) ---
        self.btn_save = ctk.CTkButton(self.sidebar_frame, text="SAVE MOVIEPRINT",
                                      command=self.generate_movieprint_action,
                                      height=50, font=("Arial", 16, "bold"),
                                      fg_color="#D35400", hover_color="#E67E22") # Orange
        self.btn_save.pack(fill="x", padx=10, pady=20, side="bottom")

    def _update_equation(self, *args):
        try:
            c = self.num_columns_var.get()
            r = self.num_rows_var.get()
            count = c * r
            self.equation_label.configure(text=f"{c} COLUMNS × {r} ROWS = {count} COUNT")
        except:
            pass

    def _populate_extraction_settings(self, parent):
        # Helper for grid layout inside frame
        def add_row(row, label_text, widget):
            ctk.CTkLabel(parent, text=label_text, anchor="w").grid(row=row, column=0, sticky="w", padx=5, pady=2)
            widget.grid(row=row, column=1, sticky="ew", padx=5, pady=2)

        parent.columnconfigure(1, weight=1)

        self.combo_ext_mode = ctk.CTkComboBox(parent, variable=self.extraction_mode_var, values=["interval", "shot"], command=self.update_options_visibility)
        add_row(0, "Mode:", self.combo_ext_mode)

        # Interval options
        self.fr_interval = ctk.CTkFrame(parent, fg_color="transparent")
        self.fr_interval.grid(row=1, column=0, columnspan=2, sticky="ew")
        self.fr_interval.columnconfigure(1, weight=1)
        ctk.CTkLabel(self.fr_interval, text="Interval (sec):").grid(row=0, column=0, padx=5)
        ctk.CTkEntry(self.fr_interval, textvariable=self.interval_seconds_var, width=60).grid(row=0, column=1, sticky="w")

        # Start/End Time
        ctk.CTkLabel(parent, text="Time Range (Start - End):").grid(row=3, column=0, columnspan=2, sticky="w", padx=5)
        time_row = ctk.CTkFrame(parent, fg_color="transparent")
        time_row.grid(row=4, column=0, columnspan=2, sticky="ew")
        ctk.CTkEntry(time_row, textvariable=self.start_time_var, placeholder_text="Start", width=80).pack(side="left", padx=5)
        ctk.CTkEntry(time_row, textvariable=self.end_time_var, placeholder_text="End", width=80).pack(side="left", padx=5)

        # Max Frames
        add_row(5, "Max Frames:", ctk.CTkEntry(parent, textvariable=self.max_frames_for_print_var))

    def _populate_appearance_settings(self, parent):
        def add_row(row, label_text, widget):
            ctk.CTkLabel(parent, text=label_text, anchor="w").grid(row=row, column=0, sticky="w", padx=5, pady=2)
            widget.grid(row=row, column=1, sticky="ew", padx=5, pady=2)
        parent.columnconfigure(1, weight=1)

        add_row(0, "Target Width (px):", ctk.CTkEntry(parent, textvariable=self.target_thumbnail_width_var))
        add_row(1, "Padding (px):", ctk.CTkEntry(parent, textvariable=self.padding_var))
        add_row(2, "Bg Color:", ctk.CTkEntry(parent, textvariable=self.background_color_var))

        self.chk_header = ctk.CTkCheckBox(parent, text="Show Header", variable=self.show_header_var)
        self.chk_header.grid(row=3, column=0, columnspan=2, sticky="w", padx=5, pady=5)

        self.chk_info = ctk.CTkCheckBox(parent, text="Show Frame Info", variable=self.frame_info_show_var)
        self.chk_info.grid(row=4, column=0, columnspan=2, sticky="w", padx=5, pady=5)

    def _populate_output_settings(self, parent):
        parent.columnconfigure(0, weight=1)

        ctk.CTkLabel(parent, text="Filename Suffix:", anchor="w").pack(fill="x", padx=5)
        ctk.CTkEntry(parent, textvariable=self.output_filename_suffix_var).pack(fill="x", padx=5, pady=2)

        ctk.CTkCheckBox(parent, text="Recursive Scan", variable=self.recursive_scan_var).pack(anchor="w", padx=5, pady=5)
        ctk.CTkCheckBox(parent, text="Detect Faces", variable=self.detect_faces_var).pack(anchor="w", padx=5, pady=5)

        ctk.CTkButton(parent, text="Reset All Settings", command=self.perform_reset_all_settings, fg_color="transparent", border_width=1).pack(fill="x", padx=5, pady=10)

    # --- Logic Methods (Copied/Adapted from Legacy) ---

    def _load_persistent_settings(self):
        try:
            if os.path.exists(SETTINGS_FILE):
                with open(SETTINGS_FILE, 'r') as f:
                    settings = json.load(f)
                    # Map settings carefully
                    if settings.get("input_paths"):
                        self.input_paths_var.set(settings.get("input_paths"))
                        p = settings.get("input_paths")
                        if ";" in p: self._internal_input_paths = [x.strip() for x in p.split(';') if x.strip()]
                        else: self._internal_input_paths = [p]

                    self.output_dir_var.set(settings.get("output_dir", ""))
                    self.num_columns_var.set(int(settings.get("num_columns", 3)))
                    self.num_rows_var.set(int(settings.get("num_rows", 3)))
                    self.padding_var.set(settings.get("padding", "5"))
                    self.background_color_var.set(settings.get("background_color", "#1e1e1e"))
                    self.interval_seconds_var.set(settings.get("interval_seconds", "5.0"))
                    self.max_frames_for_print_var.set(settings.get("max_frames_for_print", "100"))
        except Exception as e:
            print(f"Error loading settings: {e}")

    def _save_persistent_settings(self):
        settings = {
            "input_paths": self.input_paths_var.get(),
            "output_dir": self.output_dir_var.get(),
            "num_columns": self.num_columns_var.get(),
            "num_rows": self.num_rows_var.get(),
            "padding": self.padding_var.get(),
            "background_color": self.background_color_var.get(),
            "interval_seconds": self.interval_seconds_var.get(),
            "max_frames_for_print": self.max_frames_for_print_var.get()
        }
        try:
            with open(SETTINGS_FILE, 'w') as f:
                json.dump(settings, f, indent=4)
        except Exception as e:
            print(f"Error saving settings: {e}")

    def _on_closing(self):
        self._save_persistent_settings()
        if self.preview_temp_dir and os.path.exists(self.preview_temp_dir):
            shutil.rmtree(self.preview_temp_dir, ignore_errors=True)
        self.destroy()

    def handle_drop(self, event):
        data_string = event.data
        # Simple parsing for now
        paths = []
        if data_string.startswith('{'):
             paths = [p.strip('{}') for p in data_string.split('} {')]
        else:
             paths = data_string.split()

        valid_paths = [p for p in paths if os.path.exists(p)]
        if valid_paths:
            if os.path.isdir(valid_paths[0]):
                self._internal_input_paths = [valid_paths[0]]
                self.input_paths_var.set(valid_paths[0])
            else:
                self._internal_input_paths = valid_paths
                self.input_paths_var.set("; ".join(valid_paths))

            self.log_message(f"Dropped: {self._internal_input_paths}")

            # Auto-calc
            if len(self._internal_input_paths) == 1 and os.path.isfile(self._internal_input_paths[0]):
                threading.Thread(target=self._auto_calculate_and_set_interval, args=(self._internal_input_paths[0],), daemon=True).start()

    def browse_input_paths(self):
        filepaths = filedialog.askopenfilenames(title="Select Videos")
        if filepaths:
            self._internal_input_paths = list(filepaths)
            self.input_paths_var.set("; ".join(filepaths))
            if len(filepaths) == 1:
                 threading.Thread(target=self._auto_calculate_and_set_interval, args=(filepaths[0],), daemon=True).start()

    def browse_output_dir(self):
        d = filedialog.askdirectory(title="Select Output Dir")
        if d: self.output_dir_var.set(d)

    def _auto_calculate_and_set_interval(self, video_path):
        # Simplified logic from legacy
        try:
            cap = cv2.VideoCapture(video_path)
            if cap.isOpened():
                fps = cap.get(cv2.CAP_PROP_FPS)
                count = cap.get(cv2.CAP_PROP_FRAME_COUNT)
                duration = count/fps if fps > 0 else 0
                cap.release()

                target_frames = int(self.max_frames_for_print_var.get() or 60)
                if duration > 0 and target_frames > 0:
                    interval = max(0.1, duration / target_frames)
                    self.interval_seconds_var.set(f"{interval:.2f}")
                    self.queue.put(("log", f"Auto-interval: {interval:.2f}s"))
        except Exception as e:
            self.queue.put(("log", f"Auto-calc error: {e}"))

    def log_message(self, msg):
        self.log_text.configure(state="normal")
        self.log_text.insert("end", msg + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def check_queue(self):
        try:
            while True:
                msg_type, data = self.queue.get_nowait()
                if msg_type == "log":
                    self.log_message(data)
                elif msg_type == "progress":
                    curr, total, _ = data
                    if total > 0: self.progress_bar.set(curr/total)
                elif msg_type == "preview_grid":
                    self._display_thumbnail_preview(data)
                elif msg_type == "state":
                    if data == "disable_button": self.btn_save.configure(state="disabled")
                    elif data == "enable_button": self.btn_save.configure(state="normal")
        except queue.Empty:
            pass
        self.after(100, self.check_queue)

    def update_options_visibility(self, *args):
        # Placeholder for now
        pass

    def perform_reset_all_settings(self):
        self._init_variables()
        self.log_message("Settings reset.")

    # --- Generation Linking ---

    def start_thumbnail_preview_generation(self):
        self.log_message("Starting preview...")
        if not self._internal_input_paths:
            messagebox.showerror("Error", "No input selected")
            return

        import tempfile
        if self.preview_temp_dir and os.path.exists(self.preview_temp_dir):
            shutil.rmtree(self.preview_temp_dir, ignore_errors=True)
        self.preview_temp_dir = tempfile.mkdtemp(prefix="movieprint_preview_")

        threading.Thread(target=self._thumbnail_preview_thread, args=(self._internal_input_paths[0],), daemon=True).start()

    def _thumbnail_preview_thread(self, video_path):
        # Re-implement logic calling video_processing directly or reusing legacy logic?
        # I should ideally replicate the logic to ensure compatibility with my new vars
        # But for speed, I'll adapt the legacy logic here.

        thread_logger = logging.getLogger(f"prev_{threading.get_ident()}")
        thread_logger.addHandler(QueueHandler(self.queue))
        thread_logger.setLevel(logging.INFO)
        
        try:
            # Extraction
            interval = float(self.interval_seconds_var.get())
            success, meta_list = video_processing.extract_frames(
                video_path=video_path,
                output_folder=self.preview_temp_dir,
                logger=thread_logger,
                interval_seconds=interval,
                output_format="jpg"
            )
            
            if success:
                # Grid Generation
                import image_grid
                grid_path = os.path.join(self.preview_temp_dir, "preview.jpg")

                # Override columns/rows based on sliders
                cols = self.num_columns_var.get()
                rows = self.num_rows_var.get()

                # We need to limit meta_list to cols*rows
                limit = cols * rows
                if len(meta_list) > limit:
                    # Sample it down uniformly
                    indices = [int(i * (len(meta_list) - 1) / (limit - 1)) for i in range(limit)]
                    meta_list = [meta_list[i] for i in indices]

                grid_success, layout = image_grid.create_image_grid(
                    image_source_data=[m['frame_path'] for m in meta_list],
                    output_path=grid_path,
                    columns=cols,
                    rows=rows, # Force rows if needed, or just pass cols
                    padding=int(self.padding_var.get()),
                    background_color_hex=self.background_color_var.get(),
                    logger=thread_logger
                )

                if grid_success:
                    self.thumbnail_layout_data = layout
                    self.thumbnail_metadata = meta_list
                    self.queue.put(("preview_grid", {"grid_path": grid_path, "temp_dir": self.preview_temp_dir}))
        except Exception as e:
            thread_logger.error(f"Preview failed: {e}")

    def _display_thumbnail_preview(self, data):
        path = data["grid_path"]
        self.preview_zoomable_canvas.set_image(path)

    def generate_movieprint_action(self):
        self.log_message("Saving MoviePrint...")
        # Construct settings namespace
        settings = argparse.Namespace()
        settings.input_paths = self._internal_input_paths
        settings.output_dir = self.output_dir_var.get() or os.getcwd()
        settings.extraction_mode = self.extraction_mode_var.get()
        settings.layout_mode = "grid" # Forcing grid for now based on new UI
        settings.interval_seconds = float(self.interval_seconds_var.get())
        settings.columns = self.num_columns_var.get()
        settings.rows = self.num_rows_var.get()
        settings.padding = int(self.padding_var.get())
        settings.background_color = self.background_color_var.get()
        settings.frame_format = "jpg"
        settings.save_metadata_json = True
        settings.detect_faces = False
        settings.video_extensions = ".mp4,.avi,.mov"
        settings.recursive_scan = self.recursive_scan_var.get()
        settings.output_filename = None
        settings.output_filename_suffix = self.output_filename_suffix_var.get()

        # Defaults for fields I didn't explicitly re-map in this simplified code
        settings.shot_threshold = 27.0
        settings.interval_frames = None
        settings.exclude_frames = None
        settings.exclude_shots = None
        settings.target_row_height = 150
        settings.output_image_width = 1920
        settings.max_frames_for_print = int(self.max_frames_for_print_var.get())
        settings.target_thumbnail_width = None
        settings.output_width = None
        settings.output_height = None
        settings.target_thumbnail_height = None
        settings.rotate_thumbnails = 0
        settings.start_time = None
        settings.end_time = None
        settings.temp_dir = None
        settings.haar_cascade_xml = None
        settings.grid_margin = 0
        settings.show_header = self.show_header_var.get()
        settings.show_file_path = True
        settings.show_timecode = True
        settings.show_frame_num = True
        settings.rounded_corners = 0
        settings.frame_info_show = False
        settings.max_output_filesize_kb = None
        settings.frame_info_timecode_or_frame = "timecode"
        settings.frame_info_font_color = "#FFFFFF"
        settings.frame_info_bg_color = "#000000"
        settings.frame_info_position = "bottom_left"
        settings.frame_info_size = 10
        settings.frame_info_margin = 5


        self.queue.put(("state", "disable_button"))

        def run():
            thread_logger = logging.getLogger(f"gen_{threading.get_ident()}")
            thread_logger.addHandler(QueueHandler(self.queue))
            thread_logger.setLevel(logging.INFO)
            try:
                execute_movieprint_generation(settings, thread_logger, lambda c,t,f: self.queue.put(("progress", (c,t,f))))
            except Exception as e:
                thread_logger.error(f"Generation failed: {e}")
            finally:
                self.queue.put(("state", "enable_button"))

        threading.Thread(target=run, daemon=True).start()

    # Scrubbing stubs
    def is_scrubbing_active(self): return self.scrubbing_handler.active
    def start_scrubbing(self, event): return False # TODO: Implement hit detection logic using layout data
    def handle_scrubbing(self, event): pass
    def stop_scrubbing(self, event): pass


if __name__ == "__main__":
    app = MoviePrintApp()
    app.mainloop()
