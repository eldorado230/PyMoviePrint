import unittest
import os
import shutil
import cv2
import numpy as np
from movieprint_maker import execute_movieprint_generation
import argparse
import logging

class TestMovieprintMaker(unittest.TestCase):
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

    def test_execute_movieprint_generation(self):
        settings = argparse.Namespace(
            input_paths=[self.video_path],
            output_dir=self.output_dir,
            extraction_mode='interval',
            layout_mode='grid',
            interval_seconds=1,
            interval_frames=None,
            shot_threshold=27.0,
            rows=None,
            columns=3,
            target_row_height=150,
            output_image_width=1920,
            padding=5,
            max_frames_for_print=None,
            target_thumbnail_width=None,
            background_color='#FFFFFF',
            frame_format='jpg',
            save_metadata_json=False,
            detect_faces=False,
            rotate_thumbnails=0,
            start_time=None,
            end_time=None,
            exclude_frames=None,
            exclude_shots=None,
            output_filename_suffix='_movieprint',
            output_filename=None,
            video_extensions='.mp4,.avi,.mov,.mkv,.flv,.wmv',
            recursive_scan=False,
            temp_dir=None,
            haar_cascade_xml=None,
            max_output_filesize_kb=None,
            grid_margin=0,
            show_header=True,
            show_file_path=True,
            show_timecode=True,
            show_frame_num=True,
            rounded_corners=0,
            frame_info_show=True,
            frame_info_timecode_or_frame="timecode",
            frame_info_font_color="#FFFFFF",
            frame_info_bg_color="#000000",
            frame_info_position="bottom_left",
            frame_info_size=10,
            frame_info_margin=5
        )
        successful_ops, failed_ops = execute_movieprint_generation(settings, self.logger)
        self.assertEqual(len(successful_ops), 1)
        self.assertEqual(len(failed_ops), 0)
        self.assertTrue(os.path.exists(successful_ops[0]['output']))

if __name__ == '__main__':
    unittest.main()
