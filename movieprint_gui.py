import tkinter as tk
import logging
from tkinter import ttk, filedialog, scrolledtext, messagebox, colorchooser
import os
import argparse
import threading
import queue
import cv2
import json # << NEW IMPORT for saving/loading settings
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

SETTINGS_FILE = "movieprint_gui_settings.json" # << NEW: Settings file name

# ... (QueueHandler and Tooltip classes remain the same) ...
class QueueHandler(logging.Handler):
    def __init__(self, queue_instance):
        super().__init__()
        self.queue = queue_instance

    def emit(self, record):
        log_entry = self.format(record)
        self.queue.put(("log", log_entry))

class Tooltip:
    """
    Simple tooltip class for Tkinter widgets.
    """
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
        label = tk.Label(self.tooltip_window, text=self.text, justify='left',
                         background="#ffffe0", relief='solid', borderwidth=1,
                         font=("tahoma", "8", "normal"), wraplength=300)
        label.pack(ipadx=2, ipady=2)

    def hide_tooltip(self, event=None):
        if self.tooltip_window:
            self.tooltip_window.destroy()
        self.tooltip_window = None


class MoviePrintApp:
    def __init__(self):
        self.root = TkinterDnD.Tk()
        self.root.title(f"MoviePrint Generator v{__version__}")
        self.root.geometry("780x950")

        self._internal_input_paths = [] # Initialize for drag-and-drop and settings load
        self.thumbnail_images = [] # To store PhotoImage objects for preview

        # --- Define Default Settings Store ---
        self.default_settings = {
            "input_paths_var": "",
            "output_dir_var": "",
            "extraction_mode_var": "interval",
            "interval_seconds_var": "5.0",
            "interval_frames_var": "",
            "shot_threshold_var": "27.0",
            "exclude_frames_var": "",
            "exclude_shots_var": "",
            "layout_mode_var": "grid",
            "num_columns_var": "5",
            "num_rows_var": "",
            "target_row_height_var": "150", # Used in timeline
            "output_image_width_var": "1920", # Used in timeline
            "padding_var": "5",
            "background_color_var": "#FFFFFF",
            "frame_format_var": "jpg",
            "save_metadata_json_var": True,
            "detect_faces_var": False,
            "rotate_thumbnails_var": 0,
            "start_time_var": "",
            "end_time_var": "",
            "output_filename_suffix_var": "_movieprint",
            "output_filename_var": "",
            "video_extensions_var": ".mp4,.avi,.mov,.mkv,.flv,.wmv",
            "recursive_scan_var": False,
            "temp_dir_var": "",
            "haar_cascade_xml_var": "",
            "max_frames_for_print_var": "100",
            "target_thumbnail_width_var": "",
            "max_output_filesize_kb_var": ""
        }

        # --- Initialize Tk Variables using default_settings ---
        self.input_paths_var = tk.StringVar(value=self.default_settings["input_paths_var"])
        self.output_dir_var = tk.StringVar(value=self.default_settings["output_dir_var"])
        self.extraction_mode_var = tk.StringVar(value=self.default_settings["extraction_mode_var"])
        self.interval_seconds_var = tk.StringVar(value=self.default_settings["interval_seconds_var"])
        self.interval_frames_var = tk.StringVar(value=self.default_settings["interval_frames_var"])
        self.shot_threshold_var = tk.StringVar(value=self.default_settings["shot_threshold_var"])
        self.exclude_frames_var = tk.StringVar(value=self.default_settings["exclude_frames_var"])
        self.exclude_shots_var = tk.StringVar(value=self.default_settings["exclude_shots_var"])
        self.layout_mode_var = tk.StringVar(value=self.default_settings["layout_mode_var"])
        self.num_columns_var = tk.StringVar(value=self.default_settings["num_columns_var"])
        self.num_rows_var = tk.StringVar(value=self.default_settings["num_rows_var"])
        self.target_row_height_var = tk.StringVar(value=self.default_settings["target_row_height_var"])
        self.output_image_width_var = tk.StringVar(value=self.default_settings["output_image_width_var"])
        self.padding_var = tk.StringVar(value=self.default_settings["padding_var"])
        self.background_color_var = tk.StringVar(value=self.default_settings["background_color_var"])
        self.frame_format_var = tk.StringVar(value=self.default_settings["frame_format_var"])
        self.save_metadata_json_var = tk.BooleanVar(value=self.default_settings["save_metadata_json_var"])
        self.detect_faces_var = tk.BooleanVar(value=self.default_settings["detect_faces_var"])
        self.rotate_thumbnails_var = tk.IntVar(value=self.default_settings["rotate_thumbnails_var"])
        self.start_time_var = tk.StringVar(value=self.default_settings["start_time_var"])
        self.end_time_var = tk.StringVar(value=self.default_settings["end_time_var"])
        self.output_filename_suffix_var = tk.StringVar(value=self.default_settings["output_filename_suffix_var"])
        self.output_filename_var = tk.StringVar(value=self.default_settings["output_filename_var"])
        self.video_extensions_var = tk.StringVar(value=self.default_settings["video_extensions_var"])
        self.recursive_scan_var = tk.BooleanVar(value=self.default_settings["recursive_scan_var"])
        self.temp_dir_var = tk.StringVar(value=self.default_settings["temp_dir_var"])
        self.haar_cascade_xml_var = tk.StringVar(value=self.default_settings["haar_cascade_xml_var"])
        self.max_frames_for_print_var = tk.StringVar(value=self.default_settings["max_frames_for_print_var"])
        self.max_frames_for_print_var.trace_add("write", self._handle_max_frames_change)
        self.target_thumbnail_width_var = tk.StringVar(value=self.default_settings["target_thumbnail_width_var"])
        self.max_output_filesize_kb_var = tk.StringVar(value=self.default_settings["max_output_filesize_kb_var"])

        # --- Load persistent settings (will override defaults if settings file exists) ---
        self._load_persistent_settings()

        self.queue = queue.Queue()
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.pack(expand=True, fill=tk.BOTH)

        self._create_input_output_section(main_frame)
        self._create_tabs_section(main_frame)
        self._create_action_log_section(main_frame)

        self.update_options_visibility()
        self.root.after(100, self.check_queue)

        # --- Save persistent settings on close ---
        self.root.protocol("WM_DELETE_WINDOW", self._on_closing) # << NEW CALL

    # --- NEW METHODS for Persistent Settings ---
    def _load_persistent_settings(self):
        try:
            if os.path.exists(SETTINGS_FILE):
                with open(SETTINGS_FILE, 'r') as f:
                    settings = json.load(f)
                    self.input_paths_var.set(settings.get("input_paths", ""))
                    # If input_paths_var is set, also try to reconstruct _internal_input_paths
                    if self.input_paths_var.get():
                        paths_str = self.input_paths_var.get()
                        if ";" in paths_str: # Likely multiple files
                            self._internal_input_paths = [p.strip() for p in paths_str.split(';') if p.strip()]
                        elif paths_str: # Single file or directory
                            self._internal_input_paths = [paths_str.strip()]


                    self.output_dir_var.set(settings.get("output_dir", ""))
                    self.temp_dir_var.set(settings.get("custom_temp_dir", ""))
                    # Load other StringVars if you want them to be persistent
                    self.max_frames_for_print_var.set(settings.get("max_frames_for_print", "100"))
                    self.num_columns_var.set(settings.get("num_columns", "5"))
                    self.num_rows_var.set(settings.get("num_rows", ""))
                    self.target_thumbnail_width_var.set(settings.get("target_thumbnail_width", "")) # Or "320"
                    self.interval_seconds_var.set(settings.get("interval_seconds", "5.0"))
                    self.max_output_filesize_kb_var.set(settings.get("max_output_filesize_kb", ""))
                    # Load commonly adjusted layout and operational settings (with defaults)
                    self.layout_mode_var.set(settings.get("layout_mode", "grid"))
                    self.padding_var.set(settings.get("padding", "5"))
                    self.background_color_var.set(settings.get("background_color", "#FFFFFF"))
                    self.extraction_mode_var.set(settings.get("extraction_mode", "interval"))
                    # ... and so on for any other settings you want to persist ...
        except Exception as e:
            print(f"Error loading persistent settings: {e}") # Or log to GUI queue if possible early

    def _save_persistent_settings(self):
        settings_to_save = {
            "input_paths": self.input_paths_var.get(),
            "output_dir": self.output_dir_var.get(),
            "custom_temp_dir": self.temp_dir_var.get(),
            "max_frames_for_print": self.max_frames_for_print_var.get(),
            "num_columns": self.num_columns_var.get(),
            "num_rows": self.num_rows_var.get(),
            "target_thumbnail_width": self.target_thumbnail_width_var.get(),
            "interval_seconds": self.interval_seconds_var.get(),
            "max_output_filesize_kb": self.max_output_filesize_kb_var.get(),
            # Save commonly adjusted layout and operational settings
            "layout_mode": self.layout_mode_var.get(),
            "padding": self.padding_var.get(),
            "background_color": self.background_color_var.get(),
            "extraction_mode": self.extraction_mode_var.get(),
            # ... add any other settings from StringVars ...
        }
        try:
            with open(SETTINGS_FILE, 'w') as f:
                json.dump(settings_to_save, f, indent=4)
        except Exception as e:
            # Can't use GUI log here easily if app is closing
            print(f"Error saving persistent settings: {e}")

    def _on_closing(self):
        self._save_persistent_settings()
        self.root.destroy()

    def _handle_max_frames_change(self, *args):
        # Check if a single video file is selected
        if hasattr(self, '_internal_input_paths') and \
           len(self._internal_input_paths) == 1 and \
           os.path.isfile(self._internal_input_paths[0]):
            self.queue.put(("log", f"Max frames changed. Recalculating interval for {os.path.basename(self._internal_input_paths[0])}..."))
            self._auto_calculate_and_set_interval(self._internal_input_paths[0])
    # --- END NEW METHODS ---

    # ... (rest of the _create_... and helper methods as before) ...
    def _create_input_output_section(self, parent_frame):
        input_section = ttk.LabelFrame(parent_frame, text="Input / Output", padding="10")
        input_section.pack(fill=tk.X, padx=5, pady=5)
        input_section.columnconfigure(1, weight=1)
        lbl_input = ttk.Label(input_section, text="Video File(s) / Dir:")
        lbl_input.grid(row=0, column=0, sticky=tk.W, padx=5, pady=5)
        Tooltip(lbl_input, "Select one or more video files, or a single directory containing videos.")
        self.input_paths_entry = ttk.Entry(input_section, textvariable=self.input_paths_var, state="readonly", width=60)
        self.input_paths_entry.grid(row=0, column=1, sticky=tk.EW, padx=5, pady=5)
        self.input_paths_entry.drop_target_register(DND_FILES)
        self.input_paths_entry.dnd_bind('<<Drop>>', self.handle_drop)
        btn_browse_input = ttk.Button(input_section, text="Browse...", command=self.browse_input_paths)
        btn_browse_input.grid(row=0, column=2, padx=5, pady=5)
        Tooltip(btn_browse_input, "Browse for video files or a directory. You can also drag & drop files/folders onto the input field.")
        lbl_output_dir = ttk.Label(input_section, text="Output Directory:")
        lbl_output_dir.grid(row=1, column=0, sticky=tk.W, padx=5, pady=5)
        Tooltip(lbl_output_dir, "Directory where MoviePrints will be saved.")
        self.output_dir_entry = ttk.Entry(input_section, textvariable=self.output_dir_var, state="readonly", width=60)
        self.output_dir_entry.grid(row=1, column=1, sticky=tk.EW, padx=5, pady=5)
        btn_browse_output = ttk.Button(input_section, text="Browse...", command=self.browse_output_dir)
        btn_browse_output.grid(row=1, column=2, padx=5, pady=5)
        Tooltip(btn_browse_output, "Browse for the output directory.")

    def _create_tabs_section(self, parent_frame):
        notebook = ttk.Notebook(parent_frame, padding="5")
        notebook.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        tab_extraction = ttk.Frame(notebook, padding="5")
        tab_layout = ttk.Frame(notebook, padding="5")
        tab_batch_output = ttk.Frame(notebook, padding="5")
        tab_common = ttk.Frame(notebook, padding="5")
        self.tab_preview = ttk.Frame(notebook, padding="5") # New Preview Tab

        notebook.add(tab_extraction, text='Extraction & Segment')
        notebook.add(tab_layout, text='Layout')
        notebook.add(self.tab_preview, text='Thumbnail Preview') # Add to notebook
        notebook.add(tab_batch_output, text='Batch & Output')
        notebook.add(tab_common, text='Common & Advanced')

        self._populate_extraction_tab(tab_extraction)
        self._populate_layout_tab(tab_layout)
        self._populate_preview_tab(self.tab_preview) # Populate new tab
        self._populate_batch_output_tab(tab_batch_output)
        self._populate_common_tab(tab_common)

    def _populate_preview_tab(self, tab):
        tab.columnconfigure(0, weight=1) # Make the preview area expand

        self.btn_preview_thumbs = ttk.Button(tab, text="Preview Extracted Thumbnails", command=self.start_thumbnail_preview_generation)
        self.btn_preview_thumbs.pack(pady=10)
        Tooltip(self.btn_preview_thumbs, "Generate and display a preview of thumbnails based on current extraction settings for the selected video(s).")

        preview_outer_frame = ttk.LabelFrame(tab, text="Thumbnails", padding="10")
        preview_outer_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        preview_outer_frame.rowconfigure(0, weight=1)
        preview_outer_frame.columnconfigure(0, weight=1)

        self.canvas_thumbs = tk.Canvas(preview_outer_frame, borderwidth=0, background="#ECECEC") # Light grey background
        self.frame_thumbs_inner = ttk.Frame(self.canvas_thumbs, padding="5")

        self.canvas_thumbs.create_window((0, 0), window=self.frame_thumbs_inner, anchor="nw", tags="self.frame_thumbs_inner")

        vsb = ttk.Scrollbar(preview_outer_frame, orient="vertical", command=self.canvas_thumbs.yview)
        self.canvas_thumbs.configure(yscrollcommand=vsb.set)

        vsb.grid(row=0, column=1, sticky="ns")
        self.canvas_thumbs.grid(row=0, column=0, sticky="nsew")

        self.frame_thumbs_inner.bind("<Configure>", lambda e: self.canvas_thumbs.configure(scrollregion=self.canvas_thumbs.bbox("all")))

        # Mouse wheel bindings
        self.canvas_thumbs.bind_all("<MouseWheel>", self._on_mousewheel) # Windows/macOS
        self.canvas_thumbs.bind_all("<Button-4>", self._on_mousewheel)   # Linux (scroll up)
        self.canvas_thumbs.bind_all("<Button-5>", self._on_mousewheel)   # Linux (scroll down)

    def _on_mousewheel(self, event):
        # For Linux, event.num determines scroll direction
        if hasattr(event, 'num') and event.num == 4:
            self.canvas_thumbs.yview_scroll(-1, "units")
        elif hasattr(event, 'num') and event.num == 5:
            self.canvas_thumbs.yview_scroll(1, "units")
        elif hasattr(event, 'delta'): # For Windows/macOS, event.delta
            self.canvas_thumbs.yview_scroll(int(-1*(event.delta/120)), "units")
        # Pass the event to other handlers if not consumed by this canvas
        # This is important if other widgets also need mouse wheel events.
        # However, for this specific canvas, we might want to consume it.
        # For now, let it propagate if needed, but often one might return "break"
        # if the scroll happened over the intended widget.

    def start_thumbnail_preview_generation(self):
        """Generate thumbnail previews based on current settings."""
        self.queue.put(("log", "Thumbnail preview generation initiated."))

        # Clear previous preview thumbnails
        for widget in self.frame_thumbs_inner.winfo_children():
            widget.destroy()
        self.thumbnail_images.clear()

        if not hasattr(self, '_internal_input_paths') or not self._internal_input_paths:
            input_paths_str = self.input_paths_var.get()
            if input_paths_str:
                self._internal_input_paths = [p.strip() for p in input_paths_str.split(';') if p.strip()]
        if not self._internal_input_paths:
            messagebox.showerror("Input Error", "Please select a video file for preview.")
            return

        if len(self._internal_input_paths) != 1 or not os.path.isfile(self._internal_input_paths[0]):
            messagebox.showerror("Input Error", "Please select a single video file for thumbnail preview.")
            return

        video_path = self._internal_input_paths[0]

        thread = threading.Thread(target=self._thumbnail_preview_thread, args=(video_path,))
        thread.daemon = True
        thread.start()

    def _thumbnail_preview_thread(self, video_path):
        import tempfile
        import shutil
        from movieprint_maker import parse_time_to_seconds
        import image_grid

        thread_logger = logging.getLogger(f"preview_thread_{threading.get_ident()}")
        thread_logger.setLevel(logging.INFO)

        queue_handler = QueueHandler(self.queue)
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        queue_handler.setFormatter(formatter)
        thread_logger.addHandler(queue_handler)
        thread_logger.propagate = False

        temp_dir = tempfile.mkdtemp(prefix="movieprint_preview_")
        cleanup = True
        try:
            start_sec = parse_time_to_seconds(self.start_time_var.get()) if self.start_time_var.get() else None
            end_sec = parse_time_to_seconds(self.end_time_var.get()) if self.end_time_var.get() else None

            if self.extraction_mode_var.get() == "interval":
                interval_sec = float(self.interval_seconds_var.get()) if self.interval_seconds_var.get() else None
                interval_frames = int(self.interval_frames_var.get()) if self.interval_frames_var.get() else None
                success, meta_list = video_processing.extract_frames(
                    video_path=video_path,
                    output_folder=temp_dir,
                    logger=thread_logger,
                    interval_seconds=interval_sec,
                    interval_frames=interval_frames,
                    output_format="jpg",
                    start_time_sec=start_sec,
                    end_time_sec=end_sec,
                )
            else:
                shot_thresh = float(self.shot_threshold_var.get()) if self.shot_threshold_var.get() else 27.0
                success, meta_list = video_processing.extract_shot_boundary_frames(
                    video_path=video_path,
                    output_folder=temp_dir,
                    logger=thread_logger,
                    output_format="jpg",
                    detector_threshold=shot_thresh,
                    start_time_sec=start_sec,
                    end_time_sec=end_sec,
                )

            if success:
                layout_mode = self.layout_mode_var.get()
                grid_path = os.path.join(temp_dir, "preview_grid.jpg")
                padding = int(self.padding_var.get()) if self.padding_var.get() else 0
                grid_params = {
                    'image_source_data': None,
                    'output_path': grid_path,
                    'padding': padding,
                    'background_color_hex': self.background_color_var.get(),
                    'layout_mode': layout_mode,
                    'logger': thread_logger
                }
                if layout_mode == "timeline":
                    grid_params['target_row_height'] = int(self.target_row_height_var.get()) if self.target_row_height_var.get() else 150
                    grid_params['max_grid_width'] = int(self.output_image_width_var.get()) if self.output_image_width_var.get() else 1920
                    grid_params['image_source_data'] = [
                        {'image_path': m['frame_path'], 'width_ratio': float(m.get('duration_frames', 1))}
                        for m in meta_list if m.get('duration_frames', 1) > 0
                    ]
                else:
                    if self.num_rows_var.get():
                        grid_params['rows'] = int(self.num_rows_var.get())
                    else:
                        grid_params['columns'] = int(self.num_columns_var.get()) if self.num_columns_var.get() else 5
                    ttw = self.target_thumbnail_width_var.get()
                    grid_params['target_thumbnail_width'] = int(ttw) if ttw else None
                    grid_params['image_source_data'] = [m['frame_path'] for m in meta_list]

                grid_success, _ = image_grid.create_image_grid(**grid_params)
                if grid_success:
                    self.queue.put(("preview_grid", {"grid_path": grid_path, "temp_dir": temp_dir}))
                    cleanup = False
                else:
                    self.queue.put(("log", "Thumbnail preview grid creation failed."))
            else:
                self.queue.put(("log", "Thumbnail preview extraction failed."))
        except Exception as e:
            thread_logger.exception(f"Error during thumbnail preview generation: {e}")
        finally:
            if cleanup:
                shutil.rmtree(temp_dir, ignore_errors=True)

    def _display_thumbnail_preview(self, data):
        if isinstance(data, dict):
            grid_path = data.get("grid_path")
            temp_dir = data.get("temp_dir")
        else:
            grid_path = data
            temp_dir = None

        for widget in self.frame_thumbs_inner.winfo_children():
            widget.destroy()
        self.thumbnail_images.clear()

        if grid_path and os.path.exists(grid_path):
            try:
                # Load the generated grid image
                img = Image.open(grid_path)

                # Determine available preview area within the canvas
                self.root.update_idletasks()
                max_w = self.canvas_thumbs.winfo_width() - 20
                max_h = self.canvas_thumbs.winfo_height() - 20

                if max_w > 0 and max_h > 0:
                    img.thumbnail((max_w, max_h), Image.Resampling.LANCZOS)

                photo = ImageTk.PhotoImage(img)
                self.thumbnail_images.append(photo)

                lbl = ttk.Label(self.frame_thumbs_inner, image=photo)
                lbl.pack(padx=2, pady=2)

                img.close()
            except Exception as e:
                self.queue.put(("log", f"Error loading preview grid {grid_path}: {e}"))

        self.canvas_thumbs.configure(scrollregion=self.canvas_thumbs.bbox("all"))

        if temp_dir:
            import shutil
            shutil.rmtree(temp_dir, ignore_errors=True)

    def _populate_extraction_tab(self, tab):
        tab.columnconfigure(1, weight=1)
        lbl_ext_mode = ttk.Label(tab, text="Extraction Mode:")
        lbl_ext_mode.grid(row=0, column=0, sticky=tk.W, padx=5, pady=(5,2))
        self.extraction_mode_combo = ttk.Combobox(tab, textvariable=self.extraction_mode_var, values=["interval", "shot"], state="readonly", width=15)
        self.extraction_mode_combo.grid(row=0, column=1, sticky=tk.EW, padx=5, pady=(5,2))
        self.extraction_mode_combo.bind("<<ComboboxSelected>>", self.update_options_visibility)
        Tooltip(self.extraction_mode_combo, "Choose method: regular intervals or detected shots.")
        
        self.interval_options_frame = ttk.Frame(tab)
        self.interval_options_frame.grid(row=1, column=0, columnspan=2, sticky=tk.EW, pady=(0,2))
        self.interval_options_frame.columnconfigure(1, weight=1)
        
        lbl_int_sec = ttk.Label(self.interval_options_frame, text="Interval (seconds):")
        lbl_int_sec.grid(row=0, column=0, sticky=tk.W, padx=5, pady=2)
        self.interval_seconds_entry = ttk.Entry(self.interval_options_frame, textvariable=self.interval_seconds_var, width=10)
        self.interval_seconds_entry.grid(row=0, column=1, sticky=tk.W, padx=5, pady=2)
        Tooltip(self.interval_seconds_entry, "Time between frames for 'interval' mode (e.g., 5.0).\nAuto-calculated if a single video is selected and 'Max Frames for Print' is set.")
        
        lbl_int_frames = ttk.Label(self.interval_options_frame, text="Interval (frames):")
        lbl_int_frames.grid(row=1, column=0, sticky=tk.W, padx=5, pady=2)
        self.interval_frames_entry = ttk.Entry(self.interval_options_frame, textvariable=self.interval_frames_var, width=10)
        self.interval_frames_entry.grid(row=1, column=1, sticky=tk.W, padx=5, pady=2)
        Tooltip(self.interval_frames_entry, "Frame count between frames for 'interval' mode (e.g., 150).\nIf both seconds and frames interval are set, seconds interval is used.")
        
        self.shot_options_frame = ttk.Frame(tab)
        self.shot_options_frame.grid(row=2, column=0, columnspan=2, sticky=tk.EW, pady=(0,2))
        self.shot_options_frame.columnconfigure(1, weight=1)
        lbl_shot_thresh = ttk.Label(self.shot_options_frame, text="Shot Threshold:")
        lbl_shot_thresh.grid(row=0, column=0, sticky=tk.W, padx=5, pady=2)
        self.shot_threshold_entry = ttk.Entry(self.shot_options_frame, textvariable=self.shot_threshold_var, width=10)
        self.shot_threshold_entry.grid(row=0, column=1, sticky=tk.W, padx=5, pady=2)
        Tooltip(self.shot_threshold_entry, "Sensitivity for shot detection (e.g., 27.0). Lower = more shots.")
        
        lbl_start_time = ttk.Label(tab, text="Start Time (HH:MM:SS or S):")
        lbl_start_time.grid(row=3, column=0, sticky=tk.W, padx=5, pady=(5,2))
        self.start_time_entry = ttk.Entry(tab, textvariable=self.start_time_var, width=15)
        self.start_time_entry.grid(row=3, column=1, sticky=tk.W, padx=5, pady=(5,2))
        Tooltip(self.start_time_entry, "Process video from this time. Examples: '01:23:45', '90:00', '5400.5'.\nLeave blank to process from the beginning.")
        
        lbl_end_time = ttk.Label(tab, text="End Time (HH:MM:SS or S):")
        lbl_end_time.grid(row=4, column=0, sticky=tk.W, padx=5, pady=(2,5))
        self.end_time_entry = ttk.Entry(tab, textvariable=self.end_time_var, width=15)
        self.end_time_entry.grid(row=4, column=1, sticky=tk.W, padx=5, pady=(2,5))
        Tooltip(self.end_time_entry, "Process video up to this time. Examples: '01:23:45', '90:00', '5400.5'.\nLeave blank to process until the end.")
        
        lbl_ex_frames = ttk.Label(tab, text="Exclude Frames (abs nums):")
        lbl_ex_frames.grid(row=5, column=0, sticky=tk.W, padx=5, pady=(5,2))
        self.exclude_frames_entry = ttk.Entry(tab, textvariable=self.exclude_frames_var)
        self.exclude_frames_entry.grid(row=5, column=1, sticky=tk.EW, padx=5, pady=(5,2))
        Tooltip(self.exclude_frames_entry, "Comma-separated absolute frame numbers to exclude (for interval mode only). E.g., 100,101,150")
        
        lbl_ex_shots = ttk.Label(tab, text="Exclude Shots (1-based idx):")
        lbl_ex_shots.grid(row=6, column=0, sticky=tk.W, padx=5, pady=(2,5))
        self.exclude_shots_entry = ttk.Entry(tab, textvariable=self.exclude_shots_var)
        self.exclude_shots_entry.grid(row=6, column=1, sticky=tk.EW, padx=5, pady=(2,5))
        Tooltip(self.exclude_shots_entry, "Comma-separated 1-based shot indices to exclude (for shot mode only). E.g., 1,3")

    def _populate_layout_tab(self, tab):
        tab.columnconfigure(1, weight=1)
        lbl_layout_mode = ttk.Label(tab, text="Layout Mode:")
        lbl_layout_mode.grid(row=0, column=0, sticky=tk.W, padx=5, pady=5)
        self.layout_mode_combo = ttk.Combobox(tab, textvariable=self.layout_mode_var, values=["grid", "timeline"], state="readonly", width=15)
        self.layout_mode_combo.grid(row=0, column=1, sticky=tk.EW, padx=5, pady=5)
        self.layout_mode_combo.bind("<<ComboboxSelected>>", self.update_options_visibility)
        Tooltip(self.layout_mode_combo, "Choose MoviePrint layout: fixed grid or timeline (proportional width).\nTimeline layout requires 'shot' extraction mode.")
        
        lbl_max_frames = ttk.Label(tab, text="Max Frames for Print:")
        lbl_max_frames.grid(row=1, column=0, sticky=tk.W, padx=5, pady=5)
        self.max_frames_entry = ttk.Entry(tab, textvariable=self.max_frames_for_print_var, width=10)
        self.max_frames_entry.grid(row=1, column=1, sticky=tk.W, padx=5, pady=5)
        Tooltip(self.max_frames_entry, "Target maximum number of frames in the final MoviePrint.\nIf extraction yields more, frames will be sampled down to this count (e.g., 100). Also used to auto-calculate 'Interval (seconds)' when a single video is selected.")
        
        self.grid_options_frame = ttk.Frame(tab)
        self.grid_options_frame.grid(row=2, column=0, columnspan=2, sticky=tk.EW, pady=3)
        self.grid_options_frame.columnconfigure(1, weight=1)
        lbl_cols = ttk.Label(self.grid_options_frame, text="Number of Columns:")
        lbl_cols.grid(row=0, column=0, sticky=tk.W, padx=5, pady=2)
        self.num_columns_entry = ttk.Entry(self.grid_options_frame, textvariable=self.num_columns_var, width=10)
        self.num_columns_entry.grid(row=0, column=1, sticky=tk.W, padx=5, pady=2)
        Tooltip(self.num_columns_entry, "Number of columns for 'grid' layout.")

        lbl_rows = ttk.Label(self.grid_options_frame, text="Number of Rows:")
        lbl_rows.grid(row=1, column=0, sticky=tk.W, padx=5, pady=2)
        self.num_rows_entry = ttk.Entry(self.grid_options_frame, textvariable=self.num_rows_var, width=10)
        self.num_rows_entry.grid(row=1, column=1, sticky=tk.W, padx=5, pady=2)
        Tooltip(self.num_rows_entry, "Number of rows for 'grid' layout. Overrides columns if set.")

        lbl_target_thumb_w = ttk.Label(self.grid_options_frame, text="Target Thumbnail Width (px):")
        lbl_target_thumb_w.grid(row=2, column=0, sticky=tk.W, padx=5, pady=2)
        self.target_thumbnail_width_entry = ttk.Entry(self.grid_options_frame, textvariable=self.target_thumbnail_width_var, width=10)
        self.target_thumbnail_width_entry.grid(row=2, column=1, sticky=tk.W, padx=5, pady=2)
        Tooltip(self.target_thumbnail_width_entry, "For 'grid' layout: desired width for individual thumbnails (e.g., 320).\nOverrides automatic sizing. Cell height adjusts to aspect ratios.")
        
        self.timeline_options_frame = ttk.Frame(tab)
        self.timeline_options_frame.grid(row=3, column=0, columnspan=2, sticky=tk.EW, pady=3) 
        self.timeline_options_frame.columnconfigure(1, weight=1)
        lbl_row_h = ttk.Label(self.timeline_options_frame, text="Target Row Height (px):")
        lbl_row_h.grid(row=0, column=0, sticky=tk.W, padx=5, pady=2)
        self.target_row_height_entry = ttk.Entry(self.timeline_options_frame, textvariable=self.target_row_height_var, width=10)
        self.target_row_height_entry.grid(row=0, column=1, sticky=tk.W, padx=5, pady=2)
        Tooltip(self.target_row_height_entry, "Target height for each row in 'timeline' layout.")
        lbl_out_w = ttk.Label(self.timeline_options_frame, text="Output Image Width (px):")
        lbl_out_w.grid(row=1, column=0, sticky=tk.W, padx=5, pady=2)
        self.output_image_width_entry = ttk.Entry(self.timeline_options_frame, textvariable=self.output_image_width_var, width=10)
        self.output_image_width_entry.grid(row=1, column=1, sticky=tk.W, padx=5, pady=2)
        Tooltip(self.output_image_width_entry, "Target width for the final image in 'timeline' layout.")

    def _populate_batch_output_tab(self, tab):
        # ... (content as before) ...
        tab.columnconfigure(1, weight=1)
        lbl_out_fname = ttk.Label(tab, text="Output Filename (single input):")
        lbl_out_fname.grid(row=0, column=0, sticky=tk.W, padx=5, pady=5)
        self.output_filename_entry = ttk.Entry(tab, textvariable=self.output_filename_var, width=40)
        self.output_filename_entry.grid(row=0, column=1, sticky=tk.EW, padx=5, pady=5)
        Tooltip(self.output_filename_entry, "Specific filename if only one input file is processed.\nOtherwise, filenames are auto-generated using the suffix below.")
        lbl_out_suffix = ttk.Label(tab, text="Output Suffix (batch mode):")
        lbl_out_suffix.grid(row=1, column=0, sticky=tk.W, padx=5, pady=5)
        self.output_filename_suffix_entry = ttk.Entry(tab, textvariable=self.output_filename_suffix_var, width=20)
        self.output_filename_suffix_entry.grid(row=1, column=1, sticky=tk.W, padx=5, pady=5)
        Tooltip(self.output_filename_suffix_entry, "Suffix for auto-generated filenames in batch mode (e.g., '_movieprint').")
        lbl_vid_ext = ttk.Label(tab, text="Video Extensions (batch scan):")
        lbl_vid_ext.grid(row=2, column=0, sticky=tk.W, padx=5, pady=5)
        self.video_extensions_entry = ttk.Entry(tab, textvariable=self.video_extensions_var, width=40)
        self.video_extensions_entry.grid(row=2, column=1, sticky=tk.EW, padx=5, pady=5)
        Tooltip(self.video_extensions_entry, "Comma-separated list of video extensions for directory scanning (e.g., .mp4,.avi,.mov).")
        self.recursive_scan_check = ttk.Checkbutton(tab, text="Recursive Directory Scan", variable=self.recursive_scan_var)
        self.recursive_scan_check.grid(row=3, column=0, columnspan=2, sticky=tk.W, padx=5, pady=5)
        Tooltip(self.recursive_scan_check, "If checked, scan directories recursively for videos.")

    def _populate_common_tab(self, tab):
        # ... (content as before) ...
        tab.columnconfigure(1, weight=1)
        lbl_pad = ttk.Label(tab, text="Padding (px):")
        lbl_pad.grid(row=0, column=0, sticky=tk.W, padx=5, pady=5)
        self.padding_entry = ttk.Entry(tab, textvariable=self.padding_var, width=10)
        self.padding_entry.grid(row=0, column=1, sticky=tk.W, padx=5, pady=5)
        Tooltip(self.padding_entry, "Padding around and between thumbnails.")
        lbl_bg = ttk.Label(tab, text="Background Color (hex):")
        lbl_bg.grid(row=1, column=0, sticky=tk.W, padx=5, pady=5)
        self.bg_color_entry = ttk.Entry(tab, textvariable=self.background_color_var, width=10)
        self.bg_color_entry.grid(row=1, column=1, sticky=tk.W, padx=5, pady=5)
        btn_pick_color = ttk.Button(tab, text="Pick...", command=self.pick_bg_color)
        btn_pick_color.grid(row=1, column=2, padx=5, pady=5)
        Tooltip(self.bg_color_entry, "Hex color for the MoviePrint background (e.g., #FFFFFF or white).")
        Tooltip(btn_pick_color, "Open color chooser dialog to select background color.")
        lbl_frame_fmt = ttk.Label(tab, text="Frame Format (temp):")
        lbl_frame_fmt.grid(row=2, column=0, sticky=tk.W, padx=5, pady=5)
        self.frame_format_combo = ttk.Combobox(tab, textvariable=self.frame_format_var, values=["jpg", "png"], state="readonly", width=8)
        self.frame_format_combo.grid(row=2, column=1, sticky=tk.W, padx=5, pady=5)
        Tooltip(self.frame_format_combo, "Format for temporary extracted frame images (jpg or png).")
        lbl_rotate = ttk.Label(tab, text="Rotate Thumbnails:")
        lbl_rotate.grid(row=3, column=0, sticky=tk.W, padx=5, pady=5)
        self.rotate_combo = ttk.Combobox(tab, textvariable=self.rotate_thumbnails_var, values=[0, 90, 180, 270], state="readonly", width=8)
        self.rotate_combo.grid(row=3, column=1, sticky=tk.W, padx=5, pady=5)
        Tooltip(self.rotate_combo, "Rotate all thumbnails clockwise by the selected degrees (0, 90, 180, 270).")
        lbl_temp_dir = ttk.Label(tab, text="Custom Temp Directory:")
        lbl_temp_dir.grid(row=4, column=0, sticky=tk.W, padx=5, pady=5)
        self.temp_dir_entry = ttk.Entry(tab, textvariable=self.temp_dir_var, width=40)
        self.temp_dir_entry.grid(row=4, column=1, sticky=tk.EW, padx=5, pady=5)
        btn_browse_temp = ttk.Button(tab, text="Browse...", command=lambda: self.browse_specific_dir(self.temp_dir_var, "Select Custom Temporary Directory"))
        btn_browse_temp.grid(row=4, column=2, padx=5, pady=5)
        Tooltip(self.temp_dir_entry, "Optional. If set, temporary frames will be stored here and NOT auto-cleaned.")
        Tooltip(btn_browse_temp, "Browse for a custom temporary directory.")
        lbl_haar = ttk.Label(tab, text="Haar Cascade XML:")
        lbl_haar.grid(row=5, column=0, sticky=tk.W, padx=5, pady=5)
        self.haar_cascade_entry = ttk.Entry(tab, textvariable=self.haar_cascade_xml_var, width=40)
        self.haar_cascade_entry.grid(row=5, column=1, sticky=tk.EW, padx=5, pady=5)
        btn_browse_haar = ttk.Button(tab, text="Browse...", command=lambda: self.browse_specific_file(self.haar_cascade_xml_var, "Select Haar Cascade XML", (("XML files", "*.xml"),("All files", "*.*"))))
        btn_browse_haar.grid(row=5, column=2, padx=5, pady=5)
        Tooltip(self.haar_cascade_entry, "Optional. Path to Haar Cascade XML for face detection.\nUses OpenCV default if empty and face detection is enabled.")
        Tooltip(btn_browse_haar, "Browse for a Haar Cascade XML file.")
        self.save_metadata_check = ttk.Checkbutton(tab, text="Save Metadata JSON", variable=self.save_metadata_json_var)
        self.save_metadata_check.grid(row=6, column=0, columnspan=2, sticky=tk.W, padx=5, pady=5)
        Tooltip(self.save_metadata_check, "Save a JSON file with detailed metadata alongside the MoviePrint.")
        self.detect_faces_check = ttk.Checkbutton(tab, text="Detect Faces (slow)", variable=self.detect_faces_var)
        self.detect_faces_check.grid(row=7, column=0, columnspan=2, sticky=tk.W, padx=5, pady=5)
        Tooltip(self.detect_faces_check, "Enable face detection on thumbnails. This can be performance intensive.")

        lbl_max_filesize = ttk.Label(tab, text="Max Output Filesize (KB):")
        lbl_max_filesize.grid(row=8, column=0, sticky=tk.W, padx=5, pady=5)
        self.max_output_filesize_entry = ttk.Entry(tab, textvariable=self.max_output_filesize_kb_var, width=10)
        self.max_output_filesize_entry.grid(row=8, column=1, sticky=tk.W, padx=5, pady=5)
        Tooltip(self.max_output_filesize_entry, "Attempt to reduce the final MoviePrint so its file size does not exceed this value. Leave blank for no limit.")

        # Add Reset to Defaults button
        btn_reset_defaults = ttk.Button(tab, text="Reset All Settings to Defaults", command=self.confirm_reset_all_settings)
        btn_reset_defaults.grid(row=9, column=0, columnspan=3, sticky=tk.W, padx=5, pady=20) # columnspan to fit button text
        Tooltip(btn_reset_defaults, "Resets all settings in the GUI to their original default values. Input/Output paths are not reset.")


    def confirm_reset_all_settings(self):
        if messagebox.askyesno("Confirm Reset", "Are you sure you want to reset all settings to their default values?\nAll current unsaved changes to settings will be lost.\nInput/Output paths will NOT be reset."):
            self.perform_reset_all_settings()

    def perform_reset_all_settings(self):
        self._gui_log_callback("Resetting all settings to defaults...")

        # Explicitly reset input and output paths first
        self.input_paths_var.set(self.default_settings.get("input_paths_var", ""))
        self._internal_input_paths = [] # Clear the internal list of paths
        self.output_dir_var.set(self.default_settings.get("output_dir_var", ""))

        # Iterate through the rest of the settings
        for var_key, default_value in self.default_settings.items():
            if var_key not in ["input_paths_var", "output_dir_var"]: # Skip already handled ones
                try:
                    # Get the actual Tkinter variable instance (e.g., self.extraction_mode_var)
                    tk_var_instance = getattr(self, var_key)
                    tk_var_instance.set(default_value)
                except AttributeError:
                    self._gui_log_callback(f"Warning: Could not reset setting for '{var_key}' - variable not found.")
                except Exception as e:
                    self._gui_log_callback(f"Warning: Error resetting setting for '{var_key}': {e}")

        self.update_options_visibility() # Refresh UI elements based on new (default) values
        self._gui_log_callback("All settings have been reset to their default values.")


    def _create_action_log_section(self, parent_frame):
        # ... (content as before) ...
        action_section = ttk.Frame(parent_frame, padding="10")
        action_section.pack(fill=tk.X, padx=5, pady=5)
        self.generate_button = ttk.Button(action_section, text="Generate MoviePrint", command=self.generate_movieprint_action)
        self.generate_button.pack(pady=5)
        Tooltip(self.generate_button, "Start generating the MoviePrint with current settings.")
        self.progress_bar = ttk.Progressbar(action_section, orient="horizontal", mode="determinate", length=300)
        self.progress_bar.pack(fill=tk.X, padx=5, pady=2)
        log_section = ttk.LabelFrame(parent_frame, text="Log", padding="10")
        log_section.pack(expand=True, fill=tk.BOTH, padx=5, pady=5)
        self.log_text = scrolledtext.ScrolledText(log_section, wrap=tk.WORD, state="disabled", height=10)
        self.log_text.pack(expand=True, fill=tk.BOTH)

    def _get_video_duration_sync(self, video_path):
        # ... (as defined before) ...
        duration = None
        try:
            cap = cv2.VideoCapture(video_path)
            if cap.isOpened():
                fps = cap.get(cv2.CAP_PROP_FPS)
                frame_count = cap.get(cv2.CAP_PROP_FRAME_COUNT)
                if fps > 0 and frame_count > 0:
                    duration = frame_count / fps
                cap.release()
        except Exception as e:
            self.queue.put(("log", f"Error getting video duration for {os.path.basename(video_path)}: {e}"))
        return duration

    def _auto_calculate_and_set_interval(self, video_path):
        # ... (as defined before) ...
        if not video_path or not os.path.isfile(video_path):
            return

        duration_sec = self._get_video_duration_sync(video_path)

        if duration_sec is None:
            self.queue.put(("log", f"Warning: Could not determine duration for {os.path.basename(video_path)} to auto-calculate interval."))
            return

        try:
            target_frames_str = self.max_frames_for_print_var.get()
            if target_frames_str and target_frames_str.strip():
                target_frames = int(target_frames_str)
                if target_frames <= 0:
                    self.queue.put(("log", "Warning: 'Max Frames for Print' is not positive. Using default 60 for auto-calc."))
                    target_frames = 60 
            else: 
                self.queue.put(("log", "Info: 'Max Frames for Print' is blank. Using default 60 for auto-calc."))
                target_frames = 60

            if target_frames > 0 and duration_sec > 0:
                calculated_interval = duration_sec / target_frames
                calculated_interval = max(0.1, calculated_interval) 
                self.interval_seconds_var.set(f"{calculated_interval:.2f}") 
                self.queue.put(("log", 
                    f"Auto-calculated interval for '{os.path.basename(video_path)}' ({duration_sec:.1f}s) "
                    f"to ~{target_frames} frames: {calculated_interval:.2f}s"
                ))
            elif duration_sec == 0:
                 self.queue.put(("log", f"Warning: Video duration for {os.path.basename(video_path)} is 0. Cannot auto-calculate interval."))

        except ValueError:
            self.queue.put(("log", "Warning: Invalid 'Max Frames for Print' value. Cannot auto-calculate interval."))
        except Exception as e:
            self.queue.put(("log", f"Error during auto-interval calculation: {e}"))
            
    def browse_input_paths(self): 
        # ... (as defined before, with call to _auto_calculate_and_set_interval) ...
        filepaths = filedialog.askopenfilenames(title="Select Video File(s) (or cancel and select a directory next)", filetypes=(("Video files", "*.mp4 *.avi *.mov *.mkv *.flv *.wmv"), ("All files", "*.*")))
        if filepaths:
            self._internal_input_paths = list(filepaths)
            self.input_paths_var.set("; ".join(self._internal_input_paths))
            if len(self._internal_input_paths) == 1 and os.path.isfile(self._internal_input_paths[0]):
                self.root.after(200, lambda p=self._internal_input_paths[0]: self._auto_calculate_and_set_interval(p))
            else:
                self.interval_seconds_var.set("5.0") 
                self.queue.put(("log", "Multiple files/directory selected. Manual interval setting recommended."))
        else:
            dir_path = filedialog.askdirectory(title="Select Directory of Videos")
            if dir_path:
                self._internal_input_paths = [dir_path]
                self.input_paths_var.set(dir_path)
                self.interval_seconds_var.set("5.0") 
                self.queue.put(("log", "Directory selected. Manual interval setting recommended."))

    def browse_output_dir(self): 
        dir_path = filedialog.askdirectory(title="Select Output Directory")
        if dir_path: self.output_dir_var.set(dir_path)

    def browse_specific_dir(self, tk_var, title_text):
        dir_path = filedialog.askdirectory(title=title_text)
        if dir_path: tk_var.set(dir_path)

    def browse_specific_file(self, tk_var, title_text, file_types):
        filepath = filedialog.askopenfilename(title=title_text, filetypes=file_types)
        if filepath: tk_var.set(filepath)

    def pick_bg_color(self):
        color = tk.colorchooser.askcolor(color=self.background_color_var.get())
        if color[1]:
            self.background_color_var.set(color[1])

    def handle_drop(self, event):
        data_string = event.data
        dropped_paths = []
        # TkinterDnD might return paths in curly braces if they contain spaces,
        # and multiple paths are space-separated.
        # Example: '{/path/to/file with space.mp4} /path/to/another.avi'
        # Or a single path: '/path/to/singlefile.mkv'
        # Or a single path with space: '{/path with space/video.mp4}'

        current_path = ""
        in_braces = False
        for char in data_string:
            if char == '{' and not in_braces:
                in_braces = True
            elif char == '}' and in_braces:
                in_braces = False
                dropped_paths.append(current_path)
                current_path = ""
            elif char == ' ' and not in_braces:
                if current_path: # Path without spaces
                    dropped_paths.append(current_path)
                    current_path = ""
            else:
                current_path += char
        if current_path: # Add any remaining path
            dropped_paths.append(current_path)

        # Further clean up: remove leading/trailing whitespace from each path
        dropped_paths = [p.strip() for p in dropped_paths if p.strip()]

        if not dropped_paths:
            self.queue.put(("log", "Drag & drop: No valid paths found in dropped data."))
            return

        self.queue.put(("log", f"Drag & drop: Received data: {data_string}"))
        self.queue.put(("log", f"Drag & drop: Parsed paths: {dropped_paths}"))

        if len(dropped_paths) == 1 and os.path.isdir(dropped_paths[0]):
            dir_path = dropped_paths[0]
            self._internal_input_paths = [dir_path]
            self.input_paths_var.set(dir_path)
            self.interval_seconds_var.set("5.0") # Reset interval for directory
            self.queue.put(("log", f"Drag & drop: Directory '{os.path.basename(dir_path)}' selected. Manual interval recommended (reset to 5.0s)."))
        else:
            # Filter for files, assuming they are videos for now.
            # Backend will ultimately filter by extension.
            video_files = [p for p in dropped_paths if os.path.isfile(p)]

            if not video_files:
                self.queue.put(("log", "Drag & drop: No valid files found in dropped items."))
                # Potentially show an error or just log, depending on desired UX
                # For now, if a directory was mixed with non-files and not caught above,
                # this will prevent processing.
                return

            self._internal_input_paths = video_files
            self.input_paths_var.set("; ".join(self._internal_input_paths))

            if len(self._internal_input_paths) == 1:
                # Already checked it's a file by being in video_files
                self.queue.put(("log", f"Drag & drop: Single file '{os.path.basename(self._internal_input_paths[0])}' selected."))
                # Delay slightly to allow GUI to update input field text before potential modal dialogs from auto-calc
                self.root.after(100, lambda p=self._internal_input_paths[0]: self._auto_calculate_and_set_interval(p))
            else:
                self.interval_seconds_var.set("5.0") # Reset interval for multiple files
                self.queue.put(("log", f"Drag & drop: Multiple files ({len(self._internal_input_paths)}) selected. Manual interval recommended (reset to 5.0s)."))


    def log_message_from_thread(self, message): 
        self.log_text.config(state="normal")
        self.log_text.insert(tk.END, message + "\n")
        self.log_text.see(tk.END)
        self.log_text.config(state="disabled")

    def update_progress_from_thread(self, current, total, filename): 
        if total > 0:
            percentage = (current / total) * 100
            self.progress_bar["value"] = percentage
            if current < total and current != 0 :
                self.log_message_from_thread(f"Processing {os.path.basename(filename)} ({current}/{total})...")
            elif current == total :
                self.log_message_from_thread(f"Batch processing finished. Processed {total} items.")
        else: self.progress_bar["value"] = 0

    def check_queue(self): 
        try:
            while True:
                message_type, data = self.queue.get_nowait()
                if message_type == "log": self.log_message_from_thread(data)
                elif message_type == "progress":
                    current, total, filename = data
                    self.update_progress_from_thread(current, total, filename)
                elif message_type == "state":
                    if data == "enable_button": self.generate_button.config(state="normal")
                    elif data == "disable_button": self.generate_button.config(state="disabled")
                elif message_type == "preview_grid":
                    self._display_thumbnail_preview(data)
                self.root.update_idletasks()
        except queue.Empty: pass
        self.root.after(100, self.check_queue)

    def _gui_log_callback(self, message): self.queue.put(("log", message))
    def _gui_progress_callback(self, current, total, filename): self.queue.put(("progress", (current, total, filename)))

    def _parse_int_list_from_string(self, s, context_msg=""): 
        if not s: return None
        try: return [int(item.strip()) for item in s.split(',') if item.strip()]
        except ValueError: messagebox.showerror("Input Error", f"Invalid format for {context_msg}. Expecting comma-separated numbers (e.g., 1,2,3)."); return "ERROR"

    def generate_movieprint_action(self): 
        # ... (generate_movieprint_action remains the same as in the previous version with max_frames parsing) ...
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
            settings.interval_seconds = float(self.interval_seconds_var.get()) if self.interval_seconds_var.get() else None
            settings.interval_frames = int(self.interval_frames_var.get()) if self.interval_frames_var.get() else None
            settings.shot_threshold = float(self.shot_threshold_var.get()) if self.shot_threshold_var.get() else 27.0
            if self.num_rows_var.get():
                settings.rows = int(self.num_rows_var.get())
                settings.columns = None
            else:
                settings.columns = int(self.num_columns_var.get()) if self.num_columns_var.get() else 5
            settings.target_row_height = int(self.target_row_height_var.get()) if self.target_row_height_var.get() else 150
            settings.output_image_width = int(self.output_image_width_var.get()) if self.output_image_width_var.get() else 1920
            settings.padding = int(self.padding_var.get()) if self.padding_var.get() else 5
            
            max_frames_str = self.max_frames_for_print_var.get()
            if max_frames_str and max_frames_str.strip():
                settings.max_frames_for_print = int(max_frames_str)
                if settings.max_frames_for_print <= 0:
                    messagebox.showerror("Input Error", "Max Frames for Print must be a positive number if set.")
                    return
            else:
                settings.max_frames_for_print = None

            target_thumb_w_str = self.target_thumbnail_width_var.get()
            if target_thumb_w_str and target_thumb_w_str.strip():
                settings.target_thumbnail_width = int(target_thumb_w_str)
                if settings.target_thumbnail_width <= 0:
                    messagebox.showerror("Input Error", "Target Thumbnail Width must be a positive integer if set.")
                    return
            else:
                settings.target_thumbnail_width = None

        except ValueError as e: messagebox.showerror("Input Error", f"Invalid numeric value in settings: {e}"); return
        
        # Validate target_thumbnail_width applicability (after parsing all mode vars)
        if settings.layout_mode != "grid" and settings.target_thumbnail_width is not None:
            self._gui_log_callback("Warning: Target Thumbnail Width is only applicable for 'grid' layout and will be ignored.")
            # settings.target_thumbnail_width = None # Let backend handle ignoring if it's robust

        settings.background_color = self.background_color_var.get()
        settings.frame_format = self.frame_format_var.get()
        settings.save_metadata_json = self.save_metadata_json_var.get()
        settings.detect_faces = self.detect_faces_var.get()
        settings.rotate_thumbnails = self.rotate_thumbnails_var.get()
        settings.start_time = self.start_time_var.get() if self.start_time_var.get() else None
        settings.end_time = self.end_time_var.get() if self.end_time_var.get() else None
        settings.exclude_frames = self._parse_int_list_from_string(self.exclude_frames_var.get(), "Exclude Frames")
        if settings.exclude_frames == "ERROR": return
        settings.exclude_shots = self._parse_int_list_from_string(self.exclude_shots_var.get(), "Exclude Shots")
        if settings.exclude_shots == "ERROR": return
        settings.output_filename_suffix = self.output_filename_suffix_var.get()
        settings.output_filename = self.output_filename_var.get() if self.output_filename_var.get() else None
        raw_video_extensions = self.video_extensions_var.get()
        settings.video_extensions = ",".join([ext.strip() for ext in raw_video_extensions.split(',') if ext.strip() and ext.startswith('.')]) if raw_video_extensions else ".mp4,.avi,.mov,.mkv,.flv,.wmv"
        if not settings.video_extensions: messagebox.showwarning("Input Warning", "Video extensions field was empty or invalid; using default extensions."); settings.video_extensions = ".mp4,.avi,.mov,.mkv,.flv,.wmv"
        settings.recursive_scan = self.recursive_scan_var.get()
        settings.temp_dir = self.temp_dir_var.get() if self.temp_dir_var.get() else None
        settings.haar_cascade_xml = self.haar_cascade_xml_var.get() if self.haar_cascade_xml_var.get() else None
        max_size_str = self.max_output_filesize_kb_var.get()
        if max_size_str and max_size_str.strip():
            try:
                settings.max_output_filesize_kb = int(max_size_str)
                if settings.max_output_filesize_kb <= 0:
                    messagebox.showerror("Input Error", "Max Output Filesize must be a positive integer if set.")
                    return
            except ValueError:
                messagebox.showerror("Input Error", "Max Output Filesize must be an integer if set.")
                return
        else:
            settings.max_output_filesize_kb = None

        self.log_text.config(state="normal"); self.log_text.delete(1.0, tk.END); self.log_text.config(state="disabled")
        self.queue.put(("state", "disable_button"))
        self.progress_bar["value"] = 0
        self._gui_log_callback("Starting generation...")

        thread = threading.Thread(target=self.run_generation_in_thread, args=(settings, self._gui_progress_callback))
        thread.daemon = True
        thread.start()


    def run_generation_in_thread(self, settings, progress_cb):
        # ... (content as before) ...
        thread_logger = logging.getLogger(f"gui_thread_{threading.get_ident()}")
        thread_logger.setLevel(logging.INFO)

        for handler in thread_logger.handlers[:]: 
            thread_logger.removeHandler(handler)

        queue_handler = QueueHandler(self.queue)
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        queue_handler.setFormatter(formatter)

        thread_logger.addHandler(queue_handler)
        thread_logger.propagate = False
        try:
            successful_ops, failed_ops = execute_movieprint_generation(settings, thread_logger, progress_cb)
        except Exception as e:
            thread_logger.exception(f"An unexpected error occurred in the generation thread: {e}")
        finally:
            self.queue.put(("state", "enable_button"))
            self.queue.put(("log", "--- GUI Processing Session Finished ---")) 
            if progress_cb:
                max_progress = self.progress_bar.cget("maximum") if hasattr(self, 'progress_bar') else 100
                progress_cb(max_progress, max_progress, "Done")

    def update_options_visibility(self, event=None): 
        # ... (content as before, ensure row numbers are correct) ...
        extraction_mode = self.extraction_mode_var.get()
        layout_mode = self.layout_mode_var.get()
        if hasattr(self, 'interval_options_frame'):
            is_interval_mode = extraction_mode == "interval"
            self.interval_options_frame.grid_remove() if not is_interval_mode else self.interval_options_frame.grid(row=1, column=0, columnspan=2, sticky=tk.EW, pady=(0,2))
            self.interval_frames_entry.config(state="normal" if is_interval_mode else "disabled")
            self.exclude_frames_entry.config(state="normal" if is_interval_mode else "disabled")
        if hasattr(self, 'shot_options_frame'):
            is_shot_mode = extraction_mode == "shot"
            self.shot_options_frame.grid_remove() if not is_shot_mode else self.shot_options_frame.grid(row=2, column=0, columnspan=2, sticky=tk.EW, pady=(0,2))
            self.exclude_shots_entry.config(state="normal" if is_shot_mode else "disabled")
        
        if hasattr(self, 'grid_options_frame'): 
            self.grid_options_frame.grid_remove()
            if layout_mode == "grid": self.grid_options_frame.grid(row=2, column=0, columnspan=2, sticky=tk.EW, pady=3)
        
        if hasattr(self, 'timeline_options_frame'): 
            self.timeline_options_frame.grid_remove()
            if layout_mode == "timeline":
                if extraction_mode != "shot":
                    self.layout_mode_var.set("grid") 
                    if hasattr(self, 'grid_options_frame'): self.grid_options_frame.grid(row=2, column=0, columnspan=2, sticky=tk.EW, pady=3) 
                    messagebox.showwarning("Layout Change", "Timeline layout requires 'Shot' extraction mode. Switched to 'Grid' layout.")
                else:
                    self.timeline_options_frame.grid(row=3, column=0, columnspan=2, sticky=tk.EW, pady=3)
        
        if hasattr(self, 'max_frames_entry'):
            max_frames_label_widget = self.max_frames_entry.master.grid_slaves(row=1, column=0)
            if layout_mode == "grid":
                self.max_frames_entry.grid() 
                if max_frames_label_widget: max_frames_label_widget[0].grid()
            else: 
                self.max_frames_entry.grid_remove()
                if max_frames_label_widget: max_frames_label_widget[0].grid_remove()

if __name__ == "__main__":
    app = MoviePrintApp()
    app.root.mainloop()
