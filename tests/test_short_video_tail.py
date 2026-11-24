import logging
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import movieprint_maker as maker
import video_processing as vp


pytestmark = pytest.mark.skipif(not shutil.which(vp.FFMPEG_BIN), reason="Requires FFmpeg")
LOG = logging.getLogger(__name__)


def make_clip(tmp_path, rate, filters=(), duration=1):
    path = tmp_path / 'short; clip.mp4'
    subprocess.run([
        vp.FFMPEG_BIN, '-v', 'error', '-f', 'lavfi', '-i',
        f'testsrc2=size=96x64:rate={rate}:duration={duration}',
        *filters, '-c:v', 'mpeg4', str(path),
    ], check=True, capture_output=True, timeout=20)
    return str(path)


@pytest.mark.parametrize('variable_rate', [False, True])
def test_grid_tail_matches_last_frame_in_preview_and_export(tmp_path, monkeypatch, variable_rate):
    monkeypatch.setenv('PYMOVIEPRINT_TIMESTAMP_GPU', 'off')
    if variable_rate:
        source = make_clip(tmp_path, 10, ['-vf', r'select=eq(n\,0)+eq(n\,1)+eq(n\,2)+eq(n\,9)',
                                         *vp.VideoUtils.frame_sync_args(vp.FFMPEG_BIN, 'vfr')])
        last_pts = 0.9
    else:
        source = make_clip(tmp_path, 4)
        last_pts = 0.75

    ok, reference = vp.extract_frames_from_timestamps(source, [last_pts], str(tmp_path / 'reference'), LOG)
    assert ok
    expected = Path(reference[0]['frame_path']).read_bytes()
    requested = [0.2, last_pts - 0.01, last_pts + 0.04, last_pts + 0.08]
    ok, preview = vp.extract_frames_from_timestamps(source, requested, str(tmp_path / 'preview'), LOG)
    assert ok and [item['timestamp_sec'] for item in preview] == requested
    assert all(Path(item['frame_path']).read_bytes() == expected for item in preview[1:])

    preview[-1].update(id='last', scene_start_sec=last_pts, scene_end_sec=1.0, duration_frames=1)
    settings = SimpleNamespace(manual_timestamps=requested, manual_thumbnail_metadata=preview, frame_format='jpg')
    ok, final = maker._extract_frames(source, str(tmp_path / 'export'), settings, None, None, LOG)
    assert ok and [item['timestamp_sec'] for item in final] == requested
    assert final[-1]['id'] == 'last'
    assert final[-1]['scene_start_sec'] == last_pts
    assert final[-1]['duration_frames'] == 1
    assert [Path(item['frame_path']).read_bytes() for item in final] == [
        Path(item['frame_path']).read_bytes() for item in preview
    ]

    grid = SimpleNamespace(extraction_mode='interval', layout_mode='grid', columns=6, rows=2, frame_format='jpg')
    ok, calculated = maker._extract_frames(source, str(tmp_path / 'grid'), grid, None, None, LOG)
    assert ok and len(calculated) == 12
    assert Path(calculated[-1]['frame_path']).read_bytes() == expected


def test_tail_seek_uses_source_time_with_a_longer_clip(tmp_path, monkeypatch):
    monkeypatch.setenv('PYMOVIEPRINT_TIMESTAMP_GPU', 'off')
    source = make_clip(tmp_path, 4, duration=5)
    with vp.VideoExtractor(source, LOG) as extractor:
        path = tmp_path / 'tail.jpg'
        options = ['-pix_fmt', 'yuvj420p', '-q:v', '2', '-f', 'image2']
        assert extractor._extract_video_tail(str(path), 'format=yuv420p', options, None) == 4.75
        assert path.stat().st_size > 0


def test_shot_with_only_last_frame_keeps_scene_bounds(tmp_path, monkeypatch):
    source = make_clip(tmp_path, 4)
    monkeypatch.setenv('PYMOVIEPRINT_TIMESTAMP_GPU', 'off')
    # PySceneDetect supplies frame-index boundaries, including an exclusive end.
    from scenedetect import FrameTimecode

    cuts = [FrameTimecode(frame, 4.0) for frame in (0, 3, 4)]
    manager = Mock()
    manager.get_scene_list.return_value = list(zip(cuts, cuts[1:]))
    monkeypatch.setattr(vp, 'SceneManager', lambda **kwargs: manager)
    ok, shots = vp.extract_shot_boundary_frames(source, str(tmp_path / 'shots'), LOG)
    assert ok
    assert [(item['scene_start_sec'], item['scene_end_sec']) for item in shots] == [(0, 0.75), (0.75, 1)]
    assert shots[-1]['timestamp_sec'] == 0.875
    assert shots[-1]['frame_number'] == 3


def test_shot_metadata_does_not_alias_nearby_timestamps(tmp_path, monkeypatch):
    from scenedetect import FrameTimecode

    source = make_clip(tmp_path, 4)
    cuts = [FrameTimecode(frame, 1000.0) for frame in (0, 1, 3)]
    manager = Mock()
    manager.get_scene_list.return_value = list(zip(cuts, cuts[1:]))
    monkeypatch.setattr(vp, 'SceneManager', lambda **kwargs: manager)

    def extract(self, timestamps, **kwargs):
        return [{'timestamp_sec': ts, 'frame_path': f'{i}.jpg'} for i, ts in enumerate(timestamps)]

    monkeypatch.setattr(vp.VideoExtractor, 'extract_timestamps_optimized', extract)
    ok, shots = vp.extract_shot_boundary_frames(source, str(tmp_path / 'shots'), LOG)
    assert ok
    assert [(item['frame_path'], item['scene_end_sec']) for item in shots] == [('0.jpg', .001), ('1.jpg', .003)]


def test_interval_longer_than_clip_still_has_an_initial_frame(tmp_path):
    source = make_clip(tmp_path, 4, duration=.25)
    ok, frames = vp.extract_frames(source, str(tmp_path / 'interval'), LOG, interval_seconds=1)
    assert ok and [item['timestamp_sec'] for item in frames] == [0]


@pytest.mark.parametrize('extension', ['jpg', 'png', 'webp'])
def test_an_empty_still_image_seek_is_recoverable(tmp_path, monkeypatch, extension):
    monkeypatch.setenv('PYMOVIEPRINT_TIMESTAMP_GPU', 'off')
    source = make_clip(tmp_path, 4)
    ok, frames = vp.extract_frames_from_timestamps(source, [0.875], str(tmp_path / 'frames'), LOG,
                                                   output_format=extension)
    assert ok and frames[0]['decoded_timestamp_sec'] == 0.75
    from PIL import Image
    with Image.open(frames[0]['frame_path']) as frame:
        frame.load()
        assert frame.size == (96, 64)


def test_failed_command_cannot_be_replaced_with_last_frame(tmp_path, monkeypatch):
    source = make_clip(tmp_path, 4)
    monkeypatch.setenv('PYMOVIEPRINT_TIMESTAMP_GPU', 'off')
    real_command = vp.VideoUtils.run_ffmpeg_command

    def run(cmd, logger, **kwargs):
        if cmd[cmd.index('-ss') + 1] == '0.95':
            # Trigger an actual FFmpeg failure by selecting an unknown encoder.
            cmd = [*cmd[:-5], '-c:v', 'missing_encoder', *cmd[-5:]]
        return real_command(cmd, logger, **kwargs)

    monkeypatch.setattr(vp.VideoUtils, 'run_ffmpeg_command', run)
    ok, frames = vp.extract_frames_from_timestamps(source, [0.85, 0.95], str(tmp_path / 'frames'), LOG)
    assert not ok and [frame['timestamp_sec'] for frame in frames] == [0.85]


def test_outside_scene_recovery_fails_shot_preview_and_manual_export(tmp_path, monkeypatch):
    from scenedetect import FrameTimecode

    source = make_clip(tmp_path, 4)
    monkeypatch.setenv('PYMOVIEPRINT_TIMESTAMP_GPU', 'off')
    # Simulate detector bounds that extend beyond the final decoded frame.
    cuts = [FrameTimecode(8, 10.0), FrameTimecode(10, 10.0)]
    manager = Mock()
    manager.get_scene_list.return_value = [tuple(cuts)]
    monkeypatch.setattr(vp, 'SceneManager', lambda **kwargs: manager)
    assert vp.extract_shot_boundary_frames(source, str(tmp_path / 'shots'), LOG) == (False, [])

    settings = SimpleNamespace(
        manual_timestamps=[0.9], frame_format='jpg',
        manual_thumbnail_metadata=[{'timestamp_sec': 0.9, 'scene_start_sec': 0.8, 'scene_end_sec': 1.0}],
    )
    assert maker._extract_frames(source, str(tmp_path / 'export'), settings, None, None, LOG) == (False, [])
