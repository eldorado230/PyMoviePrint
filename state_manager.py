import copy
from dataclasses import dataclass, field, replace
from typing import List, Dict, Any, Optional

@dataclass
class ProjectSettings:
    """
    Holds all configuration settings for the application.
    """
    # Input
    input_paths: List[str] = field(default_factory=list)
    recursive_scan: bool = False  # NEW: Scans subdirectories if True
    
    # Naming Scheme
    output_naming_mode: str = "suffix"  # "suffix" or "custom"
    output_filename_suffix: str = "_movieprint"
    output_filename: str = ""
    overwrite_mode: str = "overwrite" # NEW: "overwrite" or "skip"

    # Extraction
    extraction_mode: str = "interval"  # "interval" or "shot"
    interval_seconds: float = 5.0
    interval_frames: Optional[int] = None
    shot_threshold: float = 27.0
    
    # Layout (Grid/Timeline)
    layout_mode: str = "grid"
    num_columns: int = 5
    num_rows: int = 5
    target_row_height: int = 150
    
    # --- NEW: Output Dimensions & Fitting ---
    fit_to_output_params: bool = False  # If True, force grid to output_width x output_height
    output_width: int = 1920
    output_height: int = 1080
    # ----------------------------------------

    # Processing
    use_gpu: bool = False
    detect_faces: bool = False
    
    # HDR & Color
    hdr_tonemap: bool = False
    hdr_algorithm: str = "hable"  # "hable", "reinhard", "mobius"
    
    # Styling - Background & Metrics
    background_color: str = "#1e1e1e"
    padding: int = 5
    grid_margin: int = 0
    rounded_corners: int = 0
    rotate_thumbnails: int = 0  # 0, 90, 180, 270
    
    # Styling - Frame Info / OSD
    show_header: bool = False
    show_file_path: bool = True
    show_timecode: bool = True
    show_frame_num: bool = True
    
    frame_info_show: bool = False
    frame_info_timecode_or_frame: str = "timecode"
    frame_info_font_color: str = "#FFFFFF"
    frame_info_bg_color: str = "#000000"
    frame_info_position: str = "bottom_left"
    frame_info_size: int = 10
    frame_info_margin: int = 5

    # Output Format
    frame_format: str = "jpg"
    output_quality: int = 95
    preview_quality: int = 50
    save_metadata_json: bool = False

@dataclass
class ProjectState:
    """
    Represents a snapshot of the application state for Undo/Redo.
    """
    settings: ProjectSettings = field(default_factory=ProjectSettings)
    thumbnail_metadata: List[Dict[str, Any]] = field(default_factory=list)
    thumbnail_layout_data: List[Dict[str, Any]] = field(default_factory=list)

    def clone(self):
        return copy.deepcopy(self)

class StateManager:
    def __init__(self):
        self._current_state = ProjectState()
        self._history_stack: List[ProjectState] = []
        self._redo_stack: List[ProjectState] = []
        self._max_history = 20
        self._in_transaction = False

    def get_state(self) -> ProjectState:
        return self._current_state

    def get_settings(self) -> ProjectSettings:
        return self._current_state.settings

    def update_settings(self, settings_update: Dict[str, Any], commit: bool = True):
        """
        Updates specific settings fields.
        if commit=True, saves a snapshot to history BEFORE updating.
        """
        if commit and not self._in_transaction:
            self.snapshot()
            
        current_settings = self._current_state.settings
        for key, value in settings_update.items():
            if hasattr(current_settings, key):
                setattr(current_settings, key, value)

    def snapshot(self):
        """Saves current state to history."""
        self._push_to_history()
        self._redo_stack.clear()

    def _push_to_history(self):
        self._history_stack.append(self._current_state.clone())
        if len(self._history_stack) > self._max_history:
            self._history_stack.pop(0)

    def undo(self) -> Optional[ProjectState]:
        if not self._history_stack:
            return None
        self._redo_stack.append(self._current_state)
        self._current_state = self._history_stack.pop()
        return self._current_state

    def redo(self) -> Optional[ProjectState]:
        if not self._redo_stack:
            return None
        self._history_stack.append(self._current_state)
        self._current_state = self._redo_stack.pop()
        return self._current_state