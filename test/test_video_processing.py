import unittest
import os
import shutil
import cv2
import numpy as np
from video_processing import extract_frames, extract_shot_boundary_frames
import logging

class TestVideoProcessing(unittest.TestCase):
    def setUp(self):
        self.test_dir = "test_videos"
        os.makedirs(self.test_dir, exist_ok=True)
        self.video_path = os.path.join(self.test_dir, "test_video.mp4")
        self.output_dir = "test_output"
        os.makedirs(self.output_dir, exist_ok=True)
        # Create a dummy video file for testing
        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        out = cv2.VideoWriter(self.video_path, fourcc, 20.0, (640, 480))
        for i in range(60):  # 3 seconds of video
            frame = np.zeros((480, 640, 3), np.uint8)
            if i < 30:
                frame[:] = (255, 0, 0)  # Blue
            else:
                frame[:] = (0, 0, 255)  # Red
            out.write(frame)
        out.release()
        self.logger = logging.getLogger()

    def tearDown(self):
        shutil.rmtree(self.test_dir)
        shutil.rmtree(self.output_dir)

    def test_extract_frames(self):
        success, frames = extract_frames(self.video_path, self.output_dir, self.logger, interval_seconds=1)
        self.assertTrue(success)
        self.assertEqual(len(frames), 3)

    def test_extract_shot_boundary_frames(self):
        success, frames = extract_shot_boundary_frames(self.video_path, self.output_dir, self.logger)
        self.assertTrue(success)
        self.assertGreater(len(frames), 0)

    def test_extract_shot_boundary_frames_with_time_segment(self):
        # This test should fail before the fix and pass after
        success, frames = extract_shot_boundary_frames(self.video_path, self.output_dir, self.logger, start_time_sec=1, end_time_sec=2, detector_threshold=15.0)
        self.assertTrue(success)
        self.assertEqual(len(frames), 1)

if __name__ == '__main__':
    unittest.main()
