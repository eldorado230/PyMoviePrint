import copy
from dataclasses import dataclass, field, replace
from typing import List, Dict, Any, Optional, ContextManager
from contextlib import contextmanager

@dataclass
class ProjectSettings:
    """
    Holds all configuration settings. 
    """
    input_paths: List[str] = field(default_factory=list)
    
    # REMOVED: output_dir (We now strictly enforce save_alongside)
    # REMOVED: save_alongside_video (implicitly True always)
    
    # Extraction
    extraction_mode: str = "interval"
    interval_seconds: float = 5.0
    interval_frames: Optional[int] = None
    shot_threshold: float = 27.0
    
    # Layout
    layout_mode: str = "grid"
    num_columns: int = 5
    num_rows: int = 5
    target_row_height: int = 150
    
    # Processing
    use_gpu: bool = False
    detect_faces: bool = False
    
    # Styling
    background_color: str = "#1e1e1e"
    padding: int = 5
    grid_margin: int = 0
    rounded_corners: int = 0
    rotate_thumbnails: int = 0
    
    # Overlay Info
    show_header: bool = True
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
    
    # Output
    frame_format: str = "jpg"
    preview_quality: int = 75
    output_quality: int = 95
    max_frames_for_print: int = 100
    
    # Naming Scheme Configuration
    # 'suffix' = OriginalFilename + Suffix (Default)
    # 'custom' = Fixed Name (e.g., "backdrop")
    output_naming_mode: str = "suffix" 
    output_filename_suffix: str = "-thumb"
    output_filename: str = "" # Stores the custom fixed name (e.g. "backdrop")
    
    # Metadata
    save_metadata_json: bool = False

    def clone(self) -> 'ProjectSettings':
        """Create a shallow copy of settings."""
        new_obj = replace(self)
        new_obj.input_paths = list(self.input_paths)
        return new_obj

@dataclass
class ProjectState:
    settings: ProjectSettings = field(default_factory=ProjectSettings)
    cached_pool_metadata: List[Dict[str, Any]] = field(default_factory=list)
    thumbnail_metadata: List[Dict[str, Any]] = field(default_factory=list)
    thumbnail_layout_data: List[Dict[str, Any]] = field(default_factory=list)

    def clone(self) -> 'ProjectState':
        return ProjectState(
            settings=self.settings.clone(),
            cached_pool_metadata=list(self.cached_pool_metadata),
            thumbnail_metadata=[d.copy() for d in self.thumbnail_metadata],
            thumbnail_layout_data=list(self.thumbnail_layout_data)
        )

class StateManager:
    def __init__(self):
        self._current_state = ProjectState()
        self._history_stack: List[ProjectState] = []
        self._redo_stack: List[ProjectState] = []
        self._max_history = 50
        self._in_transaction = False

    def get_state(self) -> ProjectState:
        return self._current_state

    def get_settings(self) -> ProjectSettings:
        return self._current_state.settings

    @contextmanager
    def transaction(self):
        if self._in_transaction:
            yield
            return

        self.snapshot()
        self._in_transaction = True
        try:
            yield
        finally:
            self._in_transaction = False

    def update_settings(self, settings_update: Dict[str, Any], commit: bool = True):
        if commit and not self._in_transaction:
            self.snapshot()
            
        for key, value in settings_update.items():
            if hasattr(self._current_state.settings, key):
                setattr(self._current_state.settings, key, value)

    def update_state(self, new_state: ProjectState, commit: bool = True):
        if commit and not self._in_transaction:
            self.snapshot()
        self._current_state = new_state

    def snapshot(self):
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