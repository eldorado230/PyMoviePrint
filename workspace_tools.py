"""Sheet editing and export operations."""
import copy
import math
import os
import re
import tempfile
from argparse import Namespace
from dataclasses import asdict
from state_manager import ProjectSettings


def rename_sheet(state, name):
    name = str(name).strip()
    if not name:
        raise ValueError('Enter a sheet name.')
    if any(s.name == name and s.id != state.active_sheet_id for s in state.sheets):
        raise ValueError('Another sheet already has that name.')
    state.active_sheet().name = name


def move_thumbnail(state, source, destination):
    items = state.thumbnail_metadata
    if not (0 <= source < len(items) and 0 <= destination < len(items)):
        raise ValueError('Select a valid destination thumbnail.')
    order = []
    for display_index, entry in enumerate(state.thumbnail_layout_data or []):
        index = int(entry.get('source_index', display_index))
        if 0 <= index < len(items) and index not in order:
            order.append(index)
    order.extend(index for index in range(len(items)) if index not in order)
    source, destination = order.index(source), order.index(destination)
    items = [items[index] for index in order]
    items.insert(destination, items.pop(source))
    state.thumbnail_metadata = items
    state.settings.sort_mode = 'manual'
    state.thumbnail_layout_data = []
    state.sync_active_sheet()
    return destination


def scene_bounds(item, fps=25.0):
    start = float(item.get('scene_start_sec', item.get('timestamp_sec', 0)))
    end = item.get('scene_end_sec')
    if end is None:
        end = start + float(item.get('duration_frames', 0)) / fps
    end = float(end)
    if not math.isfinite(start) or not math.isfinite(end) or end <= start:
        raise ValueError('This thumbnail has no valid scene range. Build a shot-based sheet first.')
    return start, end


def split_scene(item, timestamp, fps=25.0):
    start, end = scene_bounds(item, fps)
    if not start < timestamp < end:
        raise ValueError('The cut must be inside the selected scene.')
    left, right = copy.deepcopy(item), copy.deepcopy(item)
    for result, a, b in ((left, start, timestamp), (right, timestamp, end)):
        result.update(scene_start_sec=a, scene_end_sec=b,
                      timestamp_sec=(a + b) / 2, duration_frames=round((b-a)*fps))
    return left, right


def merge_scenes(first, second, fps=25.0):
    if first.get('video_path') != second.get('video_path'):
        raise ValueError('Scenes must belong to the same source video.')
    start, boundary = scene_bounds(first, fps)
    next_start, end = scene_bounds(second, fps)
    if abs(boundary-next_start) > 1.0/fps:
        raise ValueError('Only adjacent scenes can be merged.')
    result = copy.deepcopy(first)
    result.update(scene_start_sec=start, scene_end_sec=end, timestamp_sec=(start+end)/2,
                  duration_frames=round((end-start)*fps))
    return result


def edl_text(items, title, fps=25.0):
    """CMX-style non-drop-frame EDL with contiguous record-side edits."""
    rate = round(fps)
    if rate not in (24, 25, 30, 50, 60):
        raise ValueError('EDL export supports nominal 24/25/30/50/60 fps.')
    def tc(frames):
        frames = max(0, int(frames))
        seconds, frame = divmod(frames, rate)
        minutes, sec = divmod(seconds, 60)
        hour, minute = divmod(minutes, 60)
        return f'{hour:02}:{minute:02}:{sec:02}:{frame:02}'
    clean_title = str(title).replace('\n', ' ').replace('\r', ' ')
    lines = [f'TITLE: {clean_title}', 'FCM: NON-DROP FRAME', '']
    record = 0
    visible = [item for item in items if not item.get('hidden')]
    if not visible:
        raise ValueError('There are no visible scenes to export.')
    for index, item in enumerate(visible, 1):
        start, end = scene_bounds(item, fps)
        a, b = round(start*fps), round(end*fps)
        length = b-a
        if length <= 0:
            raise ValueError('A scene is shorter than one frame.')
        lines.append(f'{index:03}  AX       V     C        {tc(a)} {tc(b)} {tc(record)} {tc(record+length)}')
        source = os.path.basename(item.get('video_path', '')).replace('\n', ' ').replace('\r', ' ')
        lines.extend([f'* FROM CLIP NAME: {source}', ''])
        record += length
    return '\n'.join(lines)


def save_edl(path, items, title, fps=25.0):
    text = edl_text(items, title, fps)
    fd, temporary = tempfile.mkstemp(prefix='.movieprint_', suffix='.edl',
                                     dir=os.path.dirname(os.path.abspath(path)))
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            stream.write(text)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.remove(temporary)


def safe_sheet_suffix(name):
    return re.sub(r'[^\w -]', '_', str(name)).strip(' .') or 'sheet'


def sheet_export_settings(sheet, destination, index):
    """Build an independent export job without changing the active GUI sheet."""
    settings = Namespace(**asdict(ProjectSettings.from_dict(sheet.settings)))
    metadata = [copy.deepcopy(item) for item in sheet.thumbnail_metadata if not item.get('hidden')]
    if not metadata:
        raise ValueError(f'{sheet.name}: there are no visible thumbnails.')
    sources = {item.get('video_path') for item in metadata}
    if len(sources) != 1 or None in sources:
        raise ValueError(f'{sheet.name}: every thumbnail must identify the same source video.')
    source = next(iter(sources))
    if not os.path.isfile(source):
        raise ValueError(f'{sheet.name}: source video is missing: {source}')
    settings.input_paths = [source]
    settings.output_dir = destination
    settings.output_naming_mode = 'custom'
    settings.output_filename = f'{index:03}_{safe_sheet_suffix(sheet.name)}.{settings.frame_format}'
    settings.sheet_name = sheet.name
    settings.rows, settings.columns = settings.num_rows, settings.num_columns
    settings.start_time, settings.end_time = sheet.in_point_sec, sheet.out_point_sec
    settings.manual_timestamps = [float(item.get('timestamp_sec', 0)) for item in metadata]
    settings.manual_thumbnail_metadata = metadata
    for item in metadata:
        item.pop('frame_path', None)
    for name in ('max_frames_for_print', 'temp_dir', 'haar_cascade_xml', 'exclude_frames',
                 'exclude_shots', 'max_output_filesize_kb', 'target_thumbnail_width', 'target_thumbnail_height'):
        setattr(settings, name, None)
    settings.output_image_width = settings.output_width
    settings.video_extensions = '.mp4,.avi,.mov,.mkv,.flv,.wmv'
    return settings
