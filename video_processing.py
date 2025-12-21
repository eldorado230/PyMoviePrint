import cv2
import logging
import os
import shutil
import subprocess
import glob
import math
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple, Union

# --- Optional Dependency Handling ---
try:
    from scenedetect import open_video, SceneManager, FrameTimecode
    from scenedetect.detectors import ContentDetector
    SCENEDETECT_AVAILABLE = True
except ImportError:
    SCENEDETECT_AVAILABLE = False

FFMPEG_BIN = 'ffmpeg'

class VideoUtils:
    """Static utilities for system checks and FFmpeg capability probing."""
    
    @staticmethod
    def get_startup_info():
        """Suppress console windows on Windows to prevent popping up terminals."""
        if os.name == 'nt':
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            return startupinfo
        return None

    @staticmethod
    def check_ffmpeg_gpu(logger: logging.Logger) -> bool:
        """Checks if ffmpeg is installed and supports CUDA (NVDEC)."""
        if not shutil.which(FFMPEG_BIN):
            return False
        
        try:
            # Check for hardware acceleration support
            result = subprocess.run(
                [FFMPEG_BIN, '-hwaccels'], 
                capture_output=True, 
                text=True, 
                startupinfo=VideoUtils.get_startup_info(),
                timeout=5
            )
            if 'cuda' in result.stdout:
                logger.info("FFmpeg supports CUDA (NVDEC) hardware acceleration.")
                return True
        except Exception as e:
            logger.warning(f"Error checking FFmpeg capabilities: {e}")
        
        return False

    @staticmethod
    def run_ffmpeg_command(cmd: List[str], logger: logging.Logger) -> bool:
        """Helper to run ffmpeg safely with error logging."""
        logger.debug(f"Running FFmpeg: {' '.join(cmd)}")
        try:
            subprocess.run(
                cmd, 
                check=True, 
                stdout=subprocess.PIPE, 
                stderr=subprocess.PIPE, 
                startupinfo=VideoUtils.get_startup_info()
            )
            return True
        except subprocess.CalledProcessError as e:
            err = e.stderr.decode(errors='ignore') if e.stderr else "Unknown error"
            logger.warning(f"FFmpeg command failed: {err}")
            return False
        except Exception as e:
            logger.error(f"Execution error: {e}")
            return False

class VideoExtractor:
    """
    Stateful wrapper for video extraction.
    Implements Context Manager protocol to ensure file handles are always released.
    """
    def __init__(self, video_path: str, logger: Optional[logging.Logger] = None):
        self.video_path = video_path
        self.video_filename = os.path.basename(video_path)
        self.logger = logger or logging.getLogger(__name__)
        self._cap: Optional[cv2.VideoCapture] = None
        
        if not os.path.exists(video_path):
            raise FileNotFoundError(f"Video file not found: {video_path}")

    def __enter__(self):
        self._cap = cv2.VideoCapture(self.video_path)
        if not self._cap.isOpened():
            # We don't raise here immediately to allow FFmpeg-only operations 
            # to proceed even if OpenCV fails, but we log it.
            self.logger.warning(f"OpenCV failed to open {self.video_path}. Scrubbing may fail.")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._cap:
            self._cap.release()

    @property
    def properties(self) -> Tuple[float, float, int]:
        """Returns (fps, duration_sec, total_frames). Safe to call repeatedly."""
        cap = self._cap
        local_open = False
        
        if not cap or not cap.isOpened():
            cap = cv2.VideoCapture(self.video_path)
            local_open = True
            
        try:
            if not cap.isOpened(): return 24.0, 0.0, 0
            
            fps = cap.get(cv2.CAP_PROP_FPS)
            if fps <= 0: fps = 24.0
            frame_count = cap.get(cv2.CAP_PROP_FRAME_COUNT)
            duration = frame_count / fps
            return fps, duration, int(frame_count)
        finally:
            if local_open: cap.release()

    def extract_single_frame(self, timestamp_sec: float) -> Optional[Any]:
        """
        Extracts a single frame at a specific timestamp.
        Used primarily for the Scrubbing feature.
        """
        cap = self._cap
        local_open = False
        
        # Fallback if context manager wasn't used
        if not cap or not cap.isOpened():
            cap = cv2.VideoCapture(self.video_path)
            local_open = True

        try:
            if not cap.isOpened(): return None
            cap.set(cv2.CAP_PROP_POS_MSEC, timestamp_sec * 1000)
            ret, frame = cap.read()
            return frame if ret else None
        except Exception as e:
            self.logger.error(f"Scrub error: {e}")
            return None
        finally:
            if local_open: cap.release()

    def extract_timestamps(self, timestamps: List[float], output_folder: str, 
                         ext: str = "jpg", fast_preview: bool = False) -> List[Dict[str, Any]]:
        """
        OpenCV-based extraction for specific timestamps.
        Best for Grid Layouts where we need exact points in time.
        """
        results = []
        Path(output_folder).mkdir(parents=True, exist_ok=True)
        
        cap = self._cap
        local_open = False
        if not cap or not cap.isOpened():
            cap = cv2.VideoCapture(self.video_path)
            local_open = True
            
        try:
            if not cap.isOpened(): return []
            
            # Get video limits to prevent seeking past end
            fps = cap.get(cv2.CAP_PROP_FPS) or 24.0
            total_frames = cap.get(cv2.CAP_PROP_FRAME_COUNT)
            duration = total_frames / fps

            self.logger.info(f"Extracting {len(timestamps)} frames via OpenCV...")

            for i, ts in enumerate(timestamps):
                # Clamp timestamp
                ts = max(0.0, min(ts, duration - 0.1))
                
                cap.set(cv2.CAP_PROP_POS_MSEC, ts * 1000)
                ret, frame = cap.read()

                if ret:
                    if fast_preview:
                        h, w = frame.shape[:2]
                        if w > 480:
                            scale = 480 / w
                            frame = cv2.resize(frame, (480, int(h * scale)), interpolation=cv2.INTER_AREA)

                    # Create filename
                    safe_ts = f"{ts:.2f}".replace('.', '_')
                    fname = f"thumb_{i:03d}_ts{safe_ts}.{ext}"
                    out_path = os.path.join(output_folder, fname)
                    
                    try:
                        cv2.imwrite(out_path, frame)
                        results.append({
                            'frame_path': out_path,
                            'frame_number': int(ts * fps),
                            'timestamp_sec': ts,
                            'video_filename': self.video_filename
                        })
                    except OSError as e:
                        self.logger.warning(f"Write failed {out_path}: {e}")
        finally:
            if local_open: cap.release()
            
        return results

    def extract_shots(self, output_folder: str, threshold: float = 27.0, 
                     ext: str = "jpg") -> List[Dict[str, Any]]:
        """
        PySceneDetect wrapper.
        Finds scene changes, then extracts the first frame of every new scene.
        """
        if not SCENEDETECT_AVAILABLE:
            self.logger.error("PySceneDetect not installed.")
            return []

        results = []
        Path(output_folder).mkdir(parents=True, exist_ok=True)

        try:
            video_manager = open_video(self.video_path)
            scene_manager = SceneManager()
            scene_manager.add_detector(ContentDetector(threshold=threshold))
            
            # Detect
            scene_manager.detect_scenes(video=video_manager, show_progress=True)
            scene_list = scene_manager.get_scene_list(start_in_scene=True)

            # Extract
            # We use the internal method to reuse logic/handles
            for i, (start, end) in enumerate(scene_list):
                ts = start.get_seconds()
                frame = self.extract_single_frame(ts)
                
                if frame is not None:
                    fname = f"shot_{i:04d}_ts{ts:.2f}.{ext}"
                    out_path = os.path.join(output_folder, fname)
                    cv2.imwrite(out_path, frame)
                    
                    results.append({
                        'frame_path': out_path,
                        'timestamp_sec': ts,
                        'duration_frames': (end.get_frames() - start.get_frames()),
                        'video_filename': self.video_filename,
                        'frame_number': start.get_frames()
                    })
        except Exception as e:
            self.logger.error(f"Shot detection failed: {e}")
            
        return results

    def extract_via_ffmpeg(self, output_folder: str, 
                          interval_sec: Optional[float] = None,
                          interval_frames: Optional[int] = None,
                          ext: str = "jpg", 
                          use_gpu: bool = False,
                          start_time: float = 0.0,
                          end_time: Optional[float] = None,
                          fast_preview: bool = False) -> List[Dict[str, Any]]:
        """
        Robust FFmpeg extraction with GPU fallback and file renaming.
        Preferred for "Interval" mode as it is generally faster than OpenCV loops.
        """
        if not shutil.which(FFMPEG_BIN):
            self.logger.error("FFmpeg binary not found.")
            return []

        results = []
        Path(output_folder).mkdir(parents=True, exist_ok=True)
        
        # 1. Calculate properties
        fps, duration, _ = self.properties
        if fps <= 0: fps = 24.0

        # 2. Construct Filters
        filters = []
        if interval_sec:
            filters.append(f"fps=1/{interval_sec:.5f}")
        elif interval_frames:
            # "Select every Nth frame"
            filters.append(f"select='not(mod(n,{interval_frames}))',vsync=vfr")
        else:
            filters.append("fps=1") # Default 1 sec

        if fast_preview:
            filters.append("scale=480:-1")

        vf_filter = ",".join(filters)
        q_scale = '5' if fast_preview else '2' # 2 is high quality
        
        # 3. Build Command
        # Output pattern: ffmpeg_out_00001.jpg
        output_pattern = os.path.join(output_folder, f"ffmpeg_out_%05d.{ext}")
        
        base_cmd = [FFMPEG_BIN]
        input_args = ['-ss', str(start_time), '-i', self.video_path, '-sn', '-an', '-dn']
        
        duration_args = []
        if end_time:
            duration_val = end_time - start_time
            if duration_val > 0:
                duration_args = ['-t', str(duration_val)]

        output_args = duration_args + [
            '-vf', vf_filter,
            '-frame_pts', '1',
            '-q:v', q_scale,
            output_pattern,
            '-y', '-hide_banner', '-loglevel', 'error'
        ]

        # 4. Execute with Fallback Strategy
        success = False
        if use_gpu:
            # NVDEC attempt
            gpu_cmd = base_cmd + ['-hwaccel', 'cuda'] + input_args + output_args
            if VideoUtils.run_ffmpeg_command(gpu_cmd, self.logger):
                success = True
        
        if not success:
            if use_gpu: self.logger.info("GPU failed/unavailable, falling back to CPU.")
            cpu_cmd = base_cmd + input_args + output_args
            if not VideoUtils.run_ffmpeg_command(cpu_cmd, self.logger):
                self.logger.error("FFmpeg extraction completely failed.")
                return []

        # 5. Post-Process: Rename files to match application standard
        # Standard: frame_{i}_absFN{frame}.jpg
        generated_files = sorted(glob.glob(os.path.join(output_folder, f"ffmpeg_out_*.{ext}")))
        
        for i, file_path in enumerate(generated_files):
            # Estimate timestamps based on interval
            # Note: This is an estimation. FFmpeg frame extraction is accurate, 
            # but mapping index back to exact timestamp requires math.
            if interval_sec:
                est_time = start_time + (i * interval_sec)
                est_frame = int(est_time * fps)
            elif interval_frames:
                est_frame = int(start_time * fps) + (i * interval_frames)
                est_time = est_frame / fps
            else:
                est_time = 0; est_frame = 0

            final_name = f"frame_{i:05d}_absFN{est_frame}.{ext}"
            final_path = os.path.join(output_folder, final_name)

            try:
                os.rename(file_path, final_path)
                results.append({
                    'frame_path': final_path,
                    'frame_number': est_frame,
                    'timestamp_sec': round(est_time, 3),
                    'video_filename': self.video_filename
                })
            except OSError:
                pass # Rename failed, skip

        return results

# --- BACKWARD COMPATIBILITY WRAPPERS (Add these to fix the Attribute Error) ---

def extract_frames_from_timestamps(video_path: str, timestamps: List[float], output_folder: str, 
                                  logger: logging.Logger, output_format: str = "jpg", 
                                  fast_preview: bool = False) -> Tuple[bool, List[Dict]]:
    """Wrapper to maintain compatibility with movieprint_gui.py and legacy calls."""
    try:
        with VideoExtractor(video_path, logger) as extractor:
            meta = extractor.extract_timestamps(
                timestamps=timestamps,
                output_folder=output_folder,
                ext=output_format,
                fast_preview=fast_preview
            )
        return True, meta
    except Exception as e:
        logger.error(f"Error in extract_frames_from_timestamps: {e}")
        return False, []

def extract_shot_boundary_frames(video_path: str, output_folder: str, logger: logging.Logger, 
                                detector_threshold: float = 27.0, output_format: str = "jpg", 
                                start_time_sec: float = 0.0, end_time_sec: float = None) -> Tuple[bool, List[Dict]]:
    """Wrapper for shot detection calls."""
    try:
        with VideoExtractor(video_path, logger) as extractor:
            meta = extractor.extract_shots(
                output_folder=output_folder,
                threshold=detector_threshold,
                ext=output_format
            )
            # Filter by time if needed (since SceneDetect usually scans whole file in this basic impl)
            if start_time_sec > 0 or end_time_sec is not None:
                filtered = []
                for item in meta:
                    ts = item['timestamp_sec']
                    if ts < start_time_sec: continue
                    if end_time_sec is not None and ts > end_time_sec: continue
                    filtered.append(item)
                meta = filtered
                
        return True, meta
    except Exception as e:
        logger.error(f"Error in extract_shot_boundary_frames: {e}")
        return False, []

def extract_frames(video_path: str, output_folder: str, logger: logging.Logger, 
                   interval_seconds: float = None, interval_frames: int = None,
                   output_format: str = "jpg", start_time_sec: float = 0.0, 
                   end_time_sec: float = None, use_gpu: bool = False, 
                   fast_preview: bool = False) -> Tuple[bool, List[Dict]]:
    """Wrapper for FFmpeg interval extraction calls."""
    try:
        with VideoExtractor(video_path, logger) as extractor:
            meta = extractor.extract_via_ffmpeg(
                output_folder=output_folder,
                interval_sec=interval_seconds,
                interval_frames=interval_frames,
                ext=output_format,
                use_gpu=use_gpu,
                start_time=start_time_sec,
                end_time=end_time_sec,
                fast_preview=fast_preview
            )
        return True, meta
    except Exception as e:
        logger.error(f"Error in extract_frames: {e}")
        return False, []