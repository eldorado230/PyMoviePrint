from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import runpy
from threading import Barrier

import pytest

launcher = runpy.run_path(
    str(Path(__file__).resolve().parents[1] / 'windows' / 'installer_entry.py')
)
migrate_settings = launcher['migrate_settings']
preview_arguments = launcher['preview_arguments']


def test_migration_preserves_exact_bytes_and_source(tmp_path):
    legacy = tmp_path / 'prototype.json'
    official = tmp_path / 'official.json'
    payload = '{"input_paths_list": ["example; café.mp4"]}\n'.encode('utf-8')
    legacy.write_bytes(payload)

    assert migrate_settings(legacy, official)
    assert official.read_bytes() == legacy.read_bytes() == payload
    official.write_bytes(b'{"selected": true}')
    assert not migrate_settings(legacy, official)
    assert official.read_bytes() == b'{"selected": true}'


def test_migration_leaves_missing_or_invalid_settings_alone(tmp_path):
    legacy = tmp_path / 'prototype.json'
    official = tmp_path / 'official.json'
    assert not migrate_settings(legacy, official)
    for payload in (b'{', b'[]', b'\xff'):
        legacy.write_bytes(payload)
        assert not migrate_settings(legacy, official)
        assert legacy.read_bytes() == payload
        assert not official.exists()


def test_simultaneous_migration_only_creates_one_complete_file(tmp_path):
    legacy = tmp_path / 'prototype.json'
    official = tmp_path / 'official.json'
    payload = b'{"example": true}'
    legacy.write_bytes(payload)
    launching = Barrier(4)

    def launch(_):
        launching.wait(timeout=5)
        return migrate_settings(legacy, official)

    with ThreadPoolExecutor(max_workers=4) as pool:
        assert sum(pool.map(launch, range(4))) == 1
    assert official.read_bytes() == payload
    assert not list(tmp_path.glob('.settings-*'))


def test_explorer_launch_preserves_a_single_literal_path(tmp_path):
    path = tmp_path / 'Sample; café & 01.MP4'
    path.touch()
    assert preview_arguments([]) is None
    assert preview_arguments(['--preview', str(path)]) == path
    for arguments in (
        ['--preview', str(path), str(path)],
        ['--preview', path.name],
        ['--preview', str(tmp_path / 'missing.mp4')],
    ):
        with pytest.raises(ValueError):
            preview_arguments(arguments)
