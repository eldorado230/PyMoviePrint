import cv2
import logging
import os
import shutil
import subprocess
import re
import glob
import sys
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple, Union

# --- Optional Dependency Handling ---
try:
    from scenedetect import open_video, SceneManager, FrameTimecode
    from scenedetect.detectors import ContentDetector
    SCENEDETECT_AVAILABLE = True
except ImportError:
    SCENEDETECT_AVAILABLE = False

def check_ffmpeg_gpu(logger: logging.Logger) -> bool:
    """Checks if ffmpeg is installed and supports CUDA."""
    if not shutil.which('ffmpeg'):
        return False
    
    try:
        # Prevent console window popup on Windows
        startupinfo = None
        if os.name == 'nt':
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            
        result = subprocess.run(
            ['ffmpeg', '-hwaccels'], 
            capture_output=True, 
            text=True, 
            startupinfo=startupinfo
        )
        
        if 'cuda' in result.stdout:
            logger.info("FFmpeg supports CUDA (NVDEC) hardware acceleration.")
            return True
            
    except Exception as e:
        logger.warning(f"Error checking FFmpeg capabilities: {e}")
        
    return False

def run_ffmpeg_command(cmd: List[str], logger: logging.Logger) -> bool:
    """
    Helper to run ffmpeg and capture errors without popping up windows.
    Returns True on success, False on failure.
    """
    logger.info(f"Running FFmpeg command: {' '.join(cmd)}")
    try:
        startupinfo = None
        if os.name == 'nt':
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

        subprocess.run(
            cmd, 
            check=True, 
            stdout=subprocess.PIPE, 
            stderr=subprocess.PIPE, 
            startupinfo=startupinfo
        )
        return True
    except subprocess.CalledProcessError as e:
        error_msg = e.stderr.decode() if e.stderr else "Unknown FFmpeg error"
        logger.warning(f"FFmpeg attempt failed: {error_msg}")
        return False
    except Exception as e:
        logger.warning(f"FFmpeg execution error: {e}")
        return False

def _get_video_properties(video_path: str) -> Tuple[float, float]:
    """Returns (fps, duration) or (24.0, 0.0) on failure."""
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return 24.0, 0.0
    
    fps = cap.get(cv2.CAP_PROP_FPS)
    if fps <= 0: fps = 24.0
    
    frame_count = cap.get(cv2.CAP_PROP_FRAME_COUNT)
    duration = frame_count / fps
    cap.release()
    return fps, duration

def extract_frames_from_timestamps(
    video_path: str, 
    timestamps: List[float], 
    output_folder: str, 
    logger: logging.Logger, 
    output_format: str = "jpg", 
    fast_preview: bool = False
) -> Tuple[bool, List[Dict[str, Any]]]:
    """
    MoviePrint v004 Style: Extracts frames at specific timestamp list using OpenCV.
    Optimized to keep the capture open during the loop.
    """
    extracted_frame_info = []
    
    if not os.path.exists(video_path):
        logger.error(f"Video file not found: {video_path}")
        return False, []
    
    Path(output_folder).mkdir(parents=True, exist_ok=True)

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        logger.error("OpenCV failed to open video.")
        return False, []

    try:
        fps = cap.get(cv2.CAP_PROP_FPS)
        if fps <= 0: fps = 24.0
        
        total_frames = cap.get(cv2.CAP_PROP_FRAME_COUNT)
        duration = total_frames / fps

        logger.info(f"Extracting {len(timestamps)} specific frames (Dynamic Mode)...")

        for i, ts in enumerate(timestamps):
            # Clamp timestamp to valid duration
            ts = max(0.0, min(ts, duration - 0.1))

            # Seek and Read
            cap.set(cv2.CAP_PROP_POS_MSEC, ts * 1000)
            ret, frame = cap.read()
            
            if ret:
                if fast_preview:
                    h, w = frame.shape[:2]
                    # Resize to max 480px width for speed
                    scale = 480 / w
                    new_dim = (480, int(h * scale))
                    frame = cv2.resize(frame, new_dim, interpolation=cv2.INTER_AREA)

                frame_number = int(cap.get(cv2.CAP_PROP_POS_FRAMES))
                
                # Filename safety
                safe_ts_str = f"{ts:.2f}".replace('.', '_')
                filename = f"thumb_{i:03d}_ts{safe_ts_str}.{output_format.lower()}"
                output_path = os.path.join(output_folder, filename)
                
                try:
                    cv2.imwrite(output_path, frame)
                    extracted_frame_info.append({
                        'frame_path': output_path,
                        'frame_number': frame_number,
                        'timestamp_sec': ts,
                        'video_filename': os.path.basename(video_path)
                    })
                except Exception as e:
                    logger.warning(f"Failed to write frame at {output_path}: {e}")
            else:
                # This might happen if seeking past end of stream or corrupt video
                pass
                
    finally:
        cap.release()

    return True, extracted_frame_info

def extract_frames_ffmpeg(
    video_path: str, 
    output_folder: str, 
    logger: logging.Logger,
    interval_seconds: Optional[float] = None, 
    interval_frames: Optional[int] = None, 
    output_format: str = "jpg",
    start_time_sec: Optional[float] = None, 
    end_time_sec: Optional[float] = None, 
    fast_preview: bool = False, 
    use_gpu: bool = False
) -> Tuple[bool, List[Dict[str, Any]]]:
    """Extracts frames using FFmpeg with GPU support."""
    extracted_frame_info = []
    video_filename = os.path.basename(video_path)
    
    fps, _ = _get_video_properties(video_path)
    start_time = start_time_sec if start_time_sec is not None else 0.0

    # Calculate Duration Argument
    duration_cmd = []
    if end_time_sec is not None:
        duration_val = end_time_sec - start_time
        if duration_val > 0:
            duration_cmd = ['-t', str(duration_val)]

    # Construct Filters
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
    input_args = ['-ss', str(start_time), '-i', video_path, '-sn', '-an', '-dn']
    
    output_args = duration_cmd + [
        '-vf', vf_filter,
        '-frame_pts', '1',
        '-q:v', q_scale,
        output_pattern,
        '-y', '-hide_banner', '-loglevel', 'error'
    ]

    # Try GPU first if requested
    success = False
    if use_gpu:
        gpu_cmd = base_cmd + ['-hwaccel', 'cuda'] + input_args + output_args
        success = run_ffmpeg_command(gpu_cmd, logger)
    
    # Fallback to CPU
    if not success:
        cpu_cmd = base_cmd + input_args + output_args
        success = run_ffmpeg_command(cpu_cmd, logger)

    if not success:
        return False, extracted_frame_info

    # Post-process: Rename files to standard format
    generated_files = sorted(glob.glob(os.path.join(output_folder, f"ffmpeg_out_*.{output_format}")))

    for i, file_path in enumerate(generated_files):
        # Estimate timestamp based on interval
        if interval_seconds:
            est_time = start_time + (i * interval_seconds)
            est_frame = int(est_time * fps)
        else:
            est_frame = int(start_time * fps) + (i * (interval_frames or 1))
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

def extract_frames(
    video_path: str, 
    output_folder: str, 
    logger: logging.Logger,
    interval_seconds: Optional[float] = None, 
    interval_frames: Optional[int] = None, 
    output_format: str = "jpg",
    start_time_sec: Optional[float] = None, 
    end_time_sec: Optional[float] = None, 
    use_gpu: bool = False, 
    fast_preview: bool = False
) -> Tuple[bool, List[Dict[str, Any]]]:
    """
    Main entry point. Tries FFmpeg first (if installed), falls back to OpenCV.
    """
    Path(output_folder).mkdir(parents=True, exist_ok=True)

    # 1. Try FFmpeg
    if shutil.which('ffmpeg'):
        try:
            can_use_gpu = use_gpu and check_ffmpeg_gpu(logger)
            success, data = extract_frames_ffmpeg(
                video_path, output_folder, logger,
                interval_seconds, interval_frames, output_format,
                start_time_sec, end_time_sec, fast_preview, can_use_gpu
            )
            if success and data:
                return True, data
        except Exception as e:
             logger.warning(f"FFmpeg extraction threw exception: {e}. Fallback to OpenCV.")

    # 2. Fallback to OpenCV
    logger.info("Using OpenCV extraction (fallback or default)...")
    
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        logger.error("OpenCV failed to open video.")
        return False, []

    extracted_frame_info = []
    try:
        fps = cap.get(cv2.CAP_PROP_FPS) or 24.0
        total_frames = cap.get(cv2.CAP_PROP_FRAME_COUNT)
        vid_duration = total_frames / fps if fps > 0 else 0
        
        actual_start = start_time_sec if start_time_sec is not None else 0.0
        actual_end = end_time_sec if end_time_sec is not None else vid_duration

        # Determine step size in seconds
        if interval_seconds and interval_seconds > 0:
            step_sec = interval_seconds
        elif interval_frames and interval_frames > 0:
            step_sec = interval_frames / fps
        else:
            step_sec = 1.0
        
        next_time = actual_start
        saved_frame_count = 0
        
        while next_time <= actual_end:
            cap.set(cv2.CAP_PROP_POS_MSEC, next_time * 1000)
            ret, frame = cap.read()
            if not ret: break
            
            if fast_preview:
                h, w = frame.shape[:2]
                scale = 480 / w
                frame = cv2.resize(frame, (480, int(h * scale)), interpolation=cv2.INTER_AREA)

            frame_number = int(cap.get(cv2.CAP_PROP_POS_FRAMES))
            filename = f"frame_{saved_frame_count:05d}_absFN{frame_number}.{output_format.lower()}"
            output_path = os.path.join(output_folder, filename)
            
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

    finally:
        cap.release()

    return True, extracted_frame_info

def extract_shot_boundary_frames(
    video_path: str, 
    output_folder: str, 
    logger: logging.Logger, 
    output_format: str = "jpg",
    detector_threshold: float = 27.0, 
    start_time_sec: Optional[float] = None, 
    end_time_sec: Optional[float] = None
) -> Tuple[bool, List[Dict[str, Any]]]:
    """Wrapper for scene detection."""
    if not SCENEDETECT_AVAILABLE:
        logger.error("PySceneDetect not installed. Install via pip to use Shot mode.")
        return False, []

    shot_meta_list = []
    Path(output_folder).mkdir(parents=True, exist_ok=True)

    try:
        video_manager = open_video(video_path)
        scene_manager = SceneManager()
        scene_manager.add_detector(ContentDetector(threshold=detector_threshold))
        
        start_tc = FrameTimecode(timecode=start_time_sec or 0.0, fps=video_manager.frame_rate)
        end_tc = FrameTimecode(timecode=end_time_sec, fps=video_manager.frame_rate) if end_time_sec else None
        
        video_manager.seek(start_tc)

        # This might be slow for large files
        scene_manager.detect_scenes(video=video_manager, end_time=end_tc, show_progress=False)
        scene_list = scene_manager.get_scene_list(start_in_scene=True)

        # Extract the start frame of each scene
        cap_cv = cv2.VideoCapture(video_path)
        
        try:
            for i, (start, end) in enumerate(scene_list):
                frame_num = start.get_frames()
                cap_cv.set(cv2.CAP_PROP_POS_FRAMES, frame_num)
                ret, frame = cap_cv.read()
                
                if ret:
                    filename = f"shot_{i:04d}_absFN{frame_num}.{output_format.lower()}"
                    output_path = os.path.join(output_folder, filename)
                    cv2.imwrite(output_path, frame)
                    
                    shot_meta_list.append({
                        'frame_path': output_path,
                        'frame_number': frame_num,
                        'timestamp_sec': start.get_seconds(),
                        'video_filename': os.path.basename(video_path),
                        'duration_frames': (end.get_frames() - start.get_frames())
                    })
        finally:
            cap_cv.release()
            
        return True, shot_meta_list

    except Exception as e:
        logger.error(f"Shot detection failed: {e}")
        return False, []

def extract_specific_frame(
    video_path: str, 
    timestamp_sec: float, 
    output_path: str, 
    logger: logging.Logger, 
    use_gpu: bool = False
) -> bool:
    """
    Extract single frame for scrubbing.
    Note: Frequent calls to this will be slow as it opens/closes the file every time.
    Ideally, keep a VideoCapture object open in the calling class context.
    """
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return False
        
    try:
        cap.set(cv2.CAP_PROP_POS_MSEC, timestamp_sec * 1000)
        ret, frame = cap.read()
        if ret:
            cv2.imwrite(output_path, frame)
            return True
    except Exception as e:
        logger.error(f"Error extracting specific frame: {e}")
    finally:
        cap.release()
        
    return False