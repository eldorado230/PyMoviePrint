"""
State management for the PyMoviePrint application.

This module defines the data structures for project settings and state,
and provides a StateManager class to handle undo/redo functionality
and transactional updates.
"""

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
    Holds all configuration settings for a PyMoviePrint project.

    This data class stores settings related to input/output paths, frame extraction,
    layout configuration, processing options, styling, overlay information, and metadata.
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
        """
        Create a shallow copy of the settings object.

        Lists (like input_paths) are copied explicitly to ensure independence.

        Returns:
            ProjectSettings: A new instance with the same values.
        """
        new_obj = replace(self)
        new_obj.input_paths = list(self.input_paths)
        return new_obj

@dataclass
class ProjectState:
    """
    Represents a snapshot of the entire application state.

    This includes the current configuration settings as well as the data for
    extracted frames, currently displayed thumbnails, and layout information.
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
        Creates a deep-enough copy of the state for the history stack.

        Lists are copied, and dictionaries inside lists are shallow copied.
        Settings are cloned using their own clone method.

        Returns:
            ProjectState: A new instance representing the same state, suitable for archiving.
        """
        return ProjectState(
            settings=self.settings.clone(),
            cached_pool_metadata=list(self.cached_pool_metadata),
            thumbnail_metadata=[d.copy() for d in self.thumbnail_metadata], # Shallow copy dicts to be safe
            thumbnail_layout_data=list(self.thumbnail_layout_data)
        )

class StateManager:
    """
    Manages the application state, including undo/redo history and transactional updates.

    This class ensures that state changes can be tracked and reversed, and provides
    mechanisms to group multiple updates into single history entries (transactions).
    """
    def __init__(self):
        """
        Initialize the StateManager with a default state and empty history stacks.
        """
        self._current_state = ProjectState()
        self._history_stack: List[ProjectState] = []
        self._redo_stack: List[ProjectState] = []
        self._max_history = 50
        self._in_transaction = False

    def get_state(self) -> ProjectState:
        """
        Retrieve the current application state.

        Returns:
            ProjectState: The current state object.
        """
        return self._current_state

    def get_settings(self) -> ProjectSettings:
        """
        Retrieve the current project settings.

        Returns:
            ProjectSettings: The current settings object.
        """
        return self._current_state.settings

    @contextmanager
    def transaction(self):
        """
        Context manager for grouping multiple updates into a single Undo step.

        This is particularly useful for operations like slider movements or scrubbing,
        where many small updates happen in rapid succession but should be treated as
        one logical action from the user's perspective.

        Yields:
            None
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
        """
        Update specific settings in the current state.

        Args:
            settings_update (Dict[str, Any]): A dictionary of setting names and their new values.
            commit (bool): If True, saves the current state to history before applying changes.
                           Defaults to True.
        """
        if commit and not self._in_transaction:
            self.snapshot()

        for key, value in settings_update.items():
            if hasattr(self._current_state.settings, key):
                setattr(self._current_state.settings, key, value)

    def update_state(self, new_state: ProjectState, commit: bool = True):
        """
        Replace the entire current state with a new state object.

        Args:
            new_state (ProjectState): The new state object.
            commit (bool): If True, saves the current state to history before replacing it.
                           Defaults to True.
        """
        if commit and not self._in_transaction:
            self.snapshot()
        self._current_state = new_state

    def snapshot(self):
        """
        Push the current state to the history stack.

        This enables undo functionality. The redo stack is cleared whenever a new
        snapshot is created.
        """
        # Prevent duplicates if state hasn't actually changed
        # (Simplified check - in production you might want a hash check)
        self._push_to_history()
        self._redo_stack.clear()

    def _push_to_history(self):
        """
        Internal method to append a clone of the current state to the history stack.

        Enforces the maximum history size by removing oldest entries.
        """
        self._history_stack.append(self._current_state.clone())
        if len(self._history_stack) > self._max_history:
            self._history_stack.pop(0)

    def undo(self) -> Optional[ProjectState]:
        """
        Revert to the previous state in the history stack.

        Returns:
            Optional[ProjectState]: The previous state if available, otherwise None.
        """
        if not self._history_stack:
            return None

        self._redo_stack.append(self._current_state)
        self._current_state = self._history_stack.pop()
        return self._current_state

    def redo(self) -> Optional[ProjectState]:
        """
        Reapply a previously undone state.

        Returns:
            Optional[ProjectState]: The state from the redo stack if available, otherwise None.
        """
        if not self._redo_stack:
            return None

        self._history_stack.append(self._current_state)
        self._current_state = self._redo_stack.pop()
        return self._current_state
