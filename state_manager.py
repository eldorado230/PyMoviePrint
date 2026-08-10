import copy
import uuid
from dataclasses import asdict, dataclass, field, fields
from typing import Any, Dict, List, Optional


PROJECT_FORMAT = "pymovieprint-project"
PROJECT_VERSION = 1


@dataclass
class ProjectSettings:
    """All settings shared by the GUI, project files, and generation pipeline."""

    input_paths: List[str] = field(default_factory=list)
    recursive_scan: bool = False

    output_naming_mode: str = "suffix"
    output_filename_suffix: str = "_movieprint"
    output_filename: str = ""
    overwrite_mode: str = "overwrite"
    output_frames_only: bool = False
    individual_frames_output_dir: str = ""

    extraction_mode: str = "interval"
    interval_seconds: float = 5.0
    interval_frames: Optional[int] = None
    shot_threshold: float = 27.0

    layout_mode: str = "grid"
    num_columns: int = 5
    num_rows: int = 5
    target_row_height: int = 150

    fit_to_output_params: bool = False
    output_width: int = 1920
    output_height: int = 1080

    use_gpu: bool = False
    detect_faces: bool = False

    hdr_tonemap: bool = False
    hdr_algorithm: str = "hable"

    ui_theme: str = "Teal"
    background_color: str = "#1e1e1e"
    padding: int = 8
    grid_margin: int = 8
    # A nominal radius at 480 px thumbnail width. 18 gives MoviePrint-like cards.
    rounded_corners: int = 18
    rotate_thumbnails: int = 0

    # Non-destructive sheet-level video transforms. Crop values are percentages.
    crop_top: float = 0.0
    crop_right: float = 0.0
    crop_bottom: float = 0.0
    crop_left: float = 0.0
    crop_units: str = "percent"
    thumbnail_aspect_ratio: str = "source"

    # Workspace ordering/visibility. Individual thumbnails may override `hidden`.
    sort_mode: str = "timestamp"
    filter_mode: str = "visible"

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

    frame_format: str = "jpg"
    output_quality: int = 95
    preview_quality: int = 50
    save_metadata_json: bool = False

    @classmethod
    def from_dict(cls, values: Optional[Dict[str, Any]]):
        values = values if isinstance(values, dict) else {}
        allowed = {item.name for item in fields(cls)}
        return cls(**{key: value for key, value in values.items() if key in allowed})


def _new_sheet_id() -> str:
    return uuid.uuid4().hex


@dataclass
class MoviePrintSheet:
    """An editable movieprint sheet within a project workspace."""

    id: str = field(default_factory=_new_sheet_id)
    name: str = "Sheet 1"
    thumbnail_metadata: List[Dict[str, Any]] = field(default_factory=list)
    thumbnail_layout_data: List[Dict[str, Any]] = field(default_factory=list)
    settings: Dict[str, Any] = field(default_factory=dict)
    selected_thumbnail_id: Optional[str] = None
    in_point_sec: Optional[float] = None
    out_point_sec: Optional[float] = None

    def clone(self, *, new_identity: bool = False):
        result = copy.deepcopy(self)
        if new_identity:
            result.id = _new_sheet_id()
        return result

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, values: Optional[Dict[str, Any]]):
        values = values if isinstance(values, dict) else {}
        allowed = {item.name for item in fields(cls)}
        sheet = cls(**{key: value for key, value in values.items() if key in allowed})
        sheet.thumbnail_metadata = [dict(item) for item in sheet.thumbnail_metadata if isinstance(item, dict)]
        sheet.thumbnail_layout_data = [dict(item) for item in sheet.thumbnail_layout_data if isinstance(item, dict)]
        return sheet


@dataclass
class ProjectState:
    """A snapshot of the full editable workspace for undo/redo and project I/O."""

    settings: ProjectSettings = field(default_factory=ProjectSettings)
    # Retained for API compatibility; these mirror the active sheet.
    thumbnail_metadata: List[Dict[str, Any]] = field(default_factory=list)
    thumbnail_layout_data: List[Dict[str, Any]] = field(default_factory=list)
    project_name: str = "Untitled Project"
    source_paths: List[str] = field(default_factory=list)
    sheets: List[MoviePrintSheet] = field(default_factory=list)
    active_sheet_id: Optional[str] = None

    def __post_init__(self):
        if not self.sheets:
            sheet = MoviePrintSheet(
                thumbnail_metadata=copy.deepcopy(self.thumbnail_metadata),
                thumbnail_layout_data=copy.deepcopy(self.thumbnail_layout_data),
            )
            self.sheets = [sheet]
            self.active_sheet_id = sheet.id
        self.activate_sheet(self.active_sheet_id or self.sheets[0].id, save_current=False)

    def clone(self):
        self.sync_active_sheet()
        return copy.deepcopy(self)

    def active_sheet(self) -> MoviePrintSheet:
        for sheet in self.sheets:
            if sheet.id == self.active_sheet_id:
                return sheet
        self.active_sheet_id = self.sheets[0].id
        return self.sheets[0]

    def sync_active_sheet(self):
        sheet = self.active_sheet()
        sheet.thumbnail_metadata = copy.deepcopy(self.thumbnail_metadata)
        sheet.thumbnail_layout_data = copy.deepcopy(self.thumbnail_layout_data)
        sheet.settings = asdict(self.settings)

    def activate_sheet(self, sheet_id: str, *, save_current: bool = True) -> MoviePrintSheet:
        if save_current and self.sheets:
            self.sync_active_sheet()
        target = next((sheet for sheet in self.sheets if sheet.id == sheet_id), None)
        if target is None:
            raise KeyError(f"Unknown sheet: {sheet_id}")
        self.active_sheet_id = target.id
        if target.settings:
            self.settings = ProjectSettings.from_dict(target.settings)
        self.thumbnail_metadata = copy.deepcopy(target.thumbnail_metadata)
        self.thumbnail_layout_data = copy.deepcopy(target.thumbnail_layout_data)
        return target

    def to_dict(self) -> Dict[str, Any]:
        self.sync_active_sheet()
        return {
            "format": PROJECT_FORMAT,
            "version": PROJECT_VERSION,
            "project_name": self.project_name,
            "source_paths": list(self.source_paths or self.settings.input_paths),
            "active_sheet_id": self.active_sheet_id,
            "settings": asdict(self.settings),
            "sheets": [sheet.to_dict() for sheet in self.sheets],
        }

    @classmethod
    def from_dict(cls, values: Dict[str, Any]):
        if not isinstance(values, dict):
            raise ValueError("Project data must be a JSON object.")
        if values.get("format") not in (None, PROJECT_FORMAT):
            raise ValueError("This is not a PyMoviePrint project.")
        version = int(values.get("version", 1))
        if version > PROJECT_VERSION:
            raise ValueError(f"Project version {version} is newer than this app supports.")
        sheets = [MoviePrintSheet.from_dict(item) for item in values.get("sheets", []) if isinstance(item, dict)]
        state = cls(
            settings=ProjectSettings.from_dict(values.get("settings")),
            project_name=str(values.get("project_name") or "Untitled Project"),
            source_paths=[str(path) for path in values.get("source_paths", []) if path],
            sheets=sheets,
            active_sheet_id=values.get("active_sheet_id"),
        )
        if state.active_sheet_id not in {sheet.id for sheet in state.sheets}:
            state.active_sheet_id = state.sheets[0].id
        state.activate_sheet(state.active_sheet_id, save_current=False)
        return state


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

    def replace_state(self, state: ProjectState, *, clear_history: bool = True):
        self._current_state = state.clone()
        if clear_history:
            self._history_stack.clear()
            self._redo_stack.clear()

    def update_settings(self, settings_update: Dict[str, Any], commit: bool = True):
        if commit and not self._in_transaction:
            self.snapshot()
        current_settings = self._current_state.settings
        for key, value in settings_update.items():
            if hasattr(current_settings, key):
                setattr(current_settings, key, value)

    def add_sheet(self, name: Optional[str] = None, *, duplicate_active: bool = False) -> MoviePrintSheet:
        self.snapshot()
        self._current_state.sync_active_sheet()
        if duplicate_active:
            sheet = self._current_state.active_sheet().clone(new_identity=True)
        else:
            sheet = MoviePrintSheet(settings=asdict(self._current_state.settings))
        sheet.name = name or f"Sheet {len(self._current_state.sheets) + 1}"
        self._current_state.sheets.append(sheet)
        self._current_state.activate_sheet(sheet.id)
        return sheet

    def remove_active_sheet(self) -> bool:
        if len(self._current_state.sheets) <= 1:
            return False
        self.snapshot()
        current_id = self._current_state.active_sheet_id
        index = next(i for i, item in enumerate(self._current_state.sheets) if item.id == current_id)
        del self._current_state.sheets[index]
        replacement = self._current_state.sheets[min(index, len(self._current_state.sheets) - 1)]
        self._current_state.activate_sheet(replacement.id, save_current=False)
        return True

    def switch_sheet(self, sheet_id: str) -> MoviePrintSheet:
        self.snapshot()
        return self._current_state.activate_sheet(sheet_id)

    def snapshot(self):
        self._current_state.sync_active_sheet()
        self._push_to_history()
        self._redo_stack.clear()

    def _push_to_history(self):
        self._history_stack.append(self._current_state.clone())
        if len(self._history_stack) > self._max_history:
            self._history_stack.pop(0)

    def undo(self) -> Optional[ProjectState]:
        if not self._history_stack:
            return None
        self._current_state.sync_active_sheet()
        self._redo_stack.append(self._current_state.clone())
        self._current_state = self._history_stack.pop()
        return self._current_state

    def redo(self) -> Optional[ProjectState]:
        if not self._redo_stack:
            return None
        self._current_state.sync_active_sheet()
        self._history_stack.append(self._current_state.clone())
        self._current_state = self._redo_stack.pop()
        return self._current_state
