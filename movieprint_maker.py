import argparse
import logging
import os
import shutil
import tempfile
import glob
import json
import re
import cv2
import math # For ceil, for frame selection
from version import __version__
from PIL import Image

try:
    import video_processing
    import image_grid
except ImportError as e:
    print(f"Error importing modules: {e}")
    print("Please ensure 'video_processing.py' and 'image_grid.py' are in the same directory"
          " or accessible in the Python path.")
    exit(1)

def parse_time_to_seconds(time_str):
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
    video_files_found = set()
    valid_extensions = [ext.strip().lower() for ext in valid_extensions_str.split(',')]
    for source_path in input_sources:
        abs_source_path = os.path.abspath(source_path)
        if not os.path.exists(abs_source_path):
            logger.warning(f"Input path not found: {abs_source_path}. Skipping.")
            continue
        if os.path.isfile(abs_source_path):
            _, file_ext = os.path.splitext(abs_source_path)
            if file_ext.lower() in valid_extensions: video_files_found.add(abs_source_path)
            else: logger.warning(f"File '{abs_source_path}' lacks recognized video extension. Skipping.")
        elif os.path.isdir(abs_source_path):
            logger.info(f"Scanning directory: {abs_source_path}{' (recursively)' if recursive_scan else ''}...")
            scan_pattern = os.path.join(abs_source_path, "**", "*") if recursive_scan else os.path.join(abs_source_path, "*")
            for item_path in glob.glob(scan_pattern, recursive=recursive_scan):
                if os.path.isfile(item_path):
                    _, file_ext = os.path.splitext(item_path)
                    if file_ext.lower() in valid_extensions: video_files_found.add(item_path)
        else: logger.warning(f"Input path '{abs_source_path}' not a file/directory. Skipping.")
    return sorted(list(video_files_found))

def enforce_max_filesize(image_path, target_kb, logger):
    if target_kb is None:
        return
    try:
        current_kb = os.path.getsize(image_path) / 1024.0
    except OSError as e:
        logger.error(f"  Error checking file size for {image_path}: {e}")
        return
    if current_kb <= target_kb:
        logger.info(f"  Output size {current_kb:.1f} KB already below target {target_kb} KB.")
        return
    try:
        with Image.open(image_path) as img:
            quality = 95
            width, height = img.size
            for _ in range(10):
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
                width, height = img_resized.size
                if ext in [".jpg", ".jpeg"] and quality > 20:
                    quality -= 5
            logger.warning(f"  Could not reduce file below {target_kb} KB. Final size: {current_kb:.1f} KB.")
    except Exception as e:
        logger.error(f"  Error reducing file size for {image_path}: {e}")


def _setup_temp_directory(video_file_path, settings, logger):
    """Handles creation of the temporary directory for frames."""
    if settings.temp_dir:
        video_basename = os.path.splitext(os.path.basename(video_file_path))[0]
        temp_dir = os.path.join(settings.temp_dir, f"movieprint_temp_{video_basename}")
        if not os.path.exists(temp_dir):
            try:
                os.makedirs(temp_dir)
            except OSError as e:
                return None, False, f"Error creating temp sub-dir {temp_dir}: {e}"
        return temp_dir, False, None  # Don't cleanup user-provided dir
    else:
        try:
            temp_dir = tempfile.mkdtemp(prefix=f"movieprint_{os.path.splitext(os.path.basename(video_file_path))[0]}_")
            logger.info(f"  Using temporary directory for frames: {temp_dir}")
            return temp_dir, True, None  # Cleanup this dir
        except Exception as e:
            return None, False, f"Error creating temporary directory: {e}"


def _extract_frames(video_file_path, temp_dir, settings, start_sec, end_sec, logger):
    """Extracts frames from the video based on settings."""
    if settings.extraction_mode == "interval":
        return video_processing.extract_frames(
            video_path=video_file_path, output_folder=temp_dir,
            interval_seconds=settings.interval_seconds, interval_frames=settings.interval_frames,
            output_format=settings.frame_format,
            start_time_sec=start_sec, end_time_sec=end_sec,
            logger=logger
        )
    elif settings.extraction_mode == "shot":
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
        original_frames = {item['frame_number'] for item in metadata_list}
        not_found = exclude_set - original_frames
        if not_found:
            msg = f"  Warning: Requested frames to exclude not found: {sorted(list(not_found))}"
            logger.warning(msg)
            excluded_items_log.append(msg)
        metadata_list = [item for item in metadata_list if item['frame_number'] not in exclude_set]
        if len(metadata_list) < initial_count:
            excluded_items_log.extend([f"excluded_frame_num:{fn}" for fn in exclude_set if fn in original_frames])

    elif settings.extraction_mode == 'shot' and settings.exclude_shots:
        exclude_set_0based = {idx - 1 for idx in settings.exclude_shots}
        valid_excluded = []
        temp_list = []
        for i, item in enumerate(metadata_list):
            if i not in exclude_set_0based:
                temp_list.append(item)
            else:
                valid_excluded.append(i + 1)
        metadata_list = temp_list
        for req_idx in settings.exclude_shots:
            if req_idx - 1 >= initial_count or req_idx <= 0:
                msg = f"  Warning: Shot index {req_idx} out of range (1-{initial_count})."
                logger.warning(msg)
                excluded_items_log.append(msg)
            elif req_idx in valid_excluded:
                excluded_items_log.append(f"excluded_shot_idx:{req_idx}")

    if len(metadata_list) < initial_count:
        logger.info(f"  Applied exclusions: {initial_count - len(metadata_list)} thumbnails removed. {len(metadata_list)} remaining.")

    return metadata_list, excluded_items_log


def _limit_frames_for_grid(metadata_list, settings, temp_dir, cleanup_temp, logger):
    """Limits the number of frames for the grid layout if max_frames is set."""
    if settings.layout_mode != "grid" or not hasattr(settings, 'max_frames_for_print') or \
            settings.max_frames_for_print is None or len(metadata_list) <= settings.max_frames_for_print:
        return metadata_list

    num_to_select = settings.max_frames_for_print
    original_count = len(metadata_list)
    logger.info(f"  Limiting {original_count} extracted frames to a maximum of {num_to_select} for the print.")

    indices_to_pick = [int(i * (original_count - 1) / (num_to_select - 1)) for i in range(num_to_select)]
    if num_to_select == 1 and original_count > 0:
        indices_to_pick = [0]

    selected_metadata = [metadata_list[i] for i in sorted(list(set(indices_to_pick)))]
    if len(selected_metadata) > num_to_select:
        selected_metadata = selected_metadata[:num_to_select]

    if cleanup_temp:
        frames_to_keep_paths = {meta['frame_path'] for meta in selected_metadata}
        all_temp_paths = glob.glob(os.path.join(temp_dir, f"*.{settings.frame_format}"))
        for path in all_temp_paths:
            if path not in frames_to_keep_paths:
                try:
                    os.remove(path)
                except OSError as e:
                    logger.warning(f"    Could not remove unselected temp frame {path}: {e}")

    logger.info(f"  Selected {len(selected_metadata)} frames to proceed with grid generation.")
    return selected_metadata


def _process_thumbnails(metadata_list, settings, logger):
    """Applies transformations like face detection and rotation to thumbnails."""
    # Face detection
    face_cascade = None
    if settings.detect_faces:
        cascade_path = settings.haar_cascade_xml or os.path.join(cv2.data.haarcascades, 'haarcascade_frontalface_default.xml')
        if not os.path.exists(cascade_path):
            logger.warning(f"  Warning: Haar Cascade XML not found at '{cascade_path}'. Face detection skipped.")
        else:
            face_cascade = cv2.CascadeClassifier(cascade_path)
            if face_cascade.empty():
                logger.warning(f"  Warning: Failed to load Haar Cascade from '{cascade_path}'. Face detection skipped.")
                face_cascade = None
            else:
                logger.info(f"  Face detection enabled using: {cascade_path}")

    if face_cascade:
        logger.info("  Performing face detection on thumbnails...")
        for meta in metadata_list:
            try:
                frame_img = cv2.imread(meta['frame_path'])
                if frame_img is None: continue
                gray = cv2.cvtColor(frame_img, cv2.COLOR_BGR2GRAY)
                faces = face_cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=4, minSize=(20, 20))
                meta['face_detection'] = {'num_faces': len(faces), 'face_bboxes_thumbnail': [list(f) for f in faces]}
                if len(faces) > 0:
                    logger.info(f"    Detected {len(faces)} face(s) in thumbnail from frame {meta.get('frame_number', 'N/A')}")
            except Exception as e:
                logger.error(f"    Error during face detection for {meta['frame_path']}: {e}")
                meta['face_detection'] = {'error': str(e)}

    # Rotation
    if settings.rotate_thumbnails != 0:
        logger.info(f"  Rotating thumbnails by {settings.rotate_thumbnails} degrees clockwise...")
        rot_flag = {90: cv2.ROTATE_90_CLOCKWISE, 180: cv2.ROTATE_180, 270: cv2.ROTATE_90_COUNTERCLOCKWISE}.get(settings.rotate_thumbnails)
        if rot_flag is not None:
            for meta in metadata_list:
                try:
                    thumb_img = cv2.imread(meta['frame_path'])
                    if thumb_img is None: continue
                    rotated = cv2.rotate(thumb_img, rot_flag)
                    if not cv2.imwrite(meta['frame_path'], rotated):
                        logger.warning(f"    Failed to save rotated image {meta['frame_path']}.")
                except Exception as e:
                    logger.error(f"    Error rotating {meta['frame_path']}: {e}")
                    meta['rotation_error'] = str(e)
        else:
            logger.warning(f"  Invalid rotation angle {settings.rotate_thumbnails}. Skipping rotation.")

    return metadata_list


def _generate_movieprint(metadata_list, settings, output_path, logger):
    """Generates the final movieprint image."""
    items_for_grid = []
    if settings.layout_mode == "timeline":
        items_for_grid = [{'image_path': sm['frame_path'], 'width_ratio': float(sm['duration_frames'])}
                          for sm in metadata_list if sm.get('duration_frames', 0) > 0]
    else:  # grid mode
        items_for_grid = [meta['frame_path'] for meta in metadata_list]

    if not items_for_grid:
        return False, None, "No frames/shots remaining for grid generation."

    logger.info(f"  Proceeding with {len(items_for_grid)} items for grid generation.")

    grid_params = {
        'image_source_data': items_for_grid, 'output_path': output_path,
        'padding': settings.padding, 'background_color_hex': settings.background_color,
        'layout_mode': settings.layout_mode, 'logger': logger
    }
    if settings.layout_mode == "grid":
        grid_params.update({'rows': getattr(settings, 'rows', None),
                            'columns': settings.columns,
                            'target_thumbnail_width': getattr(settings, 'target_thumbnail_width', None)})
    elif settings.layout_mode == "timeline":
        grid_params.update({'target_row_height': settings.target_row_height,
                            'max_grid_width': settings.output_image_width})

    success, layout_data = image_grid.create_image_grid(**grid_params)
    if not success:
        return False, None, "MoviePrint image generation failed."

    logger.info(f"  MoviePrint successfully saved to {output_path}")
    return True, layout_data, None


def _save_metadata(metadata_list, layout_data, settings, start_sec, end_sec, process_warnings, movieprint_path, logger):
    """Saves the metadata JSON file."""
    if not settings.save_metadata_json:
        return

    logger.info("  Generating metadata JSON...")
    source_map = {meta['frame_path']: meta for meta in metadata_list}
    combined_thumb_meta = []
    for layout_item in layout_data:
        source_meta = source_map.get(layout_item['image_path'])
        if source_meta:
            final_meta = {k: source_meta.get(k) for k in [
                'video_filename', 'frame_number', 'timestamp_sec', 'timecode',
                'start_frame', 'end_frame', 'duration_frames',
                'face_detection', 'rotation_error'
            ] if source_meta.get(k) is not None}
            final_meta['layout_in_movieprint'] = {k: layout_item[k] for k in ['x', 'y', 'width', 'height']}
            combined_thumb_meta.append(final_meta)

    settings_copy = vars(settings).copy()
    settings_copy.update({'parsed_start_time_sec': start_sec, 'parsed_end_time_sec': end_sec,
                          'processing_warnings_log': process_warnings,
                          'actual_frames_in_print': len(combined_thumb_meta)})

    full_meta = {
        'movieprint_image_filename': os.path.basename(movieprint_path),
        'source_video_processed': os.path.abspath(settings.input_paths[0]),
        'generation_parameters': settings_copy,
        'thumbnails': combined_thumb_meta
    }
    json_path = os.path.splitext(movieprint_path)[0] + ".json"
    try:
        with open(json_path, 'w') as f:
            json.dump(full_meta, f, indent=4)
        logger.info(f"  Metadata JSON saved to {json_path}")
    except Exception as e:
        logger.error(f"  Error saving metadata JSON to {json_path}: {e}")


def process_single_video(video_file_path, settings, effective_output_filename, logger):
    logger.info(f"\nProcessing video: {video_file_path}...")

    start_sec = parse_time_to_seconds(settings.start_time)
    end_sec = parse_time_to_seconds(settings.end_time)

    # Validate times
    if (settings.start_time and start_sec is None) or (settings.end_time and end_sec is None) or \
       (start_sec is not None and end_sec is not None and start_sec >= end_sec):
        return False, "Invalid time format or start_time is not less than end_time."

    temp_dir, cleanup_temp, error = _setup_temp_directory(video_file_path, settings, logger)
    if error:
        return False, error

    try:
        extraction_ok, metadata_list = _extract_frames(video_file_path, temp_dir, settings, start_sec, end_sec, logger)
        if not extraction_ok:
            return False, f"Frame extraction failed for {video_file_path}."

        metadata_list, process_warnings = _apply_exclusions(metadata_list, settings, logger)
        metadata_list = _limit_frames_for_grid(metadata_list, settings, temp_dir, cleanup_temp, logger)
        metadata_list = _process_thumbnails(metadata_list, settings, logger)

        if not os.path.exists(settings.output_dir):
            os.makedirs(settings.output_dir)

        final_path = os.path.join(settings.output_dir, effective_output_filename)
        counter = 1
        base, ext = os.path.splitext(final_path)
        while os.path.exists(final_path):
            final_path = f"{base}_{counter}{ext}"
            counter += 1
        if counter > 1:
            logger.warning(f"  Warning: Movieprint file existed. Saving as {final_path}")

        success, layout_data, error_msg = _generate_movieprint(metadata_list, settings, final_path, logger)
        if not success:
            return False, error_msg

        enforce_max_filesize(final_path, settings.max_output_filesize_kb, logger)
        _save_metadata(metadata_list, layout_data, settings, start_sec, end_sec, process_warnings, final_path, logger)

        return True, final_path

    finally:
        if cleanup_temp and os.path.exists(temp_dir):
            try:
                shutil.rmtree(temp_dir)
                logger.info(f"  Successfully cleaned up temporary directory: {temp_dir}")
            except Exception as e:
                logger.error(f"  Error cleaning up temp directory {temp_dir}: {e}")

def execute_movieprint_generation(settings, logger, progress_callback=None):
    logger.info("Starting MoviePrint generation process...")

    video_files_to_process = discover_video_files(
        settings.input_paths,
        settings.video_extensions,
        settings.recursive_scan,
        logger
    )

    if not video_files_to_process:
        logger.warning("No video files found to process. Please check your input paths and video extensions.")
        return [], []

    logger.info(f"\nFound {len(video_files_to_process)} video file(s) to process.")

    successful_ops = []
    failed_ops = []

    is_single_file_direct_input = len(settings.input_paths) == 1 and os.path.isfile(settings.input_paths[0])

    output_print_format = "png"
    if is_single_file_direct_input and settings.output_filename:
        _, ext = os.path.splitext(settings.output_filename)
        if ext.lower() in ['.png', '.jpg', '.jpeg']:
            output_print_format = ext.lower().replace('.', '').replace('jpeg','jpg')
        elif settings.frame_format.lower() in ['jpg', 'png']:
            output_print_format = settings.frame_format.lower()

    total_videos = len(video_files_to_process)
    for i, video_path in enumerate(video_files_to_process):
        if progress_callback:
            progress_callback(i, total_videos, video_path)

        effective_output_name = ""
        if is_single_file_direct_input and settings.output_filename:
            effective_output_name = settings.output_filename
        else:
            base = os.path.splitext(os.path.basename(video_path))[0]
            effective_output_name = f"{base}{settings.output_filename_suffix}.{output_print_format}"

        try:
            success, message_or_path = process_single_video(video_path, settings, effective_output_name, logger)
            if success:
                successful_ops.append({'video': video_path, 'output': message_or_path})
            else:
                failed_ops.append({'video': video_path, 'reason': message_or_path})
        except Exception as e:
            logger.exception(f"CRITICAL UNHANDLED ERROR processing {video_path}: {e}")
            failed_ops.append({'video': video_path, 'reason': f"Unexpected critical error: {str(e)}"})

    if progress_callback:
        progress_callback(total_videos, total_videos, "Batch completed")

    return successful_ops, failed_ops


def main():
    parser = argparse.ArgumentParser(
        description="Create MoviePrints from video files or directories.",
        formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument('--version', action='version', version=f'%(prog)s {__version__}')

    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    logger = logging.getLogger(__name__)
    logger.info("Logging initialized.")

    parser.add_argument("input_paths", nargs='+', help="Video files or directories.")
    parser.add_argument("output_dir", help="Directory for final MoviePrint image(s).")
    parser.add_argument("--output_filename_suffix", type=str, default="_movieprint", help="Suffix for auto-generated filenames (default: _movieprint).")
    parser.add_argument("--output_filename", type=str, default=None, help="Specific output filename (only if single input file).")

    batch_group = parser.add_argument_group("Batch Processing Options")
    batch_group.add_argument("--video_extensions", type=str, default=".mp4,.avi,.mov,.mkv,.flv,.wmv", help="Comma-separated video extensions (default: .mp4,...).")
    batch_group.add_argument("--recursive_scan", action="store_true", help="Scan directories recursively.")

    time_segment_group = parser.add_argument_group("Time Segment Options")
    time_segment_group.add_argument("--start_time", type=str, default=None, help="Start time for processing (HH:MM:SS, MM:SS, or seconds).")
    time_segment_group.add_argument("--end_time", type=str, default=None, help="End time for processing (HH:MM:SS, MM:SS, or seconds).")

    extraction_group = parser.add_argument_group("Frame Extraction Options")
    extraction_group.add_argument("--extraction_mode", type=str, default="interval", choices=["interval", "shot"], help="Frame extraction mode (default: interval).")
    extraction_group.add_argument("--interval_seconds", type=float, help="For 'interval' mode: interval in seconds.")
    extraction_group.add_argument("--interval_frames", type=int, help="For 'interval' mode: interval in frames.")
    extraction_group.add_argument("--shot_threshold", type=float, default=27.0, help="For 'shot' mode: detection threshold (default: 27.0).")
    extraction_group.add_argument("--exclude_frames", type=int, nargs='+', default=None, help="List of absolute frame numbers to exclude (for interval mode).")
    extraction_group.add_argument("--exclude_shots", type=int, nargs='+', default=None, help="List of 1-based shot indices to exclude (for shot mode).")

    layout_group = parser.add_argument_group("Layout Options")
    layout_group.add_argument("--layout_mode", type=str, default="grid", choices=["grid", "timeline"], help="Layout mode (default: grid).")
    layout_group.add_argument("--columns", type=int, default=5, help="For 'grid' layout: number of columns (default: 5).")
    layout_group.add_argument("--rows", type=int, default=None,
                              help="For 'grid' layout: number of rows. Overrides columns if provided.")
    layout_group.add_argument(
        "--target_thumbnail_width",
        type=int,
        default=None,
        help="For 'grid' layout: target width for individual thumbnails (e.g., 320). "
             "Overrides automatic sizing based on largest frame. "
             "Final grid cell height will be adjusted to accommodate the tallest thumbnail scaled to this width."
    )
    layout_group.add_argument("--max_frames_for_print", type=int, default=None, help="For 'grid' layout: Target maximum number of frames in the final print. Samples down if extraction yields more.")
    layout_group.add_argument("--target_row_height", type=int, default=100, help="For 'timeline' layout: row height (default: 100).")
    layout_group.add_argument("--output_image_width", type=int, default=1200, help="For 'timeline' layout: output image width (default: 1200).")

    common_group = parser.add_argument_group("Common Styling, File & Metadata Options")
    common_group.add_argument("--padding", type=int, default=5, help="Padding between images (default: 5).")
    common_group.add_argument("--background_color", type=str, default="#FFFFFF", help="Background color (hex, default: #FFFFFF).")
    common_group.add_argument("--frame_format", type=str, default="jpg", choices=["jpg", "png"], help="Format for extracted frames (default: jpg).")
    common_group.add_argument("--temp_dir", type=str, default=None, help="Optional global temporary directory. Not auto-cleaned.")
    common_group.add_argument("--save_metadata_json", action="store_true", help="Save a JSON sidecar file with detailed metadata.")
    common_group.add_argument("--detect_faces", action="store_true", help="Enable face detection on thumbnails. Performance intensive.")
    common_group.add_argument("--haar_cascade_xml", type=str, default=None,
                              help="Path to Haar Cascade XML file for face detection. \n"
                                   "If not provided, uses OpenCV's default 'haarcascade_frontalface_default.xml'.")
    common_group.add_argument("--rotate_thumbnails", type=int, default=0, choices=[0, 90, 180, 270],
                              help="Rotate all thumbnails by 0, 90, 180, or 270 degrees clockwise (default: 0).")
    common_group.add_argument("--max_output_filesize_kb", type=int, default=None,
                              help="Attempt to limit final MoviePrint file size to this value in kilobytes.")

    args = parser.parse_args()

    def cli_progress_callback(current, total, filename=""):
        if total > 0 :
             percent = (current / total) * 100
             status_msg = f"Processing file {current}/{total} ({percent:.1f}%): {os.path.basename(filename)}" if current < total else f"Batch completed {current}/{total}."
             print(status_msg, end='\r' if current < total else '\n')

    if args.extraction_mode == "interval":
        if args.interval_seconds is None and args.interval_frames is None:
            parser.error("For --extraction_mode 'interval', --interval_seconds or --interval_frames required.")
        if args.exclude_shots: parser.error("--exclude_shots only with --extraction_mode 'shot'.")
    elif args.extraction_mode == "shot":
        if args.exclude_frames: parser.error("--exclude_frames only with --extraction_mode 'interval'.")
    if args.layout_mode == "timeline" and args.extraction_mode != "shot":
        parser.error("--layout_mode 'timeline' requires --extraction_mode 'shot'.")

    # Validations for target_thumbnail_width
    if args.layout_mode != "grid" and args.target_thumbnail_width is not None:
        logger.warning("--target_thumbnail_width is only applicable for 'grid' layout mode and will be ignored.")
        # args.target_thumbnail_width = None # Optionally reset, or let image_grid handle it if it's robust
    if args.target_thumbnail_width is not None and args.target_thumbnail_width <= 0:
        parser.error("--target_thumbnail_width must be a positive integer.")

    if args.rows is not None:
        if args.layout_mode != "grid":
            logger.warning("--rows is only applicable for 'grid' layout mode and will be ignored.")
            args.rows = None
        elif args.rows <= 0:
            parser.error("--rows must be a positive integer.")
        else:
            args.columns = None

    if args.layout_mode == "timeline" and args.max_frames_for_print is not None:
        logger.warning("--max_frames_for_print is ignored for 'timeline' layout mode.")
        args.max_frames_for_print = None # Ensure it's not used for timeline

    successful_ops, failed_ops = execute_movieprint_generation(
        settings=args,
        logger=logger,
        progress_callback=cli_progress_callback
    )

    logger.info("\n--- CLI Batch Processing Summary ---")
    if successful_ops:
        logger.info(f"\nSuccessfully processed {len(successful_ops)} video(s):")
        for item in successful_ops: logger.info(f"  - Input: {item['video']}\n    Output: {item['output']}")
    else: logger.info("No videos processed successfully.")

    if failed_ops:
        logger.info(f"\nFailed to process {len(failed_ops)} video(s):")
        for item in failed_ops: logger.info(f"  - Input: {item['video']}\n    Reason: {item['reason']}")
    elif successful_ops: logger.info("\nAll identified videos processed without reported failures.")

    logger.info("\nCLI movieprint creation process finished.")

if __name__ == "__main__":
    main()
