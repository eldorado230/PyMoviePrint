import cv2
import logging
import os
import shutil
import subprocess
import re
import glob
import sys

# Robust import for PySceneDetect
try:
    from scenedetect import open_video, SceneManager, FrameTimecode
    from scenedetect.detectors import ContentDetector
except ImportError:
    pass

def check_ffmpeg_gpu(logger):
    """Checks if ffmpeg is installed and supports CUDA."""
    if not shutil.which('ffmpeg'):
        return False
    try:
        # Hide console window on Windows
        startupinfo = None
        if os.name == 'nt':
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            
        result = subprocess.run(['ffmpeg', '-hwaccels'], capture_output=True, text=True, startupinfo=startupinfo)
        if 'cuda' in result.stdout:
            logger.info("FFmpeg supports CUDA (NVDEC) hardware acceleration.")
            return True
    except Exception as e:
        logger.warning(f"Error checking FFmpeg capabilities: {e}")
    return False

def run_ffmpeg_command(cmd, logger):
    """Helper to run ffmpeg and capture errors without popping up windows."""
    logger.info(f"Running FFmpeg command: {' '.join(cmd)}")
    try:
        startupinfo = None
        if os.name == 'nt':
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, startupinfo=startupinfo)
        return True
    except subprocess.CalledProcessError as e:
        error_msg = e.stderr.decode() if e.stderr else "Unknown error"
        logger.warning(f"FFmpeg attempt failed: {error_msg}")
        return False
    except Exception as e:
        logger.warning(f"FFmpeg execution error: {e}")
        return False

def extract_frames_from_timestamps(video_path, timestamps, output_folder, logger, output_format="jpg", fast_preview=False):
    """
    MoviePrint v004 Style: Extracts frames at specific timestamp list.
    Uses OpenCV for speed (persistent file handle) during previews.
    """
    extracted_frame_info = []
    
    if not os.path.exists(video_path):
        logger.error(f"Video file not found: {video_path}")
        return False, []
    
    if not os.path.exists(output_folder):
        try: os.makedirs(output_folder)
        except OSError: pass

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        logger.error("OpenCV failed to open video.")
        return False, []

    fps = cap.get(cv2.CAP_PROP_FPS)
    if fps <= 0: fps = 24.0
    
    total_frames = cap.get(cv2.CAP_PROP_FRAME_COUNT)
    duration = total_frames / fps

    logger.info(f"Extracting {len(timestamps)} specific frames (Dynamic Mode)...")

    for i, ts in enumerate(timestamps):
        # Clamp timestamp to duration
        if ts > duration: ts = duration - 0.1
        if ts < 0: ts = 0

        # Seek
        cap.set(cv2.CAP_PROP_POS_MSEC, ts * 1000)
        ret, frame = cap.read()
        
        if ret:
            if fast_preview:
                h, w = frame.shape[:2]
                scale = 480 / w
                new_dim = (480, int(h * scale))
                frame = cv2.resize(frame, new_dim, interpolation=cv2.INTER_AREA)

            frame_number = int(cap.get(cv2.CAP_PROP_POS_FRAMES))
            # Use timestamp in filename to ensure uniqueness if we re-extract same frame
            safe_ts_str = f"{ts:.2f}".replace('.', '_')
            output_filename = f"thumb_{i:03d}_ts{safe_ts_str}.{output_format.lower()}"
            output_path = os.path.join(output_folder, output_filename)
            
            try:
                cv2.imwrite(output_path, frame)
                extracted_frame_info.append({
                    'frame_path': output_path,
                    'frame_number': frame_number,
                    'timestamp_sec': ts,
                    'video_filename': os.path.basename(video_path)
                })
            except Exception: pass
        else:
            logger.warning(f"Could not read frame at {ts}s")

    cap.release()
    return True, extracted_frame_info

def extract_frames_ffmpeg(video_path, output_folder, logger,
                          interval_seconds=None, interval_frames=None, output_format="jpg",
                          start_time_sec=None, end_time_sec=None, fast_preview=False, use_gpu=False):
    """Extracts frames using FFmpeg with GPU support."""
    extracted_frame_info = []
    video_filename = os.path.basename(video_path)

    # 1. Try getting FPS via OpenCV
    fps = 0.0
    try:
        cap = cv2.VideoCapture(video_path)
        if cap.isOpened():
            fps = cap.get(cv2.CAP_PROP_FPS)
        cap.release()
    except Exception: pass

    if fps <= 0: fps = 24.0

    start_time = start_time_sec if start_time_sec is not None else 0.0
    duration_cmd = []
    if end_time_sec is not None:
        duration_val = end_time_sec - start_time
        if duration_val > 0:
            duration_cmd = ['-t', str(duration_val)]

    # 2. Construct Filters
    filters = []
    if interval_seconds:
        filters.append(f"fps=1/{interval_seconds:.5f}")
    elif interval_frames:
        filters.append(f"select='not(mod(n,{interval_frames}))',vsync=vfr")

    if fast_preview:
        filters.append("scale=480:-1")

    vf_filter = ",".join(filters)
    q_scale = '5' if fast_preview else '2'
    output_pattern = os.path.join(output_folder, "ffmpeg_out_%05d." + output_format)

    base_cmd = ['ffmpeg']
    
    # Input args
    input_args = [
        '-ss', str(start_time),
        '-i', video_path,
        '-sn', '-an', '-dn'
    ]
    
    output_args = duration_cmd + [
        '-vf', vf_filter,
        '-frame_pts', '1',
        '-q:v', q_scale,
        output_pattern,
        '-y', '-hide_banner', '-loglevel', 'error'
    ]

    success = False
    
    if use_gpu:
        # GPU Attempt
        gpu_cmd = base_cmd + ['-hwaccel', 'cuda'] + input_args + output_args
        success = run_ffmpeg_command(gpu_cmd, logger)
    
    if not success:
        # CPU Attempt
        cpu_cmd = base_cmd + input_args + output_args
        success = run_ffmpeg_command(cpu_cmd, logger)

    if not success:
        return False, extracted_frame_info

    # 5. Post-process: Rename files
    generated_files = sorted(glob.glob(os.path.join(output_folder, f"ffmpeg_out_*.{output_format}")))

    for i, file_path in enumerate(generated_files):
        if interval_seconds:
            est_time = start_time + (i * interval_seconds)
            est_frame = int(est_time * fps)
        else:
            est_frame = int(start_time * fps) + (i * interval_frames)
            est_time = est_frame / fps

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
        except OSError: pass

    return True, extracted_frame_info

def extract_frames(video_path, output_folder, logger,
                   interval_seconds=None, interval_frames=None, output_format="jpg",
                   start_time_sec=None, end_time_sec=None, use_gpu=False, fast_preview=False):
    """
    Robust entry point for BATCH EXPORT. Tries FFmpeg first, falls back to OpenCV.
    """
    extracted_frame_info = []
    
    if not os.path.exists(video_path):
        logger.error(f"Video file not found: {video_path}")
        return False, extracted_frame_info
    
    if not os.path.exists(output_folder):
        try: os.makedirs(output_folder)
        except OSError: pass

    # --- 1. Try FFmpeg (Optional) ---
    ffmpeg_success = False
    if shutil.which('ffmpeg'):
        try:
            can_use_gpu = False
            if use_gpu and check_ffmpeg_gpu(logger):
                can_use_gpu = True

            ffmpeg_success, data = extract_frames_ffmpeg(
                video_path, output_folder, logger,
                interval_seconds, interval_frames, output_format,
                start_time_sec, end_time_sec, fast_preview=fast_preview, use_gpu=can_use_gpu
            )
            
            if ffmpeg_success and data:
                return True, data
        except Exception as e:
             logger.warning(f"FFmpeg extraction threw an exception: {e}. Proceeding to OpenCV fallback.")

    # --- 2. Fallback to OpenCV ---
    logger.info("Using OpenCV extraction (fallback or default)...")
    
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        logger.error("OpenCV failed to open video.")
        return False, extracted_frame_info

    fps = cap.get(cv2.CAP_PROP_FPS)
    if fps <= 0: fps = 24.0

    total_frames = cap.get(cv2.CAP_PROP_FRAME_COUNT)
    vid_duration = total_frames / fps if fps > 0 else 0
    
    actual_start = start_time_sec if start_time_sec is not None else 0.0
    actual_end = end_time_sec if end_time_sec is not None else vid_duration

    next_time = actual_start
    saved_frame_count = 0
    
    # Safety
    if interval_seconds and interval_seconds > 0:
        step_sec = interval_seconds
    elif interval_frames and interval_frames > 0:
        step_sec = interval_frames / fps
    else:
        step_sec = 1.0
    
    while next_time <= actual_end:
        cap.set(cv2.CAP_PROP_POS_MSEC, next_time * 1000)
        ret, frame = cap.read()
        if not ret: break
        
        if fast_preview:
            h, w = frame.shape[:2]
            scale = 480 / w
            new_dim = (480, int(h * scale))
            frame = cv2.resize(frame, new_dim, interpolation=cv2.INTER_AREA)

        frame_number = int(cap.get(cv2.CAP_PROP_POS_FRAMES))
        output_filename = f"frame_{saved_frame_count:05d}_absFN{frame_number}.{output_format.lower()}"
        output_path = os.path.join(output_folder, output_filename)
        
        try:
            cv2.imwrite(output_path, frame)
            extracted_frame_info.append({
                'frame_path': output_path,
                'frame_number': frame_number,
                'timestamp_sec': round(next_time, 3),
                'video_filename': os.path.basename(video_path)
            })
            saved_frame_count += 1
        except Exception: pass
        
        next_time += step_sec

    cap.release()
    return True, extracted_frame_info

def extract_shot_boundary_frames(video_path, output_folder, logger, output_format="jpg",
                                 detector_threshold=27.0, start_time_sec=None, end_time_sec=None):
    """
    Wrapper for scene detection.
    """
    try:
        from scenedetect import open_video, SceneManager, FrameTimecode
        from scenedetect.detectors import ContentDetector
    except ImportError:
        logger.error("PySceneDetect not installed.")
        return False, []

    shot_meta_list = []
    video_filename = os.path.basename(video_path)
    
    if not os.path.exists(output_folder):
        try: os.makedirs(output_folder)
        except OSError: pass

    try:
        video_manager = open_video(video_path)
        scene_manager = SceneManager()
        scene_manager.add_detector(ContentDetector(threshold=detector_threshold))
        
        start_tc = FrameTimecode(timecode=start_time_sec or 0.0, fps=video_manager.frame_rate)
        end_tc = FrameTimecode(timecode=end_time_sec, fps=video_manager.frame_rate) if end_time_sec else None
        
        if start_time_sec:
            video_manager.seek(start_tc)

        scene_manager.detect_scenes(video=video_manager, end_time=end_tc, show_progress=False)
        scene_list = scene_manager.get_scene_list(start_in_scene=True)

        cap_cv = cv2.VideoCapture(video_path)
        
        for i, (start, end) in enumerate(scene_list):
            frame_num = start.get_frames()
            cap_cv.set(cv2.CAP_PROP_POS_FRAMES, frame_num)
            ret, frame = cap_cv.read()
            
            if ret:
                output_filename = f"shot_{i:04d}_absFN{frame_num}.{output_format.lower()}"
                output_path = os.path.join(output_folder, output_filename)
                cv2.imwrite(output_path, frame)
                
                shot_meta_list.append({
                    'frame_path': output_path,
                    'frame_number': frame_num,
                    'timestamp_sec': start.get_seconds(),
                    'video_filename': video_filename,
                    'duration_frames': (end.get_frames() - start.get_frames())
                })
                
        cap_cv.release()
        return True, shot_meta_list

    except Exception as e:
        logger.error(f"Shot detection failed: {e}")
        return False, []

def extract_specific_frame(video_path, timestamp_sec, output_path, logger, use_gpu=False):
    """Extract single frame for scrubbing."""
    cap = cv2.VideoCapture(video_path)
    cap.set(cv2.CAP_PROP_POS_MSEC, timestamp_sec * 1000)
    ret, frame = cap.read()
    cap.release()
    if ret:
        cv2.imwrite(output_path, frame)
        return True
    return False