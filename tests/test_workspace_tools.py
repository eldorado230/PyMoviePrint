import pytest

from state_manager import ProjectState, StateManager
import workspace_tools as tools


def scene(start=0, end=2, source='video.mp4'):
    return dict(scene_start_sec=start, scene_end_sec=end, timestamp_sec=(start+end)/2,
                video_path=source, frame_path='frame.jpg')


def test_rename_and_duplicate_name_rejected():
    manager = StateManager()
    tools.rename_sheet(manager.get_state(), 'Main')
    manager.add_sheet()
    with pytest.raises(ValueError):
        tools.rename_sheet(manager.get_state(), 'Main')
    with pytest.raises(ValueError):
        tools.rename_sheet(manager.get_state(), ' ')


def test_reorder_undo_and_project_roundtrip():
    manager = StateManager()
    state = manager.get_state()
    state.thumbnail_metadata = [{'id': str(i)} for i in range(3)]
    manager.snapshot()
    tools.move_thumbnail(state, 0, 2)
    assert [i['id'] for i in state.thumbnail_metadata] == ['1', '2', '0']
    assert state.settings.sort_mode == 'manual'
    restored = ProjectState.from_dict(state.to_dict())
    assert restored.thumbnail_metadata == state.thumbnail_metadata
    assert manager.undo().thumbnail_metadata[0]['id'] == '0'


def test_cut_merge_preserve_range_and_original():
    original = scene()
    left, right = tools.split_scene(original, 0.8, 25)
    assert left['duration_frames'] == 20
    assert right['duration_frames'] == 30
    merged = tools.merge_scenes(left, right, 25)
    assert tools.scene_bounds(merged) == (0, 2)
    assert original == scene()
    with pytest.raises(ValueError):
        tools.split_scene(original, 2, 25)
    with pytest.raises(ValueError):
        tools.merge_scenes(left, scene(0.8, 2, 'other.mp4'), 25)
    with pytest.raises(ValueError):
        tools.merge_scenes(left, scene(1.0, 2), 25)


def test_edl_and_atomic_save(tmp_path, monkeypatch):
    items = [scene(1, 2), dict(scene(2, 3), hidden=True), scene(3, 4)]
    result = tools.edl_text(items, 'Cuts', 25)
    assert '00:00:01:00 00:00:02:00 00:00:00:00 00:00:01:00' in result
    assert result.count('FROM CLIP NAME') == 2
    target = tmp_path / 'cuts.edl'
    tools.save_edl(target, items, 'Cuts')
    old = target.read_bytes()
    monkeypatch.setattr(tools.os, 'replace', lambda *args: (_ for _ in ()).throw(OSError('locked')))
    with pytest.raises(OSError):
        tools.save_edl(target, [scene()], 'New')
    assert target.read_bytes() == old
    assert list(tmp_path.iterdir()) == [target]


def test_parent_sheet_survives_save():
    state = ProjectState()
    state.active_sheet().parent_sheet_id = 'parent'
    assert ProjectState.from_dict(state.to_dict()).active_sheet().parent_sheet_id == 'parent'


def test_reorder_uses_display_order_not_raw_timestamp_order():
    state = ProjectState()
    state.thumbnail_metadata = [{'id': str(i)} for i in range(3)]
    state.thumbnail_layout_data = [{'source_index': i} for i in (2, 1, 0)]
    assert tools.move_thumbnail(state, 2, 0) == 2
    assert [item['id'] for item in state.thumbnail_metadata] == ['1', '0', '2']
