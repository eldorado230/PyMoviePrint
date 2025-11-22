import cv2
import logging
import os
import shutil
import subprocess
import re
import glob

# Imports for PySceneDetect
from scenedetect import open_video, SceneManager, FrameTimecode # Ensure FrameTimecode is imported
from scenedetect.detectors import ContentDetector

def check_ffmpeg_gpu(logger):
    """Checks if ffmpeg is installed and supports CUDA."""
    if not shutil.which('ffmpeg'):
        logger.warning("FFmpeg not found in PATH. GPU acceleration unavailable.")
        return False
    try:
        result = subprocess.run(['ffmpeg', '-hwaccels'], capture_output=True, text=True)
        if 'cuda' in result.stdout:
            logger.info("FFmpeg supports CUDA (NVDEC) hardware acceleration.")
            return True
        else:
            logger.warning("FFmpeg found but 'cuda' not listed in -hwaccels. GPU acceleration unavailable.")
            return False
    except Exception as e:
        logger.warning(f"Error checking FFmpeg capabilities: {e}")
        return False

def extract_frames_ffmpeg(video_path, output_folder, logger,
                          interval_seconds=None, interval_frames=None, output_format="jpg",
                          start_time_sec=None, end_time_sec=None, fast_preview=False):
    """
    Extracts frames using FFmpeg with NVDEC GPU acceleration.
    """
    extracted_frame_info = []
    video_filename = os.path.basename(video_path)

    # Retrieve basic video info (fps, duration) using OpenCV just for metadata calculation
    # (Using ffprobe would be cleaner but requires parsing JSON/output, OpenCV is already here)
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        logger.error(f"Could not open video {video_path} to read metadata."); return False, extracted_frame_info
    fps = cap.get(cv2.CAP_PROP_FPS)
    total_video_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    cap.release()

    if fps <= 0:
        logger.error("Could not determine FPS. Cannot use FFmpeg extraction reliably."); return False, extracted_frame_info

    start_time = start_time_sec if start_time_sec is not None else 0.0
    duration_cmd = []
    if end_time_sec is not None:
        duration_val = end_time_sec - start_time
        if duration_val > 0:
            duration_cmd = ['-t', str(duration_val)]

    # Construct filter
    vf_filter = ""
    if interval_seconds:
        vf_filter = f"fps=1/{interval_seconds}"
    elif interval_frames:
        # select='not(mod(n,interval))'
        vf_filter = f"select='not(mod(n,{interval_frames}))',vsync=vfr"

    output_pattern = os.path.join(output_folder, "ffmpeg_out_%05d." + output_format)

    cmd = [
        'ffmpeg',
        '-hwaccel', 'cuda'
    ]

    if fast_preview:
        cmd.extend(['-skip_frame', 'nokey'])

    cmd.extend([
        '-ss', str(start_time),
        '-i', video_path
    ])

    cmd += duration_cmd + [
        '-vf', vf_filter,
        '-frame_pts', '1', # helpful for debugging timing if needed, though simple output numbering is used here
        '-q:v', '2', # High quality for jpeg
        output_pattern,
        '-y', '-hide_banner', '-loglevel', 'error'
    ]

    logger.info(f"Running FFmpeg command: {' '.join(cmd)}")
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except subprocess.CalledProcessError as e:
        logger.error(f"FFmpeg execution failed: {e.stderr.decode()}")
        return False, extracted_frame_info

    # Post-process: Rename files and build metadata
    # FFmpeg outputs sequential numbers: ffmpeg_out_00001.jpg, 00002.jpg...
    # We need to map these to estimated timestamps/frame numbers.
    generated_files = sorted(glob.glob(os.path.join(output_folder, f"ffmpeg_out_*.{output_format}")))

    for i, file_path in enumerate(generated_files):
        # Estimate time/frame
        # Time ~= start + i * interval
        # Frame ~= Time * FPS
        if interval_seconds:
            est_time = start_time + (i * interval_seconds)
            est_frame = int(est_time * fps)
        else: # interval_frames
            est_frame = int(start_time * fps) + (i * interval_frames)
            est_time = est_frame / fps

        # Rename to standard format expected by the rest of the app
        # "frame_{count:05d}_absFN{frame_number}.{ext}"
        final_filename = f"frame_{i:05d}_absFN{est_frame}.{output_format}"
        final_path = os.path.join(output_folder, final_filename)

        try:
            os.rename(file_path, final_path)
            extracted_frame_info.append({
                'frame_path': final_path,
                'frame_number': est_frame,
                'timestamp_sec': round(est_time, 3),
                'video_filename': video_filename
            })
        except OSError as e:
            logger.warning(f"Could not rename {file_path} to {final_path}: {e}")

    logger.info(f"FFmpeg GPU extraction complete. Saved {len(extracted_frame_info)} frames.")
    return True, extracted_frame_info

def extract_specific_frame_ffmpeg(video_path, timestamp_sec, output_path, logger):
    """Extracts a single frame using FFmpeg GPU acceleration."""
    cmd = [
        'ffmpeg',
        '-hwaccel', 'cuda',
        '-ss', str(timestamp_sec),
        '-i', video_path,
        '-frames:v', '1',
        '-q:v', '2',
        output_path,
        '-y', '-hide_banner', '-loglevel', 'error'
    ]
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if os.path.exists(output_path):
            return True
    except subprocess.CalledProcessError as e:
        logger.error(f"FFmpeg scrub failed: {e.stderr.decode()}")
    return False

def extract_frames(video_path, output_folder, logger,
                   interval_seconds=None, interval_frames=None, output_format="jpg",
                   start_time_sec=None, end_time_sec=None, use_gpu=False, fast_preview=False):
    """
    Extracts frames from a video file based on time or frame intervals within a specified time segment.

    Args:
        video_path (str): Path to the video file.
        output_folder (str): Path to the folder where extracted frames will be saved.
        interval_seconds (float, optional): Interval in seconds.
        interval_frames (int, optional): Interval in frames.
        output_format (str, optional): Output image format. Defaults to "jpg".
        start_time_sec (float, optional): Start time in seconds to begin extraction.
        end_time_sec (float, optional): End time in seconds to stop extraction.
        use_gpu (bool, optional): Try to use FFmpeg with NVDEC if True.
        fast_preview (bool, optional): If True, use keyframe skipping for faster (approximate) extraction.

    Returns:
        tuple: (bool, list) - Success status and list of extracted frame metadata.
    """
    extracted_frame_info = []
    video_filename = os.path.basename(video_path)

    if not os.path.exists(video_path):
        logger.error(f"Video file not found: {video_path}"); return False, extracted_frame_info
    if interval_seconds is None and interval_frames is None:
        logger.error("Either interval_seconds or interval_frames must be specified."); return False, extracted_frame_info
    if interval_seconds is not None and interval_frames is not None:
        logger.warning("Both interval_seconds/frames specified; interval_seconds used."); interval_frames = None
    if not output_format.lower() in ["jpg", "jpeg", "png"]:
        logger.error(f"Unsupported output format '{output_format}'."); return False, extracted_frame_info
    if not os.path.exists(output_folder):
        try: os.makedirs(output_folder)
        except OSError as e: logger.error(f"Error creating output folder {output_folder}: {e}"); return False, extracted_frame_info

    # Try GPU path if requested
    if use_gpu:
        if check_ffmpeg_gpu(logger):
            logger.info("Using FFmpeg GPU acceleration for frame extraction.")
            return extract_frames_ffmpeg(
                video_path, output_folder, logger,
                interval_seconds, interval_frames, output_format,
                start_time_sec, end_time_sec, fast_preview=fast_preview
            )
        else:
            logger.info("GPU acceleration unavailable or failed check. Falling back to OpenCV CPU.")

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        logger.error(f"Could not open video {video_path} with OpenCV."); return False, extracted_frame_info

    fps = cap.get(cv2.CAP_PROP_FPS)
    total_video_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    video_duration_sec = total_video_frames / fps if fps > 0 else 0

    if fps == 0:
        logger.warning("Video FPS is 0. Cannot reliably perform time-based operations."); cap.release(); return False, extracted_frame_info

    # Validate start_time_sec and end_time_sec against video duration
    if start_time_sec is not None:
        if start_time_sec >= video_duration_sec:
            logger.error(f"Start time ({start_time_sec:.2f}s) is beyond video duration ({video_duration_sec:.2f}s)."); cap.release(); return False, extracted_frame_info
        # Seek video to start_time_sec
        cap.set(cv2.CAP_PROP_POS_MSEC, start_time_sec * 1000)
        logger.info(f"  Processing from {start_time_sec:.2f}s.")

    if end_time_sec is not None and end_time_sec <= (start_time_sec or 0): # Ensure end_time is after start_time
        logger.error(f"End time ({end_time_sec:.2f}s) must be after start time ({(start_time_sec or 0):.2f}s)."); cap.release(); return False, extracted_frame_info

    effective_start_time_sec = start_time_sec or 0
    # If end_time_sec is None, process till the end of the video.

    logger.info(f"Video Properties: FPS={fps:.2f}, Total Frames={total_video_frames}, Duration={video_duration_sec:.2f}s")
    if start_time_sec is not None or end_time_sec is not None:
        logger.info(f"  Processing segment: Start={effective_start_time_sec:.2f}s, End={(end_time_sec if end_time_sec is not None else video_duration_sec):.2f}s")


    saved_frame_count = 0

    segment_end_sec = end_time_sec if end_time_sec is not None else video_duration_sec

    if interval_seconds is not None:
        next_time = effective_start_time_sec
        while next_time <= segment_end_sec:
            cap.set(cv2.CAP_PROP_POS_MSEC, next_time * 1000)
            ret, frame = cap.read()
            if not ret:
                break
            frame_number = int(cap.get(cv2.CAP_PROP_POS_FRAMES))
            output_filename = f"frame_{saved_frame_count:05d}_absFN{frame_number}.{output_format.lower()}"
            output_path = os.path.join(output_folder, output_filename)
            try:
                cv2.imwrite(output_path, frame)
                extracted_frame_info.append({
                    'frame_path': output_path,
                    'frame_number': frame_number,
                    'timestamp_sec': round(frame_number / fps, 3),
                    'video_filename': video_filename
                })
                logger.info(
                    f"Saved frame {saved_frame_count+1} (AbsFrame: {frame_number}, Time: {frame_number / fps:.2f}s) as {output_path}")
                saved_frame_count += 1
            except Exception as e:
                logger.error(f"Error saving frame {frame_number} to {output_path}: {e}")

            next_time += interval_seconds

    elif interval_frames is not None:
        start_frame = int(effective_start_time_sec * fps)
        end_frame = int(segment_end_sec * fps)
        frame_number = start_frame
        while frame_number <= end_frame:
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_number)
            ret, frame = cap.read()
            if not ret:
                break
            output_filename = f"frame_{saved_frame_count:05d}_absFN{frame_number}.{output_format.lower()}"
            output_path = os.path.join(output_folder, output_filename)
            try:
                cv2.imwrite(output_path, frame)
                extracted_frame_info.append({
                    'frame_path': output_path,
                    'frame_number': frame_number,
                    'timestamp_sec': round(frame_number / fps, 3),
                    'video_filename': video_filename
                })
                logger.info(
                    f"Saved frame {saved_frame_count+1} (AbsFrame: {frame_number}, Time: {frame_number / fps:.2f}s) as {output_path}")
                saved_frame_count += 1
            except Exception as e:
                logger.error(f"Error saving frame {frame_number} to {output_path}: {e}")

            frame_number += interval_frames

    cap.release()
    logger.info(f"\nInterval-based extraction complete. Saved {saved_frame_count} frames.")
    return True, extracted_frame_info


def extract_shot_boundary_frames(video_path, output_folder, logger, output_format="jpg",
                                 detector_threshold=27.0, start_time_sec=None, end_time_sec=None):
    """
    Detects shot boundaries within a specified time segment and extracts metadata.
    """
    shot_meta_list = []
    video_filename = os.path.basename(video_path)

    if not os.path.exists(video_path):
        logger.error(f"Video file not found: {video_path}"); return False, shot_meta_list
    if not output_format.lower() in ["jpg", "jpeg", "png"]:
        logger.error(f"Unsupported output format '{output_format}'."); return False, shot_meta_list
    if not os.path.exists(output_folder):
        try: os.makedirs(output_folder)
        except OSError as e: logger.error(f"Error creating output folder {output_folder}: {e}"); return False, shot_meta_list

    video_manager = None
    cap_cv = None
    try:
        video_manager = open_video(video_path)
        if not video_manager:
             logger.error(f"PySceneDetect could not open/analyze video: {video_path}"); return False, shot_meta_list

        # Set duration for scene detection if start/end times are provided
        video_fps = video_manager.frame_rate
        video_duration_sec = video_manager.duration.get_seconds()

        # Validate start/end times against video duration
        effective_start_time = None
        effective_end_time = None

        if start_time_sec is not None:
            if start_time_sec >= video_duration_sec:
                logger.error(f"Start time ({start_time_sec:.2f}s) is beyond video duration ({video_duration_sec:.2f}s).")
                return False, shot_meta_list
            effective_start_time = FrameTimecode(timecode=start_time_sec, fps=video_fps)
            logger.info(f"  Shot detection from {start_time_sec:.2f}s ({effective_start_time.get_timecode()}).")

        if end_time_sec is not None:
            if end_time_sec <= (start_time_sec or 0):
                logger.error(f"End time ({end_time_sec:.2f}s) must be after start time ({(start_time_sec or 0):.2f}s).")
                return False, shot_meta_list
            if end_time_sec > video_duration_sec:
                logger.warning(f"  End time ({end_time_sec:.2f}s) exceeds video duration ({video_duration_sec:.2f}s). Clamping to video end.")
                end_time_sec = video_duration_sec
            effective_end_time = FrameTimecode(timecode=end_time_sec, fps=video_fps)
            logger.info(f"  Shot detection until {end_time_sec:.2f}s ({effective_end_time.get_timecode()}).")

        scene_manager = SceneManager()
        scene_manager.add_detector(ContentDetector(threshold=detector_threshold))

        if effective_start_time:
            video_manager.seek(effective_start_time)

        logger.info(f"Starting shot detection for '{video_path}' (Threshold: {detector_threshold})...")
        scene_manager.detect_scenes(
            video=video_manager,
            end_time=effective_end_time,
            show_progress=True
        )
        scene_list = scene_manager.get_scene_list(start_in_scene=True)

        if not scene_list:
            logger.info("No shots detected in the specified segment."); return True, shot_meta_list

        logger.info(f"Detected {len(scene_list)} shots within the segment.")

        cap_cv = cv2.VideoCapture(video_path)
        if not cap_cv.isOpened():
            logger.error(f"OpenCV could not open video {video_path} for frame extraction."); return False, shot_meta_list

        saved_frame_count = 0
        for i, (start_tc, end_tc) in enumerate(scene_list): # start_tc, end_tc are FrameTimecode objects
            start_frame_abs = start_tc.get_frames() # Absolute frame number
            end_frame_abs = end_tc.get_frames()     # Absolute frame number (exclusive for ContentDetector)
            duration_frames = end_frame_abs - start_frame_abs
            actual_end_frame_inclusive_abs = end_frame_abs - 1

            if duration_frames <= 0: continue

            cap_cv.set(cv2.CAP_PROP_POS_FRAMES, start_frame_abs)
            ret, frame_image = cap_cv.read()

            if ret:
                output_filename = f"shot_{i+1:04d}_absFN{start_frame_abs}.{output_format.lower()}"
                output_path = os.path.join(output_folder, output_filename)
                try:
                    cv2.imwrite(output_path, frame_image)
                    shot_meta_list.append({
                        'frame_path': output_path,
                        'video_filename': video_filename,
                        'start_frame': start_frame_abs, # Absolute frame number
                        'end_frame': actual_end_frame_inclusive_abs, # Absolute inclusive end frame
                        'duration_frames': duration_frames,
                        'timestamp_sec': round(start_tc.get_seconds(), 3), # Absolute timestamp
                        'timecode': start_tc.get_timecode() # Absolute timecode
                    })
                    logger.info(f"Saved frame for shot {i+1} (AbsFrame: {start_frame_abs}, Time: {start_tc.get_timecode()}) as {output_path}")
                    saved_frame_count += 1
                except Exception as e: logger.error(f"Error saving frame {start_frame_abs} for shot {i+1}: {e}")
            else: logger.warning(f"Could not read frame {start_frame_abs} for shot {i+1}.")

        logger.info(f"\nShot boundary frame extraction complete. Saved {saved_frame_count} frames.")
        return True, shot_meta_list

    except Exception as e:
        logger.exception(f"An error occurred during shot detection/extraction: {e}"); return False, shot_meta_list
    finally:
        if cap_cv: cap_cv.release()
        # video_manager is closed by PySceneDetect automatically or by its context manager if used.

def extract_specific_frame(video_path, timestamp_sec, output_path, logger, use_gpu=False):
    """
    Extracts a single specific frame from a video file at a given timestamp.

    Args:
        video_path (str): Path to the video file.
        timestamp_sec (float): The timestamp in seconds for the frame to extract.
        output_path (str): The full path where the extracted frame will be saved.
        logger (logging.Logger): Logger instance.
        use_gpu (bool): If True, try to use FFmpeg GPU extraction.

    Returns:
        bool: True if the frame was extracted successfully, False otherwise.
    """
    if use_gpu:
        # Simple check without full subprocess overhead every time (optimistically try)
        # Or rely on GUI to only pass True if verified.
        # We'll assume if passed True, we try it.
        if extract_specific_frame_ffmpeg(video_path, timestamp_sec, output_path, logger):
            return True
        # Fallback handled by proceeding to OpenCV code if return False isn't here?
        # Actually extract_specific_frame_ffmpeg returns False on failure.
        # We can fallback.
        logger.warning("FFmpeg GPU scrub failed. Falling back to CPU.")

    if not os.path.exists(video_path):
        logger.error(f"Video file not found: {video_path}")
        return False

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        logger.error(f"Could not open video {video_path} with OpenCV.")
        return False

    fps = cap.get(cv2.CAP_PROP_FPS)
    if fps == 0:
        logger.warning("Video FPS is 0. Cannot reliably seek by time.")
        cap.release()
        return False

    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    duration = total_frames / fps

    if timestamp_sec < 0 or timestamp_sec > duration:
        logger.warning(f"Timestamp {timestamp_sec}s is out of video duration (0-{duration}s).")
        cap.release()
        return False

    cap.set(cv2.CAP_PROP_POS_MSEC, timestamp_sec * 1000)
    ret, frame = cap.read()

    if not ret:
        logger.warning(f"Could not read frame at timestamp {timestamp_sec}s.")
        cap.release()
        return False

    try:
        cv2.imwrite(output_path, frame)
        logger.info(f"Successfully extracted frame at {timestamp_sec}s to {output_path}")
        cap.release()
        return True
    except Exception as e:
        logger.error(f"Error saving frame to {output_path}: {e}")
        cap.release()
        return False

if __name__ == "__main__":
    test_logger = logging.getLogger("video_processing_test")
    test_logger.setLevel(logging.INFO)
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
    test_logger.addHandler(handler)
    test_logger.propagate = False
    # (The __main__ block for testing can be kept similar, but now you can add
    #  start_time_sec and end_time_sec to calls to test the segmentation)
    test_logger.info("Starting video frame extraction process demonstrations...")
    test_video_path = "sample_video.mp4"
    # ... (dummy video creation if not exists) ...
    if not os.path.exists(test_video_path):
        # Simplified dummy video creation for brevity
        test_logger.info(f"Creating dummy video: {test_video_path}")
        cap_out = cv2.VideoWriter(test_video_path, cv2.VideoWriter_fourcc(*'mp4v'), 30, (640, 480))
        for i in range(210): # 7 seconds at 30fps
            frame = cv2.UMat(480, 640, cv2.CV_8UC3); frame.setTo(cv2.Scalar((i*2)%255, (i*3)%255, (i*4)%255))
            # Convert UMat to Mat for VideoWriter
            mat_frame = frame.get()
            cap_out.write(mat_frame)
        cap_out.release()


    if os.path.exists(test_video_path):
        output_dir_interval_seg = "extracted_frames_interval_segment"
        output_dir_shot_seg = "extracted_frames_shot_segment"
        for d in [output_dir_interval_seg, output_dir_shot_seg]:
            if os.path.exists(d): shutil.rmtree(d); os.makedirs(d)
            else: os.makedirs(d)

        test_logger.info(f"\n--- Example: Interval extraction (every 1s) from segment [2s - 5s] of '{test_video_path}' ---")
        success_interval, data_interval = extract_frames(
            test_video_path, output_dir_interval_seg, logger=test_logger, interval_seconds=1.0,
            start_time_sec=2.0, end_time_sec=5.0
        )
        if success_interval: test_logger.info(f"  Extracted {len(data_interval)} frames. First: {data_interval[0] if data_interval else 'N/A'}")

        test_logger.info(f"\n--- Example: Shot boundary extraction from segment [1s - 6s] of '{test_video_path}' ---")
        success_shot, data_shot = extract_shot_boundary_frames(
            test_video_path, output_dir_shot_seg, logger=test_logger, detector_threshold=20.0,
            start_time_sec=1.0, end_time_sec=6.0
        )
        if success_shot: test_logger.info(f"  Detected {len(data_shot)} shots. First: {data_shot[0] if data_shot else 'N/A'}")
    else:
        test_logger.warning(f"\nSkipping example usage: dummy video '{test_video_path}' not found.")
    test_logger.info("\nVideo frame extraction script demonstrations finished.")
