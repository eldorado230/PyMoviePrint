from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path, old, new, label):
    file_path = ROOT / path
    text = file_path.read_text(encoding='utf-8')
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one match in {path}, found {count}")
    file_path.write_text(text.replace(old, new, 1), encoding='utf-8')


# Preview geometry must use the same final-resolution coordinate system as export.
replace_once(
    'movieprint_gui.py',
    '''    def _grid_transform_params(self):\n        return {\n            'crop_top': float(self.crop_top_var.get() or 0),\n            'crop_right': float(self.crop_right_var.get() or 0),\n            'crop_bottom': float(self.crop_bottom_var.get() or 0),\n            'crop_left': float(self.crop_left_var.get() or 0),\n            'thumbnail_aspect_ratio': self.thumbnail_aspect_ratio_var.get(),\n            'sort_mode': self.sort_mode_var.get(),\n            'filter_mode': self.filter_mode_var.get(),\n        }\n\n    @staticmethod\n    def _snapshot_render_metadata(metadata):\n''',
    '''    def _grid_transform_params(self):\n        return {\n            'crop_top': float(self.crop_top_var.get() or 0),\n            'crop_right': float(self.crop_right_var.get() or 0),\n            'crop_bottom': float(self.crop_bottom_var.get() or 0),\n            'crop_left': float(self.crop_left_var.get() or 0),\n            'thumbnail_aspect_ratio': self.thumbnail_aspect_ratio_var.get(),\n            'sort_mode': self.sort_mode_var.get(),\n            'filter_mode': self.filter_mode_var.get(),\n        }\n\n    def _preview_target_thumbnail_width(\n        self, video_path=None, *, layout_mode=None, fit_to_output_params=None, rotation=None\n    ):\n        \"\"\"Use final-frame geometry for grid previews while keeping fast preview pixels.\"\"\"\n        layout_mode = self.layout_mode_var.get() if layout_mode is None else layout_mode\n        fit_to_output_params = (\n            self.fit_to_output_params_var.get()\n            if fit_to_output_params is None else fit_to_output_params\n        )\n        if layout_mode != 'grid' or fit_to_output_params:\n            return None\n\n        video_path = video_path or self._source_video_path()\n        if not video_path or not os.path.isfile(video_path):\n            return None\n\n        cv2 = DependencyManager.video_processing.cv2\n        cap = cv2.VideoCapture(video_path)\n        try:\n            if not cap.isOpened():\n                return None\n            width = int(round(float(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)))\n            height = int(round(float(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)))\n        finally:\n            if cap.isOpened():\n                cap.release()\n\n        if width <= 0 or height <= 0:\n            return None\n        rotation = int(self.rotate_thumbnails_var.get()) if rotation is None else int(rotation)\n        return height if rotation in (90, 270) else width\n\n    @staticmethod\n    def _snapshot_render_metadata(metadata):\n''',
    'add final-geometry preview helper',
)

replace_once(
    'movieprint_gui.py',
    '''            'filter_mode': settings.filter_mode,\n        }\n\n        success, layout = DependencyManager.image_grid.create_image_grid(**grid_params)\n''',
    '''            'filter_mode': settings.filter_mode,\n            'target_thumbnail_width': self._preview_target_thumbnail_width(\n                layout_mode=settings.layout_mode,\n                fit_to_output_params=settings.fit_to_output_params,\n                rotation=settings.rotate_thumbnails,\n            ),\n        }\n\n        success, layout = DependencyManager.image_grid.create_image_grid(**grid_params)\n''',
    'restore project preview in final geometry',
)

replace_once(
    'movieprint_gui.py',
    '''            'filter_mode': self.filter_mode_var.get(),\n            'cancel_event': threading.Event(),\n        }\n''',
    '''            'filter_mode': self.filter_mode_var.get(),\n            'target_thumbnail_width': self._preview_target_thumbnail_width(preview_target_path),\n            'cancel_event': threading.Event(),\n        }\n''',
    'capture final grid geometry for initial preview',
)

replace_once(
    'movieprint_gui.py',
    '''                    thumbnail_aspect_ratio=config['thumbnail_aspect_ratio'],\n                    sort_mode=config['sort_mode'],\n                    filter_mode=config['filter_mode'],\n                )\n''',
    '''                    thumbnail_aspect_ratio=config['thumbnail_aspect_ratio'],\n                    sort_mode=config['sort_mode'],\n                    filter_mode=config['filter_mode'],\n                    target_thumbnail_width=config['target_thumbnail_width'],\n                )\n''',
    'render initial preview in final grid coordinates',
)

replace_once(
    'movieprint_gui.py',
    '''            output_height=int(self.output_height_var.get()),\n            **transform_params,\n        )\n''',
    '''            output_height=int(self.output_height_var.get()),\n            target_thumbnail_width=self._preview_target_thumbnail_width(),\n            **transform_params,\n        )\n''',
    'render refreshed preview in final grid coordinates',
)

# Regression: low-resolution preview sources rendered with the final target width
# must produce exactly the same grid geometry as full-resolution export sources.
(ROOT / 'tests' / 'test_wysiwyg_preview_geometry.py').write_text('''import logging\n\nfrom PIL import Image\n\nimport image_grid\n\n\ndef _render(tmp_path, name, source_size, target_thumbnail_width=None):\n    paths = []\n    for index in range(6):\n        path = tmp_path / f"{name}_{index}.png"\n        Image.new("RGB", source_size, "white").save(path)\n        paths.append(str(path))\n\n    output = tmp_path / f"{name}.png"\n    ok, layout = image_grid.create_image_grid(\n        image_source_data=paths,\n        output_path=str(output),\n        layout_mode="grid",\n        columns=3,\n        rows=2,\n        padding=8,\n        grid_margin=8,\n        rounded_corners=18,\n        show_header=False,\n        show_file_path=False,\n        show_timecode=False,\n        show_frame_num=False,\n        frame_info_show=False,\n        background_color_hex="#000000",\n        target_thumbnail_width=target_thumbnail_width,\n        fit_to_output_params=False,\n        logger=logging.getLogger("test"),\n    )\n    assert ok is True\n    with Image.open(output) as rendered:\n        size = rendered.size\n    geometry = [(item["x"], item["y"], item["width"], item["height"]) for item in layout]\n    return size, geometry\n\n\ndef test_fast_preview_uses_exact_final_grid_geometry(tmp_path):\n    preview = _render(tmp_path, "preview", (480, 270), target_thumbnail_width=1920)\n    final = _render(tmp_path, "final", (1920, 1080), target_thumbnail_width=None)\n    assert preview == final\n\n\ndef test_fixed_resolution_does_not_need_dynamic_target_width(tmp_path):\n    paths = []\n    for index in range(2):\n        path = tmp_path / f"fixed_{index}.png"\n        Image.new("RGB", (480, 270), "white").save(path)\n        paths.append(str(path))\n    out_a = tmp_path / "fixed_a.png"\n    out_b = tmp_path / "fixed_b.png"\n    common = dict(\n        image_source_data=paths, layout_mode="grid", columns=2, rows=1,\n        padding=8, grid_margin=8, rounded_corners=0, show_header=False,\n        frame_info_show=False, fit_to_output_params=True, output_width=1920,\n        output_height=1080, logger=logging.getLogger("test"),\n    )\n    ok_a, layout_a = image_grid.create_image_grid(output_path=str(out_a), target_thumbnail_width=None, **common)\n    ok_b, layout_b = image_grid.create_image_grid(output_path=str(out_b), target_thumbnail_width=1920, **common)\n    assert ok_a and ok_b\n    assert layout_a == layout_b\n''', encoding='utf-8')
