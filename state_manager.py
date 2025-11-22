import copy
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Any, Optional

# --- Integration Guide for movieprint_gui.py ---
#
# 1. Import the StateManager:
#    from state_manager import StateManager, ProjectSettings, ProjectState
#
# 2. In MoviePrintApp.__init__, replace self._init_variables() with:
#    self.state_manager = StateManager()
#    
# 3. Replacing 'self.thumbnail_metadata' and 'self.cached_pool_metadata':
#    - Access state via: state = self.state_manager.get_state()
#    - Access metadata: current_grid = state.thumbnail_metadata
#
# 4. Handling Discrete Updates (e.g., Layout Change):
#    - When a single atomic action occurs:
#      # 1. Capture history first
#      self.state_manager.snapshot() 
#      
#      # 2. Modify state directly (or create new object)
#      state = self.state_manager.get_state()
#      state.thumbnail_metadata = new_metadata
#
# 5. Handling Continuous Updates (Scrubbing):
#    - This is a "Transaction":
#    
#      # A. On Scrub Start (Mouse Button Down):
#      self.state_manager.snapshot() 
#      # (This saves the state *before* the scrub starts, so Undo will revert to this point)
#
#      # B. On Scrub Move (Mouse Drag):
#      state = self.state_manager.get_state()
#      state.thumbnail_metadata[index]['timestamp_sec'] = new_time
#      # (Modify in-place for performance. Do NOT call snapshot() here.)
#
#      # C. On Scrub Release (Mouse Button Up):
#      # No action needed on the manager, as the final state is already the "Current" state.
#      pass
#
# 6. Implementing Undo/Redo:
#    - Bind Ctrl+Z to: 
#      previous_state = self.state_manager.undo()
#      if previous_state: self.refresh_ui_from_state(previous_state)
# -----------------------------------------------

@dataclass
class ProjectSettings:
    """
    Holds all configuration settings that were previously Tkinter variables.
    """
    input_paths: List[str] = field(default_factory=list)
    output_dir: str = ""
    extraction_mode: str = "interval"  # 'interval', 'shot'
    interval_seconds: float = 5.0
    layout_mode: str = "grid"          # 'grid', 'timeline'
    num_columns: int = 5
    num_rows: int = 5
    use_gpu: bool = False
    background_color: str = "#000000"
    padding: int = 0
    grid_margin: int = 0
    # Add other settings as needed

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ProjectSettings':
        return cls(**{k: v for k, v in data.items() if k in cls.__annotations__})

@dataclass
class ProjectState:
    """
    Represents a snapshot of the entire application state at a specific point in time.
    """
    # The active configuration
    settings: ProjectSettings = field(default_factory=ProjectSettings)
    
    # The Source of Truth: All available frames extracted from the video
    cached_pool_metadata: List[Dict[str, Any]] = field(default_factory=list)
    
    # The View: The subset of frames currently displayed in the grid
    thumbnail_metadata: List[Dict[str, Any]] = field(default_factory=list)
    
    # Layout info (optional, can be recalculated, but good to cache)
    thumbnail_layout_data: List[Dict[str, Any]] = field(default_factory=list)

    def deep_copy(self) -> 'ProjectState':
        return copy.deepcopy(self)

class StateManager:
    """
    Manages the application state history (Undo/Redo).
    """
    def __init__(self):
        self._current_state = ProjectState()
        self._history_stack: List[ProjectState] = []
        self._redo_stack: List[ProjectState] = []
        self._max_history = 50  # Limit memory usage

    def get_state(self) -> ProjectState:
        """Returns the current state object. Modifying this object in-place affects the 'active' state."""
        return self._current_state

    def get_settings(self) -> ProjectSettings:
        return self._current_state.settings

    def update_settings(self, settings_update: Dict[str, Any], commit: bool = True):
        """Updates specific settings. If commit=True, snapshots the OLD state to history first."""
        if commit:
            self.snapshot()
            
        # Apply updates
        for key, value in settings_update.items():
            if hasattr(self._current_state.settings, key):
                setattr(self._current_state.settings, key, value)

    def update_state(self, new_state: ProjectState, commit: bool = True):
        """Replaces the entire state. If commit=True, snapshots the OLD state to history first."""
        if commit:
            self.snapshot()
            
        self._current_state = new_state

    def snapshot(self):
        """
        Push a deep copy of the CURRENT state to the history stack.
        Call this method BEFORE performing any destructive action or starting a transaction.
        """
        self._push_to_history()
        self._redo_stack.clear()

    def _push_to_history(self):
        """Internal: Pushes a deep copy of the current state to the history stack."""
        self._history_stack.append(self._current_state.deep_copy())
        if len(self._history_stack) > self._max_history:
            self._history_stack.pop(0)

    def undo(self) -> Optional[ProjectState]:
        """Reverts to the previous state. Returns the new current state or None if no history."""
        if not self._history_stack:
            return None
            
        # Push current state to redo stack
        self._redo_stack.append(self._current_state)
        
        # Pop from history and make it current
        self._current_state = self._history_stack.pop()
        return self._current_state

    def redo(self) -> Optional[ProjectState]:
        """Re-applies a previously undone state."""
        if not self._redo_stack:
            return None
            
        # Push current state to history
        self._history_stack.append(self._current_state)
        
        # Pop from redo and make it current
        self._current_state = self._redo_stack.pop()
        return self._current_state

    def can_undo(self) -> bool:
        return len(self._history_stack) > 0

    def can_redo(self) -> bool:
        return len(self._redo_stack) > 0
