import copy
from dataclasses import dataclass, field, replace
from typing import List, Dict, Any, Optional, ContextManager
from contextlib import contextmanager

# --- Integration Guide ---
#
# 1. Batch Updates (Sliders/Scrubbing):
#    with state_manager.transaction():
#        state = state_manager.get_state()
#        state.settings.num_columns = 10
#    # (Snapshot happens automatically only ONCE at the end of the 'with' block)
#
# 2. Atomic Updates:
#    state_manager.update_settings({'num_columns': 5})
# --------------------------

@dataclass
class ProjectSettings:
    """
    Holds all configuration settings. 
    Using slots for memory optimization if we had Python 3.10+, 
    but standard dataclass is fine here.
    """
    input_paths: List[str] = field(default_factory=list)
    output_dir: str = ""
    
    # NEW: Logic to save output to the same folder as the input video
    save_alongside_video: bool = True 
    
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
    output_filename_suffix: str = "-thumb"
    
    # Metadata
    save_metadata_json: bool = False  # Changed default to False per request

    def clone(self) -> 'ProjectSettings':
        """Create a shallow copy of settings (lists must be copied explicitly)."""
        new_obj = replace(self)
        new_obj.input_paths = list(self.input_paths)
        return new_obj

@dataclass
class ProjectState:
    """
    Represents a snapshot of the application state.
    """
    settings: ProjectSettings = field(default_factory=ProjectSettings)
    
    # The Source of Truth (All extracted frames)
    cached_pool_metadata: List[Dict[str, Any]] = field(default_factory=list)
    
    # The View (Currently displayed frames)
    thumbnail_metadata: List[Dict[str, Any]] = field(default_factory=list)
    
    # Layout info
    thumbnail_layout_data: List[Dict[str, Any]] = field(default_factory=list)

    def clone(self) -> 'ProjectState':
        """
        Creates a safe copy for the history stack.
        Optimized: We copy the lists, but we assume the Dict items inside are 
        treated as immutable in most ops.
        """
        return ProjectState(
            settings=self.settings.clone(),
            cached_pool_metadata=list(self.cached_pool_metadata),
            thumbnail_metadata=[d.copy() for d in self.thumbnail_metadata], # Shallow copy dicts to be safe
            thumbnail_layout_data=list(self.thumbnail_layout_data)
        )

class StateManager:
    """
    Manages application state with transaction support to prevent
    memory bloat during rapid UI updates (scrubbing).
    """
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
        """
        Context manager for grouping multiple updates into a single Undo step.
        Useful for sliders and scrubbing.
        """
        if self._in_transaction:
            yield
            return

        self.snapshot() # Save state BEFORE the changes start
        self._in_transaction = True
        try:
            yield
        finally:
            self._in_transaction = False
            # We do NOT snapshot again here. The snapshot represents the state 
            # *before* the transaction. The current state is the "live" result.

    def update_settings(self, settings_update: Dict[str, Any], commit: bool = True):
        """Updates settings. If commit=True, saves history."""
        if commit and not self._in_transaction:
            self.snapshot()
            
        for key, value in settings_update.items():
            if hasattr(self._current_state.settings, key):
                setattr(self._current_state.settings, key, value)

    def update_state(self, new_state: ProjectState, commit: bool = True):
        """Replaces the entire state."""
        if commit and not self._in_transaction:
            self.snapshot()
        self._current_state = new_state

    def snapshot(self):
        """Push current state to history."""
        # Prevent duplicates if state hasn't actually changed
        # (Simplified check - in production you might want a hash check)
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