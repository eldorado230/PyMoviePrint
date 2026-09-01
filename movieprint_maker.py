import argparse
import logging
import os
import shutil
import tempfile
import glob
import json
import re
import ntpath
try:
    import cv2
    CV2_IMPORT_ERROR = None
except ImportError as import_error:
    cv2 = None
    CV2_IMPORT_ERROR = import_error
import math
from version import __version__
from PIL import Image, ImageOps

try:
    import video_processing
    import image_grid
    import project_io
    from state_manager import ProjectSettings, ProjectState
except ImportError as e:
    print(f"Error importing modules: {e}")
    print("Please ensure 'video_processing.py' and 'image_grid.py' are in the same directory.")
    exit(1)

# --- Helpers ---


def _ensure_cv2_available(logger):
    if cv2 is not None:
        return
    message = (
        "OpenCV (cv2) is required for movieprint generation but failed to import. "
        f"Original error: {CV2_IMPORT_ERROR}"
    )
    logger.error(message)
    raise RuntimeError(message)


def parse_time_to_seconds(time_str):
    """Parses various time formats (HH:MM:SS, MM:SS, SS.ms) into seconds."""
    if time_str is None: return None
    time_str = str(time_str).strip()
    try:
        seconds = float(time_str)
        return seconds if seconds >= 0 else None
    except ValueError: pass
    match = re.fullmatch(r'(?:(\d+):)?([0-5]?\d):([0-5]?\d(?:\.\d+)?)', time_str)
    if match:
        parts = match.groups()
        h = int(parts[0]) if parts[0] else 0
        m = int(parts[1]); s = float(parts[2])
        if m >= 60 or s >= 60: return None
        return float(h * 3600 + m * 60 + s)
    return None

def discover_video_files(input_sources, valid_extensions_str, recursive_scan, logger):
    """Scans input paths (files or directories) for valid video files."""
    video_files_found = set()
    valid_extensions = [ext.strip().lower() for ext in valid_extensions_str.split(',')]
    
    for source_path in input_sources:
        abs_source_path = os.path.abspath(source_path)
        if not os.path.exists(abs_source_path):
            logger.warning(f"Input path not found: {abs_source_path}. Skipping.")
            continue
            
        if os.path.isfile(abs_source_path):
            _, file_ext = os.path.splitext(abs_source_path)
            if file_ext.lower() in valid_extensions: 
                video_files_found.add(abs_source_path)
            else: 
                logger.warning(f"File '{abs_source_path}' lacks recognized video extension. Skipping.")
                
        elif os.path.isdir(abs_source_path):
            logger.info(f"Scanning directory: {abs_source_path}{' (recursively)' if recursive_scan else ''}...")
            scan_pattern = os.path.join(abs_source_path, "**", "*") if recursive_scan else os.path.join(abs_source_path, "*")
            
            for item_path in glob.glob(scan_pattern, recursive=recursive_scan):
                if os.path.isfile(item_path):
                    _, file_ext = os.path.splitext(item_path)
                    if file_ext.lower() in valid_extensions: 
                        video_files_found.add(item_path)

    return sorted(list(video_files_found))

def get_effective_output_filename(video_path, settings):
    """Builds the output filename that will be used for a discovered video."""
    output_print_format = getattr(settings, 'frame_format', 'jpg').lower()
    if output_print_format not in ['jpg', 'png']:
        output_print_format = 'jpg'

    if getattr(settings, 'output_naming_mode', 'suffix') == 'custom':
        custom_name = getattr(settings, 'output_filename', '').strip()
        if custom_name:
            if (
                os.path.isabs(custom_name)
                or ntpath.isabs(custom_name)
                or ntpath.splitdrive(custom_name)[0]
                or '/' in custom_name
                or '\\' in custom_name
                or os.path.basename(custom_name) != custom_name
            ):
                raise ValueError(
                    "Custom output name must be a plain filename without folder or drive components."
                )
            base_name, ext = os.path.splitext(custom_name)
            if ext.lower() in ['.png', '.jpg', '.jpeg']:
                output_print_format = ext.lower().replace('.', '').replace('jpeg', 'jpg')
                custom_name = base_name
            return f"{custom_name}.{output_print_format}"

    base = os.path.splitext(os.path.basename(video_path))[0]
    suffix = getattr(settings, 'output_filename_suffix', '_movieprint')
    return f"{base}{suffix}.{output_print_format}"

def get_target_output_path(video_path, settings, effective_output_filename=None):
    """Returns the final file or folder path for a video's generated output."""
    configured_output_dir = getattr(settings, 'output_dir', None)
    if configured_output_dir:
        target_dir = os.path.abspath(configured_output_dir)
    else:
        target_dir = os.path.dirname(os.path.abspath(video_path))

    if effective_output_filename is None:
        effective_output_filename = get_effective_output_filename(video_path, settings)

    if getattr(settings, 'output_frames_only', False):
        final_path = os.path.join(target_dir, os.path.splitext(effective_output_filename)[0] + "_frames")
        if getattr(settings, 'individual_frames_output_dir', '').strip():
            base_dir = os.path.abspath(getattr(settings, 'individual_frames_output_dir').strip())
            final_path = os.path.join(base_dir, os.path.basename(final_path))
        return final_path

    return os.path.join(target_dir, effective_output_filename)

def find_output_path_collisions(video_files, settings):
    """Finds batch entries that would write to the same output path."""
    outputs_by_key = {}
    for video_path in video_files:
        output_path = get_target_output_path(video_path, settings)
        key = os.path.normcase(os.path.abspath(output_path))
        outputs_by_key.setdefault(key, {'output': output_path, 'videos': []})
        outputs_by_key[key]['videos'].append(video_path)

    return [group for group in outputs_by_key.values() if len(group['videos']) > 1]


def _is_cancelled(settings):
    """Return whether a GUI-owned batch cancellation has been requested."""
    cancel_event = getattr(settings, 'cancel_event', None)
    return bool(cancel_event and cancel_event.is_set())

def enforce_max_filesize(image_path, target_kb, logger):
    """Iteratively reduces image quality/size to meet a target file size (KB)."""
    if target_kb is None: return

    try:
        current_kb = os.path.getsize(image_path) / 1024.0
    except OSError as e:
        logger.error(f"  Error checking file size for {image_path}: {e}")
        return

    if current_kb <= target_kb:
        return

    try:
        with Image.open(image_path) as img:
            quality = 95
            width, height = img.size
            
            for _ in range(10): # Max 10 attempts
                scale = max(0.1, (target_kb / current_kb) ** 0.5)
                new_w = max(1, int(width * scale))
                new_h = max(1, int(height * scale))
                
                img_resized = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
                
                save_kwargs = {"optimize": True}
                ext = os.path.splitext(image_path)[1].lower()
                
                if ext in [".jpg", ".jpeg"]:
                    save_kwargs["quality"] = quality
                elif ext == ".png":
                    save_kwargs["compress_level"] = 9
                    
                img_resized.save(image_path, **save_kwargs)
                img_resized.close()
                
                current_kb = os.path.getsize(image_path) / 1024.0
                if current_kb <= target_kb:
                    logger.info(f"  Adjusted output size to {current_kb:.1f} KB <= {target_kb} KB.")
                    return
                
                # Degrade quality for next iteration
                width, height = img_resized.size
                if ext in [".jpg", ".jpeg"] and quality > 20:
                    quality -= 5
                    
            logger.warning(f"  Could not reduce file below {target_kb} KB. Final size: {current_kb:.1f} KB.")
    except Exception as e:
        logger.error(f"  Error reducing file size for {image_path}: {e}")

# --- Core Logic ---

def _setup_temp_directory(video_file_path, settings, logger):
    """Handles creation of the temporary directory for frames."""
    if settings.temp_dir:
        video_basename = os.path.splitext(os.path.basename(video_file_path))[0]
        try:
            os.makedirs(settings.temp_dir, exist_ok=True)
            temp_dir = tempfile.mkdtemp(
                prefix=f"movieprint_temp_{video_basename}_",
                dir=settings.temp_dir,
            )
            return temp_dir, True, None
        except OSError as error:
            return None, False, f"Error creating temporary directory: {error}"
    else:
        try:
            temp_dir = tempfile.mkdtemp(prefix=f"movieprint_{os.path.splitext(os.path.basename(video_file_path))[0]}_")
            return temp_dir, True, None
        except Exception as e:
            return None, False, f"Error creating temporary directory: {e}"

def _get_video_duration(video_path, logger):
    """Helper to get exact video duration using OpenCV."""
    _ensure_cv2_available(logger)
    try:
        cap = cv2.VideoCapture(video_path)
        if cap.isOpened():
            fps = cap.get(cv2.CAP_PROP_FPS)
            count = cap.get(cv2.CAP_PROP_FRAME_COUNT)
            cap.release()
            if fps > 0: return count / fps
    except Exception as e:
        logger.warning(f"Could not determine duration for {video_path}: {e}")
    return 0.0

def _timestamp_key(value):
    try:
        return round(float(value), 9)
    except (TypeError, ValueError):
        return None

def _merge_manual_thumbnail_metadata(metadata_list, settings, logger):
    """Restore preview/editor metadata onto freshly extracted final-quality frames."""
    requested_metadata = getattr(settings, 'manual_thumbnail_metadata', None)
    if not requested_metadata:
        return metadata_list

    by_timestamp = {}
    without_timestamp = []
    for extracted in metadata_list:
        key = _timestamp_key(extracted.get('timestamp_sec'))
        if key is None:
            without_timestamp.append(extracted)
        else:
            by_timestamp.setdefault(key, []).append(extracted)

    merged = []
    for requested in requested_metadata:
        if not isinstance(requested, dict):
            continue
        key = _timestamp_key(requested.get('timestamp_sec'))
        candidates = by_timestamp.get(key, []) if key is not None else []
        if candidates:
            extracted = candidates.pop(0)
        elif without_timestamp:
            extracted = without_timestamp.pop(0)
        else:
            logger.warning(
                "  Final extraction did not return the preview thumbnail at %r.",
                requested.get('timestamp_sec'),
            )
            continue

        combined = dict(extracted)
        for field, value in requested.items():
            if field in {'frame_path', 'video_path', 'video_filename'}:
                continue
            combined[field] = value

        # The final-quality extraction owns physical source information.
        for field in ('frame_path', 'video_path', 'video_filename', 'timestamp_sec', 'frame_number'):
            if field in extracted:
                combined[field] = extracted[field]
        merged.append(combined)

    leftovers = [item for values in by_timestamp.values() for item in values]
    leftovers.extend(without_timestamp)
    if leftovers:
        logger.warning(
            "  %d final frame(s) had no matching preview metadata; preserving them at the end.",
            len(leftovers),
        )
        merged.extend(leftovers)
    return merged

def _extract_frames(video_file_path, temp_dir, settings, start_sec, end_sec, logger, fast_preview=False):
    """Orchestrates frame extraction based on layout and extraction modes."""
    
    # HDR Settings
    hdr_tonemap = getattr(settings, 'hdr_tonemap', False)
    hdr_algo = getattr(settings, 'hdr_algorithm', 'hable')

    # 1. Manual Timestamps (from Scrubbing/GUI)
    if hasattr(settings, 'manual_timestamps') and settings.manual_timestamps:
        timestamps = [
            float(ts) for ts in settings.manual_timestamps
            if ts is not None
            and (start_sec is None or float(ts) >= start_sec)
            and (end_sec is None or float(ts) <= end_sec)
        ]
        logger.info(f"  Using {len(timestamps)} manual timestamps provided by GUI.")
        if not timestamps:
            return False, []
        success, extracted = video_processing.extract_frames_from_timestamps(
            video_path=video_file_path,
            timestamps=timestamps,
            output_folder=temp_dir,
            logger=logger,
            output_format=settings.frame_format,
            fast_preview=fast_preview,
            hdr_tonemap=hdr_tonemap,
            hdr_algorithm=hdr_algo,
            cancel_event=getattr(settings, 'cancel_event', None)
        )
        if success and extracted:
            extracted = _merge_manual_thumbnail_metadata(extracted, settings, logger)
        return success, extracted

    # 2. Grid Mode (Calculated Timestamps)
    if settings.layout_mode == "grid" and getattr(settings, 'columns', None) and getattr(settings, 'rows', None):
        logger.info("  Layout is Grid: Calculating exact timestamps for extraction.")
        
        duration = _get_video_duration(video_file_path, logger)
        range_start = start_sec if start_sec is not None else 0.0
        range_end = min(end_sec, duration) if end_sec is not None else duration
        if duration > 0 and range_start < range_end:
            total_frames = settings.columns * settings.rows
            step = (range_end - range_start) / (total_frames + 1)
            timestamps = [range_start + ((i + 1) * step) for i in range(total_frames)]
            
            return video_processing.extract_frames_from_timestamps(
                video_path=video_file_path, 
                timestamps=timestamps, 
                output_folder=temp_dir, 
                logger=logger, 
                output_format=settings.frame_format,
                fast_preview=fast_preview,
                hdr_tonemap=hdr_tonemap,
                hdr_algorithm=hdr_algo,
                cancel_event=getattr(settings, 'cancel_event', None)
            )

    # 3. Interval or Shot Mode (Fallback/Legacy)
    use_gpu = getattr(settings, 'use_gpu', False)
    
    if settings.extraction_mode == "interval":
        return video_processing.extract_frames(
            video_path=video_file_path, output_folder=temp_dir,
            interval_seconds=settings.interval_seconds, interval_frames=settings.interval_frames,
            output_format=settings.frame_format,
            start_time_sec=start_sec, end_time_sec=end_sec,
            use_gpu=use_gpu,
            fast_preview=fast_preview,
            logger=logger,
            hdr_tonemap=hdr_tonemap,
            hdr_algorithm=hdr_algo,
            cancel_event=getattr(settings, 'cancel_event', None)
        )
    elif settings.extraction_mode == "shot":
        return video_processing.extract_shot_boundary_frames(
            video_path=video_file_path, output_folder=temp_dir,
            output_format=settings.frame_format, detector_threshold=settings.shot_threshold,
            start_time_sec=start_sec if start_sec is not None else 0.0, end_time_sec=end_sec,
            logger=logger,
            hdr_tonemap=hdr_tonemap,
            hdr_algorithm=hdr_algo,
            cancel_event=getattr(settings, 'cancel_event', None)
        )
    
    return False, []

def _apply_exclusions(metadata_list, settings, logger):
    """Applies frame or shot exclusions based on settings."""
    initial_count = len(metadata_list)
    excluded_items_log = []

    if settings.extraction_mode == 'interval' and settings.exclude_frames:
        exclude_set = set(settings.exclude_frames)
        metadata_list = [item for item in metadata_list if item['frame_number'] not in exclude_set]

    elif settings.extraction_mode == 'shot' and settings.exclude_shots:
        exclude_set_0based = {idx - 1 for idx in settings.exclude_shots}
        metadata_list = [item for i, item in enumerate(metadata_list) if i not in exclude_set_0based]

    if len(metadata_list) < initial_count:
        logger.info(f"  Applied exclusions: {initial_count - len(metadata_list)} thumbnails removed.")

    return metadata_list, excluded_items_log

def _limit_frames_for_grid(metadata_list, settings, temp_dir, cleanup_temp, logger):
    """Limits the number of frames for the grid layout if max_frames is set."""
    if settings.layout_mode != "grid" or not hasattr(settings, 'max_frames_for_print') or \
            settings.max_frames_for_print is None or len(metadata_list) <= settings.max_frames_for_print:
        return metadata_list

    num_to_select = int(settings.max_frames_for_print)
    original_count = len(metadata_list)

    if num_to_select <= 0:
        logger.warning("  max_frames_for_print must be positive; no frames selected.")
        return []

    if num_to_select == 1:
        selected_metadata = [metadata_list[0]] if original_count > 0 else []
    else:
        indices_to_pick = [int(i * (original_count - 1) / (num_to_select - 1)) for i in range(num_to_select)]
        selected_metadata = [metadata_list[i] for i in sorted(list(set(indices_to_pick)))]

    if cleanup_temp:
        frames_to_keep_paths = {meta['frame_path'] for meta in selected_metadata}
        all_temp_paths = glob.glob(os.path.join(temp_dir, f"*.{settings.frame_format}"))
        for path in all_temp_paths:
            if path not in frames_to_keep_paths:
                try:
                    os.remove(path)
                except OSError as e:
                    logger.warning(f"  Could not remove temporary frame '{path}': {e}")

    return selected_metadata

def _process_thumbnails(metadata_list, settings, logger):
    """Collect analysis metadata without destructively changing extracted frames."""
    if settings.detect_faces:
        cascade_path = settings.haar_cascade_xml or os.path.join(
            cv2.data.haarcascades, 'haarcascade_frontalface_default.xml'
        )
        if os.path.exists(cascade_path):
            face_cascade = cv2.CascadeClassifier(cascade_path)
            if not face_cascade.empty():
                logger.info("  Performing face detection...")
                for meta in metadata_list:
                    try:
                        frame_img = cv2.imread(meta['frame_path'])
                        if frame_img is None:
                            continue
                        gray = cv2.cvtColor(frame_img, cv2.COLOR_BGR2GRAY)
                        faces = face_cascade.detectMultiScale(
                            gray, scaleFactor=1.1, minNeighbors=4, minSize=(20, 20)
                        )
                        meta['face_detection'] = {
                            'num_faces': len(faces),
                            'face_bboxes_thumbnail': [list(face) for face in faces],
                        }
                    except Exception as error:
                        logger.warning(
                            f"  Face detection failed for '{meta.get('frame_path')}': {error}"
                        )
    return metadata_list

def _generate_movieprint(metadata_list, settings, output_path, logger):
    """Generates the final image using image_grid."""
    items_for_grid = []
    for meta in metadata_list:
        if settings.layout_mode == "timeline" and float(meta.get('duration_frames') or 0) <= 0:
            continue
        item = dict(meta)
        item['image_path'] = meta['frame_path']
        if settings.layout_mode == "timeline":
            item['width_ratio'] = float(meta.get('duration_frames') or 1.0)
        items_for_grid.append(item)

    if not items_for_grid:
        return False, None, "No frames available for grid generation."

    grid_params = {
        'image_source_data': items_for_grid, 
        'output_path': output_path,
        'padding': settings.padding, 
        'background_color_hex': settings.background_color,
        'layout_mode': settings.layout_mode, 
        'logger': logger,
        'grid_margin': settings.grid_margin,
        'rounded_corners': settings.rounded_corners,
        'rotation': getattr(settings, 'rotate_thumbnails', 0),
        'crop_top': getattr(settings, 'crop_top', 0.0),
        'crop_right': getattr(settings, 'crop_right', 0.0),
        'crop_bottom': getattr(settings, 'crop_bottom', 0.0),
        'crop_left': getattr(settings, 'crop_left', 0.0),
        'thumbnail_aspect_ratio': getattr(settings, 'thumbnail_aspect_ratio', 'source'),
        'sort_mode': getattr(settings, 'sort_mode', 'timestamp'),
        'filter_mode': getattr(settings, 'filter_mode', 'visible'),
        'frame_info_show': settings.frame_info_show,
        'show_header': settings.show_header,
        'show_file_path': settings.show_file_path,
        'show_timecode': settings.show_timecode,
        'show_frame_num': settings.show_frame_num,
        'frame_info_timecode_or_frame': settings.frame_info_timecode_or_frame,
        'frame_info_font_color': settings.frame_info_font_color,
        'frame_info_bg_color': settings.frame_info_bg_color,
        'frame_info_position': settings.frame_info_position,
        'frame_info_size': settings.frame_info_size,
        'frame_info_margin': settings.frame_info_margin,
        'quality': getattr(settings, 'output_quality', 95),
        'header_title': metadata_list[0].get('video_filename', '') if metadata_list else '',
        # NEW PARAMS
        'fit_to_output_params': getattr(settings, 'fit_to_output_params', False),
        'output_width': getattr(settings, 'output_width', 1920),
        'output_height': getattr(settings, 'output_height', 1080)
    }
    
    if settings.layout_mode == "grid":
        grid_params.update({
            'rows': getattr(settings, 'rows', None),
            'columns': settings.columns,
            'target_thumbnail_width': getattr(settings, 'target_thumbnail_width', None)
        })
    elif settings.layout_mode == "timeline":
        grid_params.update({
            'target_row_height': settings.target_row_height
        })

    success, layout_data = image_grid.create_image_grid(**grid_params)
    if not success: return False, None, "Image generation failed."

    logger.info(f"  MoviePrint successfully saved to {output_path}")
    return True, layout_data, None


def _export_individual_frames(metadata_list, output_dir, settings, logger):
    """Atomically replace generated frame files while preserving unrelated contents."""
    output_dir = os.path.abspath(output_dir)
    parent_dir = os.path.dirname(output_dir)
    os.makedirs(parent_dir, exist_ok=True)
    if os.path.exists(output_dir) and not os.path.isdir(output_dir):
        return False, f"Frame export target exists but is not a folder: {output_dir}"

    frame_format = getattr(settings, 'frame_format', 'jpg').lower()
    staging_dir = tempfile.mkdtemp(prefix=".pymovieprint_frames_stage_", dir=parent_dir)
    backup_dir = None
    staged_names = []
    preserve_backup = False

    try:
        for idx, meta in enumerate(metadata_list, 1):
            source_path = meta.get('frame_path')
            if not source_path or not os.path.exists(source_path):
                continue

            timestamp = meta.get('timestamp_sec')
            if timestamp is None:
                target_name = f"frame_{idx:04d}.{frame_format}"
            else:
                safe_ts = str(round(float(timestamp), 3)).replace('.', 'p')
                target_name = f"frame_{idx:04d}_{safe_ts}s.{frame_format}"

            target_path = os.path.join(staging_dir, target_name)
            item_transform = meta.get('transform') if isinstance(meta.get('transform'), dict) else {}
            item_aspect = meta.get('aspect_ratio') or getattr(settings, 'thumbnail_aspect_ratio', 'source')
            has_transform = bool(item_transform) or any((
                getattr(settings, 'crop_top', 0.0),
                getattr(settings, 'crop_right', 0.0),
                getattr(settings, 'crop_bottom', 0.0),
                getattr(settings, 'crop_left', 0.0),
                getattr(settings, 'rotate_thumbnails', 0),
                item_aspect != 'source',
            ))
            if not has_transform:
                shutil.copy2(source_path, target_path)
            else:
                with Image.open(source_path) as source_image:
                    transform_config = image_grid.GridConfig(
                        output_path=target_path,
                        rotation=getattr(settings, 'rotate_thumbnails', 0),
                        crop_top=getattr(settings, 'crop_top', 0.0),
                        crop_right=getattr(settings, 'crop_right', 0.0),
                        crop_bottom=getattr(settings, 'crop_bottom', 0.0),
                        crop_left=getattr(settings, 'crop_left', 0.0),
                        thumbnail_aspect_ratio=getattr(settings, 'thumbnail_aspect_ratio', 'source'),
                    )
                    transformed = image_grid._apply_source_transform(source_image, meta, transform_config)
                    aspect = image_grid._aspect_value(
                        meta.get('aspect_ratio', transform_config.thumbnail_aspect_ratio)
                    )
                    if aspect:
                        target_w = transformed.width
                        target_h = max(1, round(target_w / aspect))
                        if target_h > transformed.height:
                            target_h = transformed.height
                            target_w = max(1, round(target_h * aspect))
                        transformed = ImageOps.fit(
                            transformed, (target_w, target_h), method=Image.Resampling.LANCZOS
                        )
                    save_kwargs = (
                        {'quality': getattr(settings, 'output_quality', 95)}
                        if frame_format in {'jpg', 'jpeg'} else {}
                    )
                    transformed.convert('RGB').save(target_path, **save_kwargs)
            staged_names.append(target_name)

        if not staged_names:
            return False, "No frames were exported."

        os.makedirs(output_dir, exist_ok=True)
        backup_dir = tempfile.mkdtemp(prefix=".pymovieprint_frames_backup_", dir=parent_dir)
        previous_names = [
            name for name in os.listdir(output_dir)
            if os.path.isfile(os.path.join(output_dir, name))
            and _is_generated_frame_name(name)
        ]
        committed_names = []

        try:
            for name in previous_names:
                os.replace(os.path.join(output_dir, name), os.path.join(backup_dir, name))
            for name in staged_names:
                os.replace(os.path.join(staging_dir, name), os.path.join(output_dir, name))
                committed_names.append(name)
        except OSError as error:
            logger.error("Could not commit frame export to %s: %s", output_dir, error)
            for name in committed_names:
                try:
                    os.remove(os.path.join(output_dir, name))
                except OSError:
                    logger.exception("Could not remove partially committed frame %s", name)
            for name in previous_names:
                backup_path = os.path.join(backup_dir, name)
                if os.path.exists(backup_path):
                    try:
                        os.replace(backup_path, os.path.join(output_dir, name))
                    except OSError:
                        preserve_backup = True
                        logger.exception("Could not restore previous frame export %s", name)
            return False, f"Could not replace previous frame export: {error}"

        logger.info(f"  Exported {len(staged_names)} individual frames to {output_dir}")
        return True, output_dir
    except (OSError, TypeError, ValueError) as error:
        logger.error("Could not stage frame export for %s: %s", output_dir, error)
        return False, f"Could not export individual frames: {error}"
    finally:
        shutil.rmtree(staging_dir, ignore_errors=True)
        if backup_dir and not preserve_backup:
            shutil.rmtree(backup_dir, ignore_errors=True)


def _is_generated_frame_name(name):
    return bool(re.fullmatch(
        r"frame_\d{4,}(?:_[0-9eE+p-]+s)?\.(?:jpe?g|png)",
        name,
        re.IGNORECASE,
    ))

def _clear_generated_frame_files(output_dir, logger):
    """Remove only PyMoviePrint-generated files from an existing frame-export folder."""
    if not os.path.isdir(output_dir):
        return False, f"Frame export target exists but is not a folder: {output_dir}"

    for name in os.listdir(output_dir):
        path = os.path.join(output_dir, name)
        if not os.path.isfile(path) or not _is_generated_frame_name(name):
            continue
        try:
            os.remove(path)
        except OSError as error:
            logger.error("Could not remove previous frame export %s: %s", path, error)
            return False, f"Could not clear previous frame export: {path}: {error}"

    return True, None

def _save_metadata(metadata_list, layout_data, settings, start_sec, end_sec, process_warnings, movieprint_path, logger, source_video_path=None):
    """Saves metadata JSON. STRICTLY DISABLED if save_metadata_json is False."""
    if not getattr(settings, 'save_metadata_json', False): return

    source_map = {meta['frame_path']: meta for meta in metadata_list}
    combined_thumb_meta = []
    
    for layout_item in layout_data:
        source_meta = source_map.get(layout_item['image_path'])
        if source_meta:
            final_meta = {k: source_meta.get(k) for k in [
                'video_filename', 'frame_number', 'timestamp_sec', 
                'duration_frames', 'face_detection'
            ] if source_meta.get(k) is not None}
            final_meta['layout_in_movieprint'] = {k: layout_item[k] for k in ['x', 'y', 'width', 'height']}
            combined_thumb_meta.append(final_meta)

    settings_copy = {k:v for k,v in vars(settings).items() if not k.startswith('_')}
    
    full_meta = {
        'movieprint_image_filename': os.path.basename(movieprint_path),
        'source_video_processed': os.path.abspath(source_video_path or settings.input_paths[0]),
        'generation_parameters': settings_copy,
        'thumbnails': combined_thumb_meta
    }
    
    json_path = os.path.splitext(movieprint_path)[0] + ".json"
    try:
        with open(json_path, 'w') as f: json.dump(full_meta, f, indent=4)
        logger.info(f"  Metadata JSON saved to {json_path}")
    except Exception as e: logger.error(f"  Error saving metadata JSON: {e}")

def process_single_video(video_file_path, settings, effective_output_filename, logger, fast_preview=False):
    """Main pipeline for processing a single video file."""
    logger.info(f"\nProcessing video: {video_file_path}...")

    if not shutil.which(video_processing.FFMPEG_BIN):
        return False, (
            "FFmpeg was not found on PATH. Install FFmpeg, restart PyMoviePrint, "
            "and confirm that 'ffmpeg -version' works in a terminal."
        )

    # 1. Path Resolution
    configured_output_dir = getattr(settings, 'output_dir', None)
    if configured_output_dir:
        target_output_dir = os.path.abspath(configured_output_dir)
        try:
            os.makedirs(target_output_dir, exist_ok=True)
        except OSError as e:
            return False, f"Cannot create output directory '{target_output_dir}': {e}"
    else:
        target_output_dir = os.path.dirname(os.path.abspath(video_file_path))

    frame_export_base_dir = ""
    if getattr(settings, 'output_frames_only', False):
        frame_export_base_dir = getattr(settings, 'individual_frames_output_dir', '').strip()
        if frame_export_base_dir:
            frame_export_base_dir = os.path.abspath(frame_export_base_dir)
            try:
                os.makedirs(frame_export_base_dir, exist_ok=True)
            except OSError as error:
                return False, f"Cannot create frame export directory '{frame_export_base_dir}': {error}"

    writable_output_dir = frame_export_base_dir or target_output_dir
    if not os.access(writable_output_dir, os.W_OK):
        return False, f"Cannot write to output directory: {writable_output_dir}. Permission denied."

    # 2. Parse Times
    start_sec = parse_time_to_seconds(settings.start_time)
    end_sec = parse_time_to_seconds(settings.end_time)
    
    if (settings.start_time and start_sec is None) or \
       (settings.end_time and end_sec is None) or \
       (start_sec is not None and end_sec is not None and start_sec >= end_sec):
        return False, "Invalid time segment settings."

    # 3. Setup Temp
    temp_dir, cleanup_temp, error = _setup_temp_directory(video_file_path, settings, logger)
    if error: return False, error

    try:
        # 4. Extraction
        extraction_ok, metadata_list = _extract_frames(
            video_file_path, temp_dir, settings, start_sec, end_sec, logger, fast_preview=fast_preview
        )
        if not extraction_ok or not metadata_list:
            return False, f"Frame extraction yielded no frames for {video_file_path}."

        # 5. Processing
        metadata_list, process_warnings = _apply_exclusions(metadata_list, settings, logger)
        metadata_list = _limit_frames_for_grid(metadata_list, settings, temp_dir, cleanup_temp, logger)
        metadata_list = _process_thumbnails(metadata_list, settings, logger)

        # 6. Generation / Export
        if getattr(settings, 'output_frames_only', False):
            final_path = os.path.join(target_output_dir, os.path.splitext(effective_output_filename)[0] + "_frames")
            if frame_export_base_dir:
                final_path = os.path.join(frame_export_base_dir, os.path.basename(final_path))

            overwrite_mode = getattr(settings, 'overwrite_mode', 'overwrite')
            if os.path.exists(final_path):
                if overwrite_mode == 'skip':
                    logger.info(f"Skipping frame export for {video_file_path} (Folder exists: {final_path})")
                    return True, final_path

            success, message_or_path = _export_individual_frames(metadata_list, final_path, settings, logger)
            if not success:
                return False, message_or_path
            return True, message_or_path

        final_path = os.path.join(target_output_dir, effective_output_filename)
        success, layout_data, error_msg = _generate_movieprint(metadata_list, settings, final_path, logger)
        if not success:
            return False, error_msg

        # 7. Post-Processing
        enforce_max_filesize(final_path, settings.max_output_filesize_kb, logger)
        if final_path.lower().endswith('.png'):
            try:
                project_settings = ProjectSettings.from_dict(vars(settings))
                project_settings.input_paths = [os.path.abspath(video_file_path)]
                project_settings.num_columns = int(getattr(settings, 'columns', 5) or 5)
                project_settings.num_rows = int(getattr(settings, 'rows', 5) or 5)
                project_state = ProjectState(
                    settings=project_settings,
                    project_name=os.path.splitext(os.path.basename(final_path))[0],
                    source_paths=[os.path.abspath(video_file_path)],
                    thumbnail_metadata=[
                        dict(item, id=item.get('id') or f"thumb-{index + 1}")
                        for index, item in enumerate(metadata_list)
                    ],
                    thumbnail_layout_data=layout_data or [],
                )
                project_io.embed_project_in_png(final_path, project_state)
            except (OSError, ValueError, TypeError) as error:
                logger.warning("  Could not embed editable project metadata: %s", error)
        if getattr(settings, 'save_metadata_json', False):
            _save_metadata(metadata_list, layout_data, settings, start_sec, end_sec, process_warnings, final_path, logger, source_video_path=video_file_path)

        return True, final_path

    finally:
        if cleanup_temp and os.path.exists(temp_dir):
            try: shutil.rmtree(temp_dir)
            except Exception: pass

def execute_movieprint_generation(settings, logger, progress_callback=None, fast_preview=False):
    """Entry point for batch processing."""
    _ensure_cv2_available(logger)
    logger.info("Starting PyMoviePrint generation process...")

    # 1. Discover Files (Recursive support via settings)
    video_files_to_process = discover_video_files(
        settings.input_paths,
        getattr(settings, 'video_extensions', ".mp4,.avi,.mov,.mkv,.flv,.wmv"),
        getattr(settings, 'recursive_scan', False),
        logger
    )

    if not video_files_to_process:
        logger.warning("No video files found to process.")
        return [], []

    successful_ops = []
    failed_ops = []
    total_videos = len(video_files_to_process)

    # Mode for overwriting
    overwrite_mode = getattr(settings, 'overwrite_mode', 'overwrite')

    # Protect CLI and GUI callers alike. A fixed name is valid across separate
    # source folders, but never when two sources target the same final path.
    try:
        collision_groups = find_output_path_collisions(video_files_to_process, settings)
    except ValueError as error:
        logger.error("Invalid output naming configuration: %s", error)
        return [], [
            {'video': video_path, 'reason': str(error)}
            for video_path in video_files_to_process
        ]
    colliding_videos = set()
    for group in collision_groups:
        colliding_videos.update(group['videos'])
        logger.error(
            "Output collision: %s would be written by: %s",
            group['output'],
            ", ".join(group['videos']),
        )

    for video_path in sorted(colliding_videos):
        failed_ops.append({
            'video': video_path,
            'reason': (
                "Output filename collision. Choose Add Suffix, change the Fixed Name, "
                "or process videos from this folder separately."
            ),
        })

    for i, video_path in enumerate(video_files_to_process):
        if _is_cancelled(settings):
            logger.info("Cancellation requested. Stopping before the next video.")
            setattr(settings, 'cancelled', True)
            break

        if progress_callback: progress_callback(i, total_videos, video_path)

        if video_path in colliding_videos:
            continue

        try:
            # Naming logic must be per-file so one bad custom name does not
            # leave the GUI worker stuck or obscure which source triggered it.
            effective_output_name = get_effective_output_filename(video_path, settings)
            full_output_path = get_target_output_path(video_path, settings, effective_output_name)

            if overwrite_mode == 'skip' and os.path.exists(full_output_path):
                logger.info(f"Skipping {video_path} (Output exists: {effective_output_name})")
                continue

            success, message_or_path = process_single_video(
                video_path, settings, effective_output_name, logger, fast_preview=fast_preview
            )
            if success: successful_ops.append({'video': video_path, 'output': message_or_path})
            else: failed_ops.append({'video': video_path, 'reason': message_or_path})
        except Exception as e:
            logger.exception(f"CRITICAL ERROR processing {video_path}: {e}")
            failed_ops.append({'video': video_path, 'reason': str(e)})

    if progress_callback: progress_callback(total_videos, total_videos, "Batch completed")
    return successful_ops, failed_ops

def main():
    parser = argparse.ArgumentParser(description="Create PyMoviePrints.")
    parser.add_argument('--version', action='version', version=f'%(prog)s {__version__}')
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    logger = logging.getLogger(__name__)

    # Inputs
    parser.add_argument("input_paths", nargs='+', help="Video files or directories.")
    parser.add_argument("output_dir", help="Destination folder for generated outputs.")
    
    # Naming
    parser.add_argument("--naming_mode", type=str, default="suffix", choices=["suffix", "custom"], dest="output_naming_mode")
    parser.add_argument("--output_filename_suffix", type=str, default="_movieprint")
    parser.add_argument("--output_filename", type=str, default=None)
    parser.add_argument("--overwrite_mode", type=str, default="overwrite", choices=["overwrite", "skip"], help="Action if output file exists.")

    # Batch
    batch_grp = parser.add_argument_group("Batch Processing")
    batch_grp.add_argument("--video_extensions", type=str, default=".mp4,.avi,.mov,.mkv,.flv,.wmv")
    batch_grp.add_argument("--recursive_scan", action="store_true", help="Recursively scan directories.")

    # Time
    time_grp = parser.add_argument_group("Time Segment")
    time_grp.add_argument("--start_time", type=str, default=None)
    time_grp.add_argument("--end_time", type=str, default=None)

    # Extraction
    ext_grp = parser.add_argument_group("Extraction")
    ext_grp.add_argument("--extraction_mode", type=str, default="interval", choices=["interval", "shot"])
    ext_grp.add_argument("--interval_seconds", type=float)
    ext_grp.add_argument("--interval_frames", type=int)
    ext_grp.add_argument("--shot_threshold", type=float, default=27.0)
    ext_grp.add_argument("--exclude_frames", type=int, nargs='+')
    ext_grp.add_argument("--exclude_shots", type=int, nargs='+')

    # Layout
    lay_grp = parser.add_argument_group("Layout")
    lay_grp.add_argument("--layout_mode", type=str, default="grid", choices=["grid", "timeline"])
    lay_grp.add_argument("--columns", type=int, default=5)
    lay_grp.add_argument("--rows", type=int, default=None)
    lay_grp.add_argument("--target_thumbnail_width", type=int, default=None)
    lay_grp.add_argument("--max_frames_for_print", type=int, default=None)
    lay_grp.add_argument("--target_row_height", type=int, default=100)
    
    # NEW: Dimensions
    lay_grp.add_argument("--fit_to_output_params", action="store_true")
    lay_grp.add_argument("--output_width", type=int, default=1920)
    lay_grp.add_argument("--output_height", type=int, default=1080)

    # Styling & Misc
    style_grp = parser.add_argument_group("Styling & Misc")
    style_grp.add_argument("--padding", type=int, default=8)
    style_grp.add_argument("--background_color", type=str, default="#FFFFFF")
    style_grp.add_argument("--frame_format", type=str, default="jpg", choices=["jpg", "png"])
    style_grp.add_argument("--temp_dir", type=str, default=None)
    style_grp.add_argument("--save_metadata_json", action="store_true")
    style_grp.add_argument("--detect_faces", action="store_true")
    style_grp.add_argument("--haar_cascade_xml", type=str, default=None)
    style_grp.add_argument("--rotate_thumbnails", type=int, default=0, choices=[0, 90, 180, 270])
    style_grp.add_argument("--max_output_filesize_kb", type=int, default=None)
    style_grp.add_argument("--use_gpu", action="store_true")
    style_grp.add_argument("--fast", "--draft", action="store_true", dest="fast_preview")
    style_grp.add_argument("--output_quality", type=int, default=95)
    style_grp.add_argument("--output_frames_only", action="store_true", help="Export individual selected frames instead of creating a combined MoviePrint image.")
    style_grp.add_argument("--individual_frames_output_dir", type=str, default="", help="Base directory for individual frame export folders.")
    
    # HDR / Color
    style_grp.add_argument("--hdr_tonemap", action="store_true")
    style_grp.add_argument("--hdr_algorithm", type=str, default="hable")
    
    # Frame Info / OSD
    style_grp.add_argument("--show_header", action="store_true", default=False)
    style_grp.add_argument("--show_file_path", dest="show_file_path", action="store_true", default=True)
    style_grp.add_argument("--hide_file_path", dest="show_file_path", action="store_false")
    style_grp.add_argument("--show_timecode", dest="show_timecode", action="store_true", default=True)
    style_grp.add_argument("--hide_timecode", dest="show_timecode", action="store_false")
    style_grp.add_argument("--show_frame_num", dest="show_frame_num", action="store_true", default=True)
    style_grp.add_argument("--hide_frame_num", dest="show_frame_num", action="store_false")
    style_grp.add_argument("--frame_info_show", action="store_true", default=False)
    style_grp.add_argument("--frame_info_timecode_or_frame", type=str, default="timecode")
    style_grp.add_argument("--frame_info_font_color", type=str, default="#FFFFFF")
    style_grp.add_argument("--frame_info_bg_color", type=str, default="#000000")
    style_grp.add_argument("--frame_info_position", type=str, default="bottom_left")
    style_grp.add_argument("--frame_info_size", type=int, default=10)
    style_grp.add_argument("--frame_info_margin", type=int, default=5)
    style_grp.add_argument("--rounded_corners", type=int, default=18)
    style_grp.add_argument("--grid_margin", type=int, default=8)
    style_grp.add_argument("--crop_top", type=float, default=0.0, help="Crop percent from the top edge.")
    style_grp.add_argument("--crop_right", type=float, default=0.0, help="Crop percent from the right edge.")
    style_grp.add_argument("--crop_bottom", type=float, default=0.0, help="Crop percent from the bottom edge.")
    style_grp.add_argument("--crop_left", type=float, default=0.0, help="Crop percent from the left edge.")
    style_grp.add_argument("--thumbnail_aspect_ratio", default="source", choices=["source", "16:9", "4:3", "1:1", "9:16"])

    args = parser.parse_args()

    # Validation
    if (
        args.layout_mode == "grid"
        and args.fit_to_output_params
        and args.rows is None
        and args.interval_seconds is None
        and args.interval_frames is None
    ):
        args.rows = 5
    if args.extraction_mode == "interval" and args.interval_seconds is None and args.interval_frames is None:
        if not (args.layout_mode == 'grid' and args.rows and args.columns):
             parser.error("Interval mode requires --interval_seconds or --interval_frames.")
    if args.interval_seconds is not None and args.interval_seconds <= 0:
        parser.error("--interval_seconds must be greater than zero.")
    if args.interval_frames is not None and args.interval_frames <= 0:
        parser.error("--interval_frames must be greater than zero.")
    if args.columns <= 0 or (args.rows is not None and args.rows <= 0):
        parser.error("--columns and --rows must be greater than zero.")
    if args.output_width <= 0 or args.output_height <= 0:
        parser.error("--output_width and --output_height must be greater than zero.")

    successful_ops, failed_ops = execute_movieprint_generation(
        settings=args,
        logger=logger,
        progress_callback=lambda c, t, f: print(f"Processing... {c}/{t}", end='\r'),
        fast_preview=args.fast_preview
    )

    logger.info("\n--- Processing Summary ---")
    if successful_ops: logger.info(f"Success: {len(successful_ops)}")
    if failed_ops:
        logger.info(f"Failed: {len(failed_ops)}")
        for f in failed_ops: logger.info(f" - {f['video']}: {f['reason']}")

    return 1 if failed_ops else 0

if __name__ == "__main__":
    raise SystemExit(main())
