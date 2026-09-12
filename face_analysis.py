"""Optional, local-only YuNet/SFace analysis. No video or image uploads."""
import copy
import hashlib
import os
import tempfile
import urllib.request
from pathlib import Path

import numpy as np
from video_processing import cv2


MODEL_SPECS = (
    ('face_detection_yunet_2022mar.onnx', 'c97242ce7f2a554e288b50eabd9f5df957e78801',
     'face_detection_yunet', '50ef07f702a31741ca46a4c0d947773b64143b9362780237bf0d427d6c79bab7'),
    ('face_recognition_sface_2021dec.onnx', '47534e27c9851bb1128ccc0102f1145e27f23f98',
     'face_recognition_sface', '0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79'),
)


def model_directory():
    return Path.home() / '.pymovieprint' / 'models'


def ensure_models(cancel_event=None):
    directory = model_directory()
    directory.mkdir(parents=True, exist_ok=True)
    paths = []
    for name, revision, folder, digest in MODEL_SPECS:
        path = directory / name
        if path.exists() and hashlib.sha256(path.read_bytes()).hexdigest() == digest:
            paths.append(str(path))
            continue
        url = f'https://media.githubusercontent.com/media/opencv/opencv_zoo/{revision}/models/{folder}/{name}'
        fd, temporary = tempfile.mkstemp(prefix='.download_', dir=directory)
        try:
            checksum = hashlib.sha256()
            with os.fdopen(fd, 'wb') as output, urllib.request.urlopen(url, timeout=30) as response:
                while True:
                    if cancel_event is not None and cancel_event.is_set():
                        raise InterruptedError('Face model download cancelled.')
                    chunk = response.read(1024*256)
                    if not chunk:
                        break
                    checksum.update(chunk)
                    output.write(chunk)
            if checksum.hexdigest() != digest:
                raise ValueError(f'Model verification failed: {name}')
            os.replace(temporary, path)
            license_url = f'https://raw.githubusercontent.com/opencv/opencv_zoo/{revision}/models/{folder}/LICENSE'
            with urllib.request.urlopen(license_url, timeout=30) as response:
                (directory / f'{folder}_LICENSE.txt').write_bytes(response.read(100000))
            paths.append(str(path))
        finally:
            if os.path.exists(temporary):
                os.remove(temporary)
    return paths


def assign_groups(items, threshold=0.363):
    """Assign anonymous similarity groups; matches are suggestions, not identities."""
    prototypes = []
    for item in items:
        for face in item.get('face_detection', {}).get('faces', []):
            feature = np.asarray(face['descriptor'], dtype=np.float32).reshape(-1)
            norm = np.linalg.norm(feature)
            if not norm or not np.isfinite(norm):
                raise ValueError('Invalid face descriptor.')
            feature /= norm
            scores = [float(np.dot(feature, prototype)) for prototype in prototypes]
            best = int(np.argmax(scores)) if scores else -1
            if best < 0 or scores[best] < threshold:
                prototypes.append(feature)
                best = len(prototypes)-1
            face['group'] = best+1
    occurrences = {}
    for item in items:
        for group in {f['group'] for f in item.get('face_detection', {}).get('faces', [])}:
            occurrences[group] = occurrences.get(group, 0)+1
    for item in items:
        detection = item.get('face_detection', {})
        faces = detection.get('faces', [])
        for face in faces:
            face['occurrences'] = occurrences[face['group']]
        detection['max_face_size'] = max((f['area_fraction'] for f in faces), default=0)
        detection['confidence'] = max((f['confidence'] for f in faces), default=0)
        detection['occurrences'] = max((f['occurrences'] for f in faces), default=0)
        detection['group'] = min((f['group'] for f in faces), default=1000000)
    return items


def analyze(items, cancel_event, progress=None):
    detector_path, recognizer_path = ensure_models(cancel_event)
    detector = cv2.FaceDetectorYN_create(detector_path, '', (320, 320), 0.9, 0.3, 5000)
    recognizer = cv2.FaceRecognizerSF_create(recognizer_path, '')
    result = copy.deepcopy(items)
    for index, item in enumerate(result):
        if cancel_event.is_set():
            raise InterruptedError('Face analysis cancelled.')
        image = cv2.imread(item.get('frame_path', ''))
        if image is None:
            raise ValueError('A cached thumbnail is unavailable. Rebuild its preview before analysing faces.')
        height, width = image.shape[:2]
        scale = min(1.0, 960/max(width, height))
        image = cv2.resize(image, (max(1, round(width*scale)), max(1, round(height*scale))))
        detector.setInputSize((image.shape[1], image.shape[0]))
        if float(cv2.cvtColor(image, cv2.COLOR_BGR2GRAY).std()) < 1.0:
            detected = None
        else:
            _, detected = detector.detect(image)
        faces = []
        for face in ([] if detected is None else detected):
            aligned = recognizer.alignCrop(image, face)
            feature = recognizer.feature(aligned).reshape(-1)
            faces.append(dict(bbox=(face[:4]/scale).tolist(), confidence=float(face[-1]),
                              area_fraction=float(face[2]*face[3]/(image.shape[0]*image.shape[1])),
                              descriptor=feature.tolist()))
        item['face_detection'] = dict(num_faces=len(faces), faces=faces,
                                      face_bboxes_thumbnail=[f['bbox'] for f in faces])
        if progress:
            progress(index+1, len(result), os.path.basename(item.get('video_path', '')))
    assign_groups(result)
    # Group IDs suffice for workspace searches; don't persist face embeddings.
    for item in result:
        for face in item['face_detection']['faces']:
            face.pop('descriptor', None)
    return result
