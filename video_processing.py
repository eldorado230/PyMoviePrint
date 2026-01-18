import cv2
import logging
import os
import shutil
import subprocess
import glob
import math
import json
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

FFMPEG_BIN = 'ffmpeg'
FFPROBE_BIN = 'ffprobe'

class VideoUtils:
    """Static utilities for system checks and FFmpeg capability probing."""
    
    _gpu_checked: Optional[bool] = None
    _zscale_checked: Optional[bool] = None

    @staticmethod
    def get_startup_info():
        """Suppress console windows on Windows."""
        if os.name == 'nt':
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            return startupinfo
        return None

    @staticmethod
    def check_ffmpeg_gpu(logger: logging.Logger) -> bool:
        """Checks if ffmpeg supports CUDA (NVDEC). Cached."""
        if VideoUtils._gpu_checked is not None:
            return VideoUtils._gpu_checked

        if not shutil.which(FFMPEG_BIN):
            VideoUtils._gpu_checked = False
            return False
            
        try:
            result = subprocess.run(
                [FFMPEG_BIN, '-hwaccels'], 
                capture_output=True, 
                text=True, 
                startupinfo=VideoUtils.get_startup_info(), 
                timeout=5
            )
            VideoUtils._gpu_checked = 'cuda' in result.stdout
            if VideoUtils._gpu_checked:
                logger.debug("FFmpeg supports CUDA (NVDEC).")
        except Exception:
            VideoUtils._gpu_checked = False
            
        return VideoUtils._gpu_checked

    @staticmethod
    def check_ffmpeg_zscale(logger: logging.Logger) -> bool:
        """Checks if ffmpeg has zscale support. Cached."""
        if VideoUtils._zscale_checked is not None:
            return VideoUtils._zscale_checked

        if not shutil.which(FFMPEG_BIN):
            VideoUtils._zscale_checked = False
            return False

        try:
            result = subprocess.run(
                [FFMPEG_BIN, '-filters'], 
                capture_output=True, 
                text=True, 
                startupinfo=VideoUtils.get_startup_info(), 
                timeout=5
            )
            VideoUtils._zscale_checked = 'zscale' in result.stdout
            if VideoUtils._zscale_checked:
                logger.debug("FFmpeg supports zscale filter.")
        except Exception:
            VideoUtils._zscale_checked = False
            
        return VideoUtils._zscale_checked

    @staticmethod
    def run_ffmpeg_command(cmd: List[str], logger: logging.Logger) -> bool:
        try:
            process = subprocess.run(
                cmd, 
                check=True, 
                stdout=subprocess.PIPE, 
                stderr=subprocess.PIPE, 
                startupinfo=VideoUtils.get_startup_info()
            )
            return True
        except subprocess.CalledProcessError as e:
            try:
                err_msg = e.stderr.decode('utf-8', errors='replace')
            except:
                err_msg = str(e.stderr)
            
            relevant_lines = "\n".join(err_msg.splitlines()[-10:])
            logger.error(f"FFmpeg failed.\nCommand: {' '.join(cmd)}\nError tail: {relevant_lines}")
            return False
        except Exception as e:
            logger.error(f"Execution error: {e}")
            return False

class VideoExtractor:
    def __init__(self, video_path: str, logger: Optional[logging.Logger] = None):
        self.video_path = video_path
        self.video_filename = os.path.basename(video_path)
        self.logger = logger or logging.getLogger(__name__)
        self._cap: Optional[cv2.VideoCapture] = None
        self._is_hdr_confirmed = None 
        
        if not os.path.exists(video_path):
            raise FileNotFoundError(f"Video file not found: {video_path}")

    def __enter__(self):
        self._cap = cv2.VideoCapture(self.video_path)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._cap: self._cap.release()

    @property
    def properties(self) -> Tuple[float, float, int]:
        cap = self._cap
        local_open = False
        if not cap or not cap.isOpened():
            cap = cv2.VideoCapture(self.video_path)
            local_open = True
        try:
            if not cap.isOpened(): return 24.0, 0.0, 0
            fps = cap.get(cv2.CAP_PROP_FPS)
            if fps <= 0: fps = 24.0
            frames = cap.get(cv2.CAP_PROP_FRAME_COUNT)
            return fps, frames / fps, int(frames)
        finally:
            if local_open: cap.release()

    def detect_hdr(self) -> bool:
        """
        Detects if video is HDR based on color transfer/primaries.
        FIX: Removed 'Main 10' assumption to avoid false positives on 10-bit SDR.
        """
        if self._is_hdr_confirmed is not None:
            return self._is_hdr_confirmed

        if not shutil.which(FFPROBE_BIN): 
            self._is_hdr_confirmed = False
            return False
        
        cmd = [
            FFPROBE_BIN, '-v', 'error', '-select_streams', 'v:0',
            '-show_entries', 'stream=color_transfer,color_space,color_primaries',
            '-of', 'json', self.video_path
        ]
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, startupinfo=VideoUtils.get_startup_info())
            data = json.loads(res.stdout)
            streams = data.get('streams', [])
            if not streams: 
                self._is_hdr_confirmed = False
                return False
            
            s = streams[0]
            transfer = s.get('color_transfer', '').lower()
            primaries = s.get('color_primaries', '').lower()
            
            # Strict HDR signatures
            hdr_signatures = ['smpte2084', 'arib-std-b67', 'bt2020']
            
            is_hdr = any(sig in transfer for sig in hdr_signatures) or ('bt2020' in primaries)
            
            self._is_hdr_confirmed = is_hdr
            return is_hdr
        except Exception:
            self._is_hdr_confirmed = False
            return False

    def extract_single_frame(self, timestamp_sec: float) -> Optional[Any]:
        cap = self._cap
        local_open = False
        if not cap or not cap.isOpened():
            cap = cv2.VideoCapture(self.video_path)
            local_open = True
        try:
            if not cap.isOpened(): return None
            cap.set(cv2.CAP_PROP_POS_MSEC, timestamp_sec * 1000)
            ret, frame = cap.read()
            return frame if ret else None
        finally:
            if local_open: cap.release()

    def _build_hdr_filter_chain(self, hdr_algorithm: str) -> str:
        has_zscale = VideoUtils.check_ffmpeg_zscale(self.logger)
        algo = hdr_algorithm.lower() if hdr_algorithm else 'hable'
        
        pre_filter = "format=p010le"

        if has_zscale:
            return (
                f"{pre_filter},"
                "zscale=tin=smpte2084:pin=bt2020:rin=tv:t=linear:npl=100,format=gbrpf32le,"
                f"tonemap=tonemap={algo}:desat=0,"
                "zscale=p=bt709:m=bt709:t=bt709:r=tv,format=yuv420p"
            )
        else:
            self.logger.warning("Zscale missing. Using native 'tonemap' fallback filter.")
            return (
                f"{pre_filter},"
                "scale=in_color_matrix=bt2020:out_color_matrix=bt2020:out_range=tv,"
                "format=gbrp16le,"
                f"tonemap=tonemap={algo}:desat=0,"
                "format=yuv420p"
            )

    def extract_timestamps_optimized(self, timestamps: List[float], output_folder: str, ext: str = "jpg", 
                                      fast_preview: bool = False, hdr_tonemap: bool = False, hdr_algorithm: str = 'hable') -> List[Dict[str, Any]]:
        """
        Extracts frames using FFmpeg Seeking (-ss).
        Handles BOTH SDR and HDR content.
        """
        if not shutil.which(FFMPEG_BIN):
            self.logger.error("FFmpeg not found.")
            return []

        results = []
        Path(output_folder).mkdir(parents=True, exist_ok=True)
        
        fps, _, _ = self.properties
        if fps <= 0: fps = 24.0

        # Safety Lock for HDR Tone Mapping
        use_gpu = False
        if not hdr_tonemap and VideoUtils.check_ffmpeg_gpu(self.logger):
             use_gpu = True
             # Log once per batch to avoid spam
             if hasattr(self, '_logged_gpu'): pass
             else: 
                 self.logger.info("  >> GPU Acceleration Enabled.")
                 self._logged_gpu = True
        elif hdr_tonemap:
             # GPU must be disabled for tone mapping to work reliably
             pass

        hdr_filters = self._build_hdr_filter_chain(hdr_algorithm) if hdr_tonemap else ""
        total_frames = len(timestamps)
        
        for i, ts in enumerate(timestamps):
            if not fast_preview:
                self.logger.info(f"  ... Extracting frame {i+1}/{total_frames} at {ts:.2f}s ...")
            
            # Construct Filter Chain
            filters = []
            if hdr_tonemap:
                filters.append(hdr_filters)
            
            if fast_preview:
                filters.append("scale=480:-1")
            
            # Ensure standard pixel format for output if not handled by tone mapper
            if not hdr_tonemap:
                filters.append("format=yuv420p")

            vf_filter = ",".join(filters)
            q_scale = '5' if fast_preview else '2'

            final_name = f"thumb_{i:03d}_ts{ts:.2f}.{ext}"
            final_path = os.path.join(output_folder, final_name)
            
            cmd = [FFMPEG_BIN]
            if use_gpu:
                cmd.extend(['-hwaccel', 'cuda'])
            
            # Input Seeking: Fast and precise
            cmd.extend(['-ss', str(ts)]) 
            cmd.extend(['-i', self.video_path])
            
            cmd.extend([
                '-frames:v', '1',
                '-vf', vf_filter,
                '-q:v', q_scale,
                final_path,
                '-y', '-hide_banner', '-loglevel', 'error'
            ])

            success = VideoUtils.run_ffmpeg_command(cmd, self.logger)
            
            if success and os.path.exists(final_path):
                results.append({
                    'frame_path': final_path,
                    'frame_number': int(ts * fps),
                    'timestamp_sec': ts,
                    'video_filename': self.video_filename
                })

        results.sort(key=lambda x: x['timestamp_sec'])
        return results

    def extract_shots(self, output_folder: str, threshold: float = 27.0, ext: str = "jpg", hdr_tonemap: bool = False, hdr_algorithm: str = 'hable') -> List[Dict[str, Any]]:
        if not SCENEDETECT_AVAILABLE:
            self.logger.error("PySceneDetect not installed.")
            return []
            
        Path(output_folder).mkdir(parents=True, exist_ok=True)
        
        detected_shots = []
        try:
            self.logger.info("  Running shot detection (PySceneDetect)...")
            video_manager = open_video(self.video_path)
            scene_manager = SceneManager()
            scene_manager.add_detector(ContentDetector(threshold=threshold))
            scene_manager.detect_scenes(video=video_manager)
            
            scenes = scene_manager.get_scene_list(start_in_scene=True)
            self.logger.info(f"  Detected {len(scenes)} shots.")
            
            for i, (start, end) in enumerate(scenes):
                detected_shots.append({
                    'index': i,
                    'timestamp_sec': start.get_seconds(),
                    'frame_number': start.get_frames(),
                    'duration_frames': end.get_frames() - start.get_frames()
                })
        except Exception as e:
            self.logger.error(f"Shot detection error: {e}")
            return []

        if not detected_shots: return []

        timestamps = [s['timestamp_sec'] for s in detected_shots]
        
        if not hdr_tonemap and self.detect_hdr():
             self.logger.info("  [Auto-Detect] HDR content identified in Shot Mode. Enabling Tone Mapping.")
             hdr_tonemap = True

        # Use the optimized extractor for shots too
        extracted_meta = self.extract_timestamps_optimized(
            timestamps=timestamps,
            output_folder=output_folder,
            ext=ext,
            fast_preview=False,
            hdr_tonemap=hdr_tonemap,
            hdr_algorithm=hdr_algorithm
        )
        
        final_results = []
        meta_map = {round(m['timestamp_sec'], 2): m for m in extracted_meta}
        
        for shot in detected_shots:
            ts_key = round(shot['timestamp_sec'], 2)
            meta = meta_map.get(ts_key)
            if meta:
                meta['duration_frames'] = shot['duration_frames']
                final_results.append(meta)
        
        return final_results

    def extract_via_ffmpeg(self, output_folder: str, 
                          interval_sec: Optional[float] = None, interval_frames: Optional[int] = None,
                          ext: str = "jpg", use_gpu: bool = False, start_time: float = 0.0, end_time: Optional[float] = None,
                          fast_preview: bool = False,
                          hdr_tonemap: bool = False, hdr_algorithm: str = 'hable') -> List[Dict[str, Any]]:
        # This function handles the 'Interval' mode where we output many frames at once.
        # We leave this mostly as-is but ensuring GPU logic is safe.
        if not shutil.which(FFMPEG_BIN):
            self.logger.error("FFmpeg not found.")
            return []

        results = []
        Path(output_folder).mkdir(parents=True, exist_ok=True)
        fps, _, _ = self.properties
        if fps <= 0: fps = 24.0

        filters = []
        if interval_sec: filters.append(f"fps=1/{interval_sec:.5f}")
        elif interval_frames: filters.append(f"select='not(mod(n,{interval_frames}))',vsync=vfr")
        else: filters.append("fps=1")

        if hdr_tonemap: 
            filters.append(self._build_hdr_filter_chain(hdr_algorithm))
        
        if fast_preview: 
            filters.append("scale=480:-1")
        
        if not hdr_tonemap:
             filters.append("format=yuv420p")

        vf_filter = ",".join(filters)
        q_scale = '5' if fast_preview else '2'

        output_pattern = os.path.join(output_folder, f"ffmpeg_out_%05d.{ext}")
        base_cmd = [FFMPEG_BIN]
        
        if hdr_tonemap: use_gpu = False
             
        if use_gpu and VideoUtils.check_ffmpeg_gpu(self.logger):
            base_cmd.extend(['-hwaccel', 'cuda'])

        input_args = ['-ss', str(start_time), '-i', self.video_path, '-sn', '-an', '-dn']
        if end_time and (end_time - start_time > 0): 
            input_args.extend(['-t', str(end_time - start_time)])

        output_args = [
            '-vf', vf_filter, 
            '-frame_pts', '1', 
            '-q:v', q_scale, 
            output_pattern, 
            '-y', '-hide_banner', '-loglevel', 'error'
        ]

        if not VideoUtils.run_ffmpeg_command(base_cmd + input_args + output_args, self.logger):
            return []

        generated_files = sorted(glob.glob(os.path.join(output_folder, f"ffmpeg_out_*.{ext}")))
        for i, file_path in enumerate(generated_files):
            est_time = start_time + (i * interval_sec) if interval_sec else (i * interval_frames / fps if interval_frames else 0)
            est_frame = int(est_time * fps)
            final_path = os.path.join(output_folder, f"frame_{i:05d}_absFN{est_frame}.{ext}")
            try:
                os.rename(file_path, final_path)
                results.append({
                    'frame_path': final_path, 
                    'frame_number': est_frame, 
                    'timestamp_sec': round(est_time, 3), 
                    'video_filename': self.video_filename
                })
            except: pass

        return results

# Legacy Wrappers
def extract_frames_from_timestamps(video_path, timestamps, output_folder, logger, output_format="jpg", fast_preview=False, hdr_tonemap=False, hdr_algorithm='hable'):
    """
    Unified entry point for Grid/Manual timestamp extraction.
    Now uses FFmpeg 'Seek & Snap' for ALL videos (SDR and HDR) for consistent performance.
    """
    with VideoExtractor(video_path, logger) as ex: 
        # Only enable tone mapping if not forced AND detected correctly
        if not hdr_tonemap and ex.detect_hdr():
            logger.info("  [Auto-Detect] HDR content identified. Enabling Tone Mapping.")
            hdr_tonemap = True
        
        # We now use the optimized FFmpeg extractor for EVERYTHING.
        # It handles SDR (by not adding tone map filters) and HDR (by adding them) efficiently.
        return True, ex.extract_timestamps_optimized(
            timestamps, output_folder, output_format, fast_preview, hdr_tonemap, hdr_algorithm
        )

def extract_shot_boundary_frames(video_path, output_folder, logger, detector_threshold=27.0, output_format="jpg", start_time_sec=0.0, end_time_sec=None, hdr_tonemap=False, hdr_algorithm='hable'):
    with VideoExtractor(video_path, logger) as ex: 
        return True, ex.extract_shots(output_folder, detector_threshold, output_format, hdr_tonemap=hdr_tonemap, hdr_algorithm=hdr_algorithm)

def extract_frames(video_path, output_folder, logger, interval_seconds=None, interval_frames=None, output_format="jpg", start_time_sec=0.0, end_time_sec=None, use_gpu=False, fast_preview=False, hdr_tonemap=False, hdr_algorithm='hable'):
    with VideoExtractor(video_path, logger) as ex:
        if not hdr_tonemap and ex.detect_hdr():
             logger.info("  [Auto-Detect] HDR content identified. Enabling Tone Mapping.")
             hdr_tonemap = True
        meta = ex.extract_via_ffmpeg(output_folder, interval_seconds, interval_frames, output_format, use_gpu, start_time_sec, end_time_sec, fast_preview, hdr_tonemap, hdr_algorithm)
    return True, meta