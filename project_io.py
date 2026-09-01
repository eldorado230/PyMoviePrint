"""Portable, versioned PyMoviePrint project files and PNG project metadata."""

import json
import os
import struct
import zlib
from pathlib import Path
from typing import Any, Dict, Optional, Tuple
from urllib.parse import unquote

from PIL import Image, PngImagePlugin

from state_manager import PROJECT_FORMAT, PROJECT_VERSION, MoviePrintSheet, ProjectSettings, ProjectState


PNG_PROJECT_KEY = "pymovieprint.project"
MAX_PROJECT_BYTES = 8 * 1024 * 1024


def _bounded_zlib_decompress(data: bytes) -> bytes:
    """Decompress PNG text without allowing a small chunk to expand without limit."""
    decompressor = zlib.decompressobj()
    result = decompressor.decompress(data, MAX_PROJECT_BYTES + 1)
    if len(result) > MAX_PROJECT_BYTES or decompressor.unconsumed_tail or not decompressor.eof:
        raise ValueError("Compressed PNG project metadata exceeds the supported 8 MB limit.")
    return result


def _validated_json(raw: str) -> Dict[str, Any]:
    if len(raw.encode("utf-8")) > MAX_PROJECT_BYTES:
        raise ValueError("Project metadata is larger than the supported 8 MB limit.")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("Project data must be a JSON object.")
    return value


def save_project_json(path: str, state: ProjectState) -> str:
    target = os.path.abspath(path)
    if not target.lower().endswith(".json"):
        target += ".json"
    os.makedirs(os.path.dirname(target) or ".", exist_ok=True)
    payload = json.dumps(state.to_dict(), indent=2, ensure_ascii=False)
    temp_path = target + ".tmp"
    with open(temp_path, "w", encoding="utf-8") as handle:
        handle.write(payload)
    os.replace(temp_path, target)
    return target


def embed_project_in_png(image_path: str, state: ProjectState, output_path: Optional[str] = None) -> str:
    source = os.path.abspath(image_path)
    target = os.path.abspath(output_path or image_path)
    payload = json.dumps(state.to_dict(), separators=(",", ":"), ensure_ascii=False)
    if len(payload.encode("utf-8")) > MAX_PROJECT_BYTES:
        raise ValueError("Project metadata is larger than the supported 8 MB limit.")
    with Image.open(source) as image:
        pnginfo = PngImagePlugin.PngInfo()
        for key, value in image.info.items():
            if isinstance(value, str) and key != PNG_PROJECT_KEY:
                pnginfo.add_text(key, value)
        pnginfo.add_itxt(PNG_PROJECT_KEY, payload, zip=True)
        temp_path = target + ".tmp.png"
        image.save(temp_path, format="PNG", pnginfo=pnginfo, optimize=True)
    os.replace(temp_path, target)
    return target


def _official_movieprint_state(info: Dict[str, Any], project_path: str) -> Optional[ProjectState]:
    """Best-effort import of MoviePrint PNG metadata without depending on its runtime."""
    parsed: Dict[str, Any] = {}
    for key, value in info.items():
        if not isinstance(value, str):
            continue
        try:
            decoded = json.loads(value)
        except (json.JSONDecodeError, TypeError):
            decoded = value
        parsed[key.lower()] = decoded

    video_path = next((unquote(str(value)) for key, value in parsed.items() if "filepath" in key and isinstance(value, str)), "")
    frames = next((value for key, value in parsed.items() if "framenumberarray" in key and isinstance(value, list)), None)
    scenes = next((value for key, value in parsed.items() if "scenearray" in key and isinstance(value, list)), None)
    if not video_path and not frames and not scenes:
        return None

    metadata = []
    for index, frame_number in enumerate(frames or []):
        try:
            frame_number = int(frame_number)
        except (TypeError, ValueError):
            continue
        metadata.append({
            "id": f"imported-{index + 1}",
            "frame_number": frame_number,
            "video_path": video_path,
            "video_filename": os.path.basename(video_path),
            "frame_path": "",
            "needs_extraction": True,
        })
    if frames is None:
        for index, scene in enumerate(scenes or []):
            if not isinstance(scene, dict):
                continue
            try:
                frame_number = int(scene.get("frameNumber", scene.get("start", 0)))
                duration_frames = max(1, int(scene.get("length", 1)))
            except (TypeError, ValueError):
                continue
            metadata.append({
                "id": f"imported-scene-{index + 1}",
                "frame_number": frame_number,
                "duration_frames": duration_frames,
                "video_path": video_path,
                "video_filename": os.path.basename(video_path),
                "frame_path": "",
                "needs_extraction": True,
            })
    settings = ProjectSettings(input_paths=[video_path] if video_path else [])
    if frames is None and scenes:
        settings.extraction_mode = "shot"
        settings.layout_mode = "timeline"
    column_count = next((value for key, value in parsed.items() if "columncount" in key), None)
    try:
        if column_count is not None:
            settings.num_columns = max(1, int(column_count))
    except (TypeError, ValueError):
        pass
    transform = next((value for key, value in parsed.items() if "transformobject" in key and isinstance(value, dict)), {})
    settings.crop_top = float(transform.get("cropTop", 0.0) or 0.0)
    settings.crop_right = float(transform.get("cropRight", 0.0) or 0.0)
    settings.crop_bottom = float(transform.get("cropBottom", 0.0) or 0.0)
    settings.crop_left = float(transform.get("cropLeft", 0.0) or 0.0)
    if any((settings.crop_top, settings.crop_right, settings.crop_bottom, settings.crop_left)):
        settings.crop_units = "pixels"
    settings.rotate_thumbnails = {0: 90, 1: 180, 2: 270, 3: 0}.get(
        int(transform.get("rotationFlag", 3) or 0), 0
    )
    aspect_inv = transform.get("aspectRatioInv")
    if aspect_inv:
        try:
            aspect = 1.0 / float(aspect_inv)
            settings.thumbnail_aspect_ratio = min(
                ("16:9", "4:3", "1:1", "9:16"),
                key=lambda value: abs(aspect - (float(value.split(':')[0]) / float(value.split(':')[1]))),
            )
        except (TypeError, ValueError, ZeroDivisionError):
            pass
    state = ProjectState(
        settings=settings,
        project_name=Path(project_path).stem,
        source_paths=[video_path] if video_path else [],
        thumbnail_metadata=metadata,
    )
    return state


def _png_text_chunks(path: str) -> Dict[str, str]:
    """Read text chunks even when third-party PNGs place them after image data."""
    values: Dict[str, str] = {}
    with open(path, "rb") as handle:
        if handle.read(8) != b"\x89PNG\r\n\x1a\n":
            return values
        while True:
            length_raw = handle.read(4)
            if len(length_raw) != 4:
                break
            length = struct.unpack(">I", length_raw)[0]
            chunk_type = handle.read(4)
            if length > MAX_PROJECT_BYTES:
                handle.seek(length + 4, 1)
                continue
            data = handle.read(length)
            handle.read(4)  # CRC is validated by image decoders when rendered.
            try:
                if chunk_type == b"tEXt":
                    keyword, content = data.split(b"\0", 1)
                    values[keyword.decode("latin-1")] = content.decode("latin-1")
                elif chunk_type == b"zTXt":
                    keyword, compressed = data.split(b"\0\x00", 1)
                    values[keyword.decode("latin-1")] = _bounded_zlib_decompress(compressed).decode("utf-8")
                elif chunk_type == b"iTXt":
                    parts = data.split(b"\0", 5)
                    if len(parts) == 6:
                        keyword, compression_flag, _method, _language, _translated, content = parts
                        if compression_flag == b"\x01":
                            content = _bounded_zlib_decompress(content)
                        values[keyword.decode("latin-1")] = content.decode("utf-8")
            except (ValueError, UnicodeDecodeError, zlib.error):
                continue
            if chunk_type == b"IEND":
                break
    return values


def load_project(path: str) -> Tuple[ProjectState, str]:
    source = os.path.abspath(path)
    suffix = Path(source).suffix.lower()
    if suffix == ".json":
        with open(source, "r", encoding="utf-8") as handle:
            data = _validated_json(handle.read())
        if data.get("format") == PROJECT_FORMAT or "sheets" in data:
            return ProjectState.from_dict(data), "pymovieprint-json"

        official = _official_movieprint_state(data, source)
        if official:
            return official, "movieprint-json"

        # Import the older metadata sidecar produced by PyMoviePrint.
        video_path = str(data.get("source_video_processed") or "")
        settings = ProjectSettings.from_dict(data.get("generation_parameters"))
        settings.input_paths = [video_path] if video_path else settings.input_paths
        metadata = []
        for index, item in enumerate(data.get("thumbnails", [])):
            if not isinstance(item, dict):
                continue
            entry = dict(item)
            entry.setdefault("id", f"imported-{index + 1}")
            entry.setdefault("video_path", video_path)
            entry.setdefault("video_filename", os.path.basename(video_path))
            entry.setdefault("frame_path", "")
            entry["needs_extraction"] = not bool(entry.get("frame_path"))
            metadata.append(entry)
        return ProjectState(
            settings=settings,
            project_name=Path(source).stem,
            source_paths=[video_path] if video_path else [],
            thumbnail_metadata=metadata,
        ), "pymovieprint-metadata-json"

    if suffix != ".png":
        raise ValueError("Open a PyMoviePrint JSON project or MoviePrint PNG.")
    with Image.open(source) as image:
        info = dict(image.info)
    info.update(_png_text_chunks(source))
    raw = info.get(PNG_PROJECT_KEY)
    if raw:
        return ProjectState.from_dict(_validated_json(raw)), "pymovieprint-png"
    official = _official_movieprint_state(info, source)
    if official:
        return official, "movieprint-png"
    raise ValueError("This PNG does not contain editable MoviePrint project metadata.")


def project_summary(state: ProjectState) -> Dict[str, Any]:
    return {
        "format": PROJECT_FORMAT,
        "version": PROJECT_VERSION,
        "name": state.project_name,
        "sheets": len(state.sheets),
        "thumbnails": sum(len(sheet.thumbnail_metadata) for sheet in state.sheets),
        "sources": len(state.source_paths or state.settings.input_paths),
    }
