"""Run GUI regressions in separate processes to isolate Tk's global state."""
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.skipif(sys.platform != 'win32', reason='Windows GUI regression checks')
@pytest.mark.parametrize('case', [
    'test_replacement_video_clears_trim_only_on_success_and_undo_restores[picker]',
    'test_replacement_video_clears_trim_only_on_success_and_undo_restores[typed]',
    'test_export_replacement_does_not_reuse_trim_but_batch_is_unchanged[Single Source]',
    'test_export_replacement_does_not_reuse_trim_but_batch_is_unchanged[Batch Queue]',
    'test_same_source_keeps_trim_and_failed_replacement_preserves_sheet',
    'test_theme_undo_matches_rendered_theme_and_controls',
    'test_toolbar_wraps_without_clipping_hidden_switch',
])
def test_ui_audit_fix(case):
    cases = Path(__file__).with_name('_ui_audit_cases.py')
    result = subprocess.run(
        [sys.executable, '-m', 'pytest', f'{cases}::{case}', '-q', '--tb=short', '--show-capture=no'],
        cwd=cases.parent.parent, capture_output=True, text=True, timeout=45)
    assert result.returncode == 0, result.stdout + result.stderr
