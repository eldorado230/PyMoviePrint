import argparse
import logging
import os
import shutil
import tempfile
import glob
import json
import re
try:
    import cv2
    CV2_IMPORT_ERROR = None
except ImportError as import_error:
    cv2 = None
    CV2_IMPORT_ERROR = import_error
import math
from version import __version__
from PIL import Image

try:
    import video_processing
    import image_grid
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
        temp_dir = os.path.join(settings.temp_dir, f"movieprint_temp_{video_basename}")
        os.makedirs(temp_dir, exist_ok=True)
        return temp_dir, False, None
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

def _extract_frames(video_file_path, temp_dir, settings, start_sec, end_sec, logger, fast_preview=False):
    """Orchestrates frame extraction based on layout and extraction modes."""
    
    # HDR Settings
    hdr_tonemap = getattr(settings, 'hdr_tonemap', False)
    hdr_algo = getattr(settings, 'hdr_algorithm', 'hable')

    # 1. Manual Timestamps (from Scrubbing/GUI)
    if hasattr(settings, 'manual_timestamps') and settings.manual_timestamps:
        logger.info(f"  Using {len(settings.manual_timestamps)} manual timestamps provided by GUI.")
        return video_processing.extract_frames_from_timestamps(
            video_path=video_file_path, 
            timestamps=settings.manual_timestamps, 
            output_folder=temp_dir, 
            logger=logger, 
            output_format=settings.frame_format,
            fast_preview=fast_preview,
            hdr_tonemap=hdr_tonemap,
            hdr_algorithm=hdr_algo
        )

    # 2. Grid Mode (Calculated Timestamps)
    if settings.layout_mode == "grid" and getattr(settings, 'columns', None) and getattr(settings, 'rows', None):
        logger.info("  Layout is Grid: Calculating exact timestamps for extraction.")
        
        duration = _get_video_duration(video_file_path, logger)
        if duration > 0:
            total_frames = settings.columns * settings.rows
            step = duration / (total_frames + 1)
            timestamps = [(i + 1) * step for i in range(total_frames)]
            
            return video_processing.extract_frames_from_timestamps(
                video_path=video_file_path, 
                timestamps=timestamps, 
                output_folder=temp_dir, 
                logger=logger, 
                output_format=settings.frame_format,
                fast_preview=fast_preview,
                hdr_tonemap=hdr_tonemap,
                hdr_algorithm=hdr_algo
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
            hdr_algorithm=hdr_algo
        )
    elif settings.extraction_mode == "shot":
        if hdr_tonemap:
            logger.warning("  [Limit] HDR Tone Mapping is not yet supported in Shot Extraction mode. Output may look washed out.")
        
        return video_processing.extract_shot_boundary_frames(
            video_path=video_file_path, output_folder=temp_dir,
            output_format=settings.frame_format, detector_threshold=settings.shot_threshold,
            start_time_sec=start_sec, end_time_sec=end_sec,
            logger=logger
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

    num_to_select = settings.max_frames_for_print
    original_count = len(metadata_list)
    
    indices_to_pick = [int(i * (original_count - 1) / (num_to_select - 1)) for i in range(num_to_select)]
    if num_to_select == 1 and original_count > 0:
        indices_to_pick = [0]

    selected_metadata = [metadata_list[i] for i in sorted(list(set(indices_to_pick)))]
    
    if cleanup_temp:
        frames_to_keep_paths = {meta['frame_path'] for meta in selected_metadata}
        all_temp_paths = glob.glob(os.path.join(temp_dir, f"*.{settings.frame_format}"))
        for path in all_temp_paths:
            if path not in frames_to_keep_paths:
                try: os.remove(path)
                except OSError: pass

    return selected_metadata

def _process_thumbnails(metadata_list, settings, logger):
    """Applies Face Detection and Rotation."""
    
    # 1. Face Detection
    if settings.detect_faces:
        cascade_path = settings.haar_cascade_xml or os.path.join(cv2.data.haarcascades, 'haarcascade_frontalface_default.xml')
        if os.path.exists(cascade_path):
            face_cascade = cv2.CascadeClassifier(cascade_path)
            if not face_cascade.empty():
                logger.info("  Performing face detection...")
                for meta in metadata_list:
                    try:
                        frame_img = cv2.imread(meta['frame_path'])
                        if frame_img is None: continue
                        gray = cv2.cvtColor(frame_img, cv2.COLOR_BGR2GRAY)
                        faces = face_cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=4, minSize=(20, 20))
                        meta['face_detection'] = {'num_faces': len(faces), 'face_bboxes_thumbnail': [list(f) for f in faces]}
                    except Exception: pass

    # 2. Rotation
    if settings.rotate_thumbnails != 0:
        rot_flag = {90: cv2.ROTATE_90_CLOCKWISE, 180: cv2.ROTATE_180, 270: cv2.ROTATE_90_COUNTERCLOCKWISE}.get(settings.rotate_thumbnails)
        if rot_flag is not None:
            logger.info(f"  Rotating thumbnails by {settings.rotate_thumbnails}°...")
            for meta in metadata_list:
                try:
                    thumb_img = cv2.imread(meta['frame_path'])
                    if thumb_img is None: continue
                    rotated = cv2.rotate(thumb_img, rot_flag)
                    cv2.imwrite(meta['frame_path'], rotated)
                except Exception: pass

    return metadata_list

def _generate_movieprint(metadata_list, settings, output_path, logger):
    """Generates the final image using image_grid."""
    items_for_grid = []
    if settings.layout_mode == "timeline":
        items_for_grid = [{'image_path': sm['frame_path'], 'width_ratio': float(sm.get('duration_frames', 1.0))}
                          for sm in metadata_list if sm.get('duration_frames', 0) > 0]
    else:
        items_for_grid = [meta['frame_path'] for meta in metadata_list]

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
            'target_row_height': settings.target_row_height,
            'max_grid_width': settings.output_image_width
        })

    success, layout_data = image_grid.create_image_grid(**grid_params)
    if not success: return False, None, "Image generation failed."

    logger.info(f"  MoviePrint successfully saved to {output_path}")
    return True, layout_data, None

def _save_metadata(metadata_list, layout_data, settings, start_sec, end_sec, process_warnings, movieprint_path, logger):
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
        'source_video_processed': os.path.abspath(settings.input_paths[0]),
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

    # 1. Path Resolution
    target_output_dir = os.path.dirname(os.path.abspath(video_file_path))
    if not os.access(target_output_dir, os.W_OK):
        return False, f"Cannot write to source directory: {target_output_dir}. Permission denied."

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

        # 6. Generation
        final_path = os.path.join(target_output_dir, effective_output_filename)
        success, layout_data, error_msg = _generate_movieprint(metadata_list, settings, final_path, logger)
        if not success: return False, error_msg

        # 7. Post-Processing
        enforce_max_filesize(final_path, settings.max_output_filesize_kb, logger)
        if getattr(settings, 'save_metadata_json', False):
            _save_metadata(metadata_list, layout_data, settings, start_sec, end_sec, process_warnings, final_path, logger)

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

    # Determine Format (Default jpg)
    output_print_format = "jpg"
    if hasattr(settings, 'frame_format') and settings.frame_format.lower() in ['jpg', 'png']:
        output_print_format = settings.frame_format.lower()

    # Handle custom filename extension override
    if getattr(settings, 'output_naming_mode', 'suffix') == 'custom':
        custom_name = getattr(settings, 'output_filename', '').strip()
        if custom_name:
            _, ext = os.path.splitext(custom_name)
            if ext.lower() in ['.png', '.jpg', '.jpeg']:
                output_print_format = ext.lower().replace('.', '').replace('jpeg','jpg')
                settings.output_filename = os.path.splitext(custom_name)[0]

    # Mode for overwriting
    overwrite_mode = getattr(settings, 'overwrite_mode', 'overwrite')

    for i, video_path in enumerate(video_files_to_process):
        if progress_callback: progress_callback(i, total_videos, video_path)

        # Naming Logic (Calculated early for skip check)
        naming_mode = getattr(settings, 'output_naming_mode', 'suffix')
        if naming_mode == 'custom' and getattr(settings, 'output_filename', ''):
            base_name = settings.output_filename
            effective_output_name = f"{base_name}.{output_print_format}"
        else:
            base = os.path.splitext(os.path.basename(video_path))[0]
            suffix = getattr(settings, 'output_filename_suffix', '_movieprint')
            effective_output_name = f"{base}{suffix}.{output_print_format}"

        # 2. Skip Check
        target_dir = os.path.dirname(os.path.abspath(video_path))
        full_output_path = os.path.join(target_dir, effective_output_name)
        
        if overwrite_mode == 'skip' and os.path.exists(full_output_path):
            logger.info(f"Skipping {video_path} (Output exists: {effective_output_name})")
            continue

        try:
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
    style_grp.add_argument("--padding", type=int, default=5)
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
    
    # HDR / Color
    style_grp.add_argument("--hdr_tonemap", action="store_true")
    style_grp.add_argument("--hdr_algorithm", type=str, default="hable")
    
    # Frame Info / OSD
    style_grp.add_argument("--show_header", action="store_true", default=False)
    style_grp.add_argument("--show_file_path", action="store_true", default=True)
    style_grp.add_argument("--show_timecode", action="store_true", default=True)
    style_grp.add_argument("--show_frame_num", action="store_true", default=True)
    style_grp.add_argument("--frame_info_show", action="store_true", default=False)
    style_grp.add_argument("--frame_info_timecode_or_frame", type=str, default="timecode")
    style_grp.add_argument("--frame_info_font_color", type=str, default="#FFFFFF")
    style_grp.add_argument("--frame_info_bg_color", type=str, default="#000000")
    style_grp.add_argument("--frame_info_position", type=str, default="bottom_left")
    style_grp.add_argument("--frame_info_size", type=int, default=10)
    style_grp.add_argument("--frame_info_margin", type=int, default=5)
    style_grp.add_argument("--rounded_corners", type=int, default=0)
    style_grp.add_argument("--grid_margin", type=int, default=0)

    args = parser.parse_args()

    # Validation
    if args.extraction_mode == "interval" and args.interval_seconds is None and args.interval_frames is None:
        if not (args.layout_mode == 'grid' and args.rows and args.columns):
             parser.error("Interval mode requires --interval_seconds or --interval_frames.")

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

if __name__ == "__main__":
    main()