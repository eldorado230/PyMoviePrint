import threading
import numpy as np
import pytest
from PIL import Image
import face_analysis


def test_face_groups_count_unique_frames():
    def face(values):
        return dict(descriptor=values, area_fraction=0.1, confidence=0.95)
    items = [dict(face_detection=dict(faces=[face([1, 0]), face([1, 0])])),
             dict(face_detection=dict(faces=[face([0.99, 0.01])])),
             dict(face_detection=dict(faces=[face([0, 1])] ))]
    face_analysis.assign_groups(items)
    assert items[0]['face_detection']['occurrences'] == 2
    assert items[1]['face_detection']['faces'][0]['group'] == 1
    assert items[2]['face_detection']['faces'][0]['group'] == 2


def test_local_models_execute_without_network(tmp_path, monkeypatch):
    directory = face_analysis.model_directory()
    if not all((directory/spec[0]).is_file() for spec in face_analysis.MODEL_SPECS):
        pytest.skip('Optional recognition models have not been downloaded')
    monkeypatch.setattr(face_analysis.urllib.request, 'urlopen', lambda *a, **k: pytest.fail('Unexpected network request'))
    path = tmp_path/'blank.jpg'
    Image.fromarray(np.zeros((320, 320, 3), dtype=np.uint8)).save(path)
    result = face_analysis.analyze([dict(frame_path=str(path))], threading.Event())
    assert result[0]['face_detection']['num_faces'] == 0
