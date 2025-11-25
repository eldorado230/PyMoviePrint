from PIL import Image, ImageDraw, ImageColor, ImageFont, ImageChops
import logging
import os
import math
import shutil
import platform
from dataclasses import dataclass, field
from typing import List, Tuple, Optional, Dict, Union, Any

# --- Configuration Data Classes ---

@dataclass
class FontConfig:
    """Handles font settings."""
    show_header: bool = True
    show_file_path: bool = True
    show_timecode: bool = True
    show_frame_num: bool = True
    frame_info_show: bool = True
    frame_info_type: str = "timecode"  # 'timecode' or 'frame'
    font_color: str = "#FFFFFF"
    bg_color: str = "#000000"
    position: str = "bottom_left"
    size: int = 12
    margin: int = 5
    
    def get_font_path(self) -> str:
        system = platform.system()
        if system == "Windows": return "arial.ttf"
        elif system == "Darwin": return "/System/Library/Fonts/Helvetica.ttc"
        else: return "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"

@dataclass
class GridConfig:
    """Consolidates visual settings."""
    output_path: str
    # Grid Specific
    columns: int = 5
    target_thumb_width: Optional[int] = None
    
    # Timeline Specific
    layout_mode: str = "grid" # 'grid' or 'timeline'
    target_row_height: int = 150
    output_width: int = 1920
    
    # Common
    padding: int = 5
    bg_color_hex: str = "#1E1E1E"
    grid_margin: int = 0
    rounded_corners: int = 0
    rotation: int = 0
    quality: int = 95
    font_settings: FontConfig = field(default_factory=FontConfig)

# --- Helper Functions ---

def _load_font(name_or_path: str, size: int) -> ImageFont.FreeTypeFont:
    try: return ImageFont.truetype(name_or_path, size)
    except IOError:
        try: return ImageFont.truetype("arial.ttf", size)
        except IOError: return ImageFont.load_default()

def _apply_rotation(img: Image.Image, rotation: int) -> Image.Image:
    if rotation == 90: return img.rotate(-90, expand=True)
    elif rotation == 180: return img.rotate(180)
    elif rotation == 270: return img.rotate(-270, expand=True)
    return img

def _apply_rounding(img: Image.Image, radius: int) -> Image.Image:
    """
    Applies rounded corners to an image by modifying its alpha channel.
    """
    if radius <= 0:
        return img
    
    # Ensure we are working with RGBA to have an alpha channel
    img = img.convert("RGBA")
    
    # Create a mask (white = visible, black = transparent)
    mask = Image.new('L', img.size, 0)
    draw = ImageDraw.Draw(mask)
    
    # Draw the white rounded rectangle
    draw.rounded_rectangle([(0, 0), img.size], radius=radius, fill=255)
    
    # Combine the new mask with the existing alpha channel (if any)
    # This preserves existing transparency inside the image while cropping corners
    existing_alpha = img.split()[3]
    final_alpha = ImageChops.multiply(existing_alpha, mask)
    
    img.putalpha(final_alpha)
    return img

def _draw_frame_info(draw, text, img_w, img_h, conf, font):
    bbox = draw.textbbox((0, 0), text, font=font)
    text_w, text_h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    m = conf.margin
    
    if conf.position == "bottom_left": x, y = m, img_h - text_h - m - 4
    elif conf.position == "bottom_right": x, y = img_w - text_w - m - 4, img_h - text_h - m - 4
    elif conf.position == "top_left": x, y = m, m
    elif conf.position == "top_right": x, y = img_w - text_w - m - 4, m
    else: x, y = m, m

    draw.rectangle((x - 2, y - 2, x + text_w + 2, y + text_h + 2), fill=conf.bg_color)
    draw.text((x, y), text, font=font, fill=conf.font_color)

# --- Layout Engines ---

def _create_fixed_column_grid(image_paths: List[str], config: GridConfig, logger: logging.Logger):
    """Standard grid layout."""
    layout_data = []
    if not image_paths: return False, []

    # 1. Determine Cell Size
    cell_w, cell_h = 0, 0
    
    # Simple autosizing logic
    max_w, max_h = 0, 0
    for p in image_paths[:5]: # Check first few to guess size
        try:
            with Image.open(p) as img:
                if config.rotation in [90, 270]: w, h = img.height, img.width
                else: w, h = img.size
                max_w = max(max_w, w)
                max_h = max(max_h, h)
        except: pass
    
    cell_w = config.target_thumb_width if config.target_thumb_width else (max_w or 200)
    # Maintain aspect ratio for height if possible, else default
    if max_w > 0: cell_h = int(cell_w * (max_h / max_w))
    else: cell_h = 150

    num_images = len(image_paths)
    rows = math.ceil(num_images / config.columns)
    
    header_height = 50 if config.font_settings.show_header else 0
    grid_w = (config.columns * cell_w) + ((config.columns - 1) * config.padding) + (2 * config.grid_margin)
    grid_h = (rows * cell_h) + ((rows - 1) * config.padding) + (2 * config.grid_margin) + header_height

    try:
        bg_rgb = ImageColor.getrgb(config.bg_color_hex)
        grid_image = Image.new("RGB", (grid_w, grid_h), bg_rgb)
    except: return False, []

    draw = ImageDraw.Draw(grid_image)
    if config.font_settings.show_header:
        f = _load_font(config.font_settings.get_font_path(), 20)
        draw.text((config.grid_margin, config.grid_margin), os.path.basename(image_paths[0]), font=f, fill=config.font_settings.font_color)

    current_x = config.grid_margin
    current_y = config.grid_margin + header_height
    info_font = _load_font(config.font_settings.get_font_path(), config.font_settings.size)

    for i, path in enumerate(image_paths):
        try:
            with Image.open(path) as img:
                # 1. Rotate
                img = _apply_rotation(img, config.rotation)
                img = img.convert("RGBA")
                
                # 2. Resize
                img.thumbnail((cell_w, cell_h), Image.Resampling.BICUBIC)
                
                # 3. Apply Rounded Corners (New Step)
                if config.rounded_corners > 0:
                    img = _apply_rounding(img, config.rounded_corners)
                
                # Center content if aspect ratio differs (though usually exact match here)
                paste_x = current_x + (cell_w - img.width) // 2
                paste_y = current_y + (cell_h - img.height) // 2

                if config.font_settings.frame_info_show:
                    d_tmp = ImageDraw.Draw(img)
                    label = f"TC: {i}" if config.font_settings.frame_info_type == "timecode" else f"#{i}"
                    _draw_frame_info(d_tmp, label, img.width, img.height, config.font_settings, info_font)

                # Paste using the image itself as the mask to preserve transparency (corners)
                grid_image.paste(img, (paste_x, paste_y), mask=img)
                layout_data.append({'image_path': path, 'x': paste_x, 'y': paste_y, 'width': img.width, 'height': img.height})

        except Exception as e: logger.error(f"Error thumb {path}: {e}")

        if (i + 1) % config.columns == 0:
            current_x = config.grid_margin
            current_y += cell_h + config.padding
        else:
            current_x += cell_w + config.padding

    try:
        grid_image.save(config.output_path, quality=config.quality)
        return True, layout_data
    except Exception: return False, []

def _create_timeline_grid(source_data: List[Dict[str, Any]], config: GridConfig, logger: logging.Logger):
    """
    Timeline layout: Rows are packed greedily; images have variable width based on 'width_ratio' (duration).
    """
    layout_data = []
    if not source_data: return False, []

    target_h = config.target_row_height
    max_w = config.output_width - (2 * config.grid_margin)
    
    rows = []
    current_row = []
    current_row_width = 0
    
    # Pre-calculate items
    items = []
    for item in source_data:
        try:
            with Image.open(item['image_path']) as img:
                 native_w, native_h = img.size
                 aspect = native_w / native_h
                 base_w = int(target_h * aspect)
                 items.append({'path': item['image_path'], 'w': base_w, 'h': target_h})
        except: continue

    # Pack rows
    for item in items:
        if current_row_width + item['w'] + config.padding > max_w:
            rows.append(current_row)
            current_row = []
            current_row_width = 0
        current_row.append(item)
        current_row_width += item['w'] + config.padding
    if current_row: rows.append(current_row)
    
    header_height = 50 if config.font_settings.show_header else 0
    total_grid_h = (len(rows) * (target_h + config.padding)) + header_height + (2 * config.grid_margin)
    
    try:
        bg_rgb = ImageColor.getrgb(config.bg_color_hex)
        grid_image = Image.new("RGB", (config.output_width, total_grid_h), bg_rgb)
    except: return False, []
    
    draw = ImageDraw.Draw(grid_image)
    if config.font_settings.show_header and source_data:
        f = _load_font(config.font_settings.get_font_path(), 20)
        draw.text((config.grid_margin, config.grid_margin), os.path.basename(source_data[0]['image_path']), font=f, fill=config.font_settings.font_color)
        
    y = config.grid_margin + header_height
    info_font = _load_font(config.font_settings.get_font_path(), config.font_settings.size)
    
    for row in rows:
        x = config.grid_margin
        row_content_w = sum(i['w'] for i in row) + ((len(row)-1) * config.padding)
        available_w = max_w
        
        scale = 1.0
        if row_content_w > 0 and row != rows[-1]:
             scale = available_w / row_content_w
        
        for item in row:
            try:
                draw_w = int(item['w'] * scale)
                draw_h = target_h 
                
                with Image.open(item['path']) as img:
                    # 1. Rotate
                    img = _apply_rotation(img, config.rotation)
                    img = img.convert("RGBA")
                    
                    # 2. Resize
                    img = img.resize((draw_w, target_h), Image.Resampling.BICUBIC)
                    
                    # 3. Apply Rounded Corners (New Step)
                    if config.rounded_corners > 0:
                        img = _apply_rounding(img, config.rounded_corners)

                    # Paste with mask to show background on corners
                    grid_image.paste(img, (x, y), mask=img)
                    
                    if config.font_settings.frame_info_show:
                        d_tmp = ImageDraw.Draw(img)
                        _draw_frame_info(d_tmp, "Shot", draw_w, target_h, config.font_settings, info_font)
                    
                    layout_data.append({'image_path': item['path'], 'x': x, 'y': y, 'width': draw_w, 'height': target_h})
                    x += draw_w + int(config.padding * scale)
            except: pass
        
        y += target_h + config.padding

    try:
        grid_image.save(config.output_path, quality=config.quality)
        return True, layout_data
    except Exception as e:
        logger.error(f"Save failed: {e}")
        return False, []

def create_image_grid(**kwargs):
    """Adapter function."""
    font_conf = FontConfig(
        show_header=kwargs.get("show_header", True),
        frame_info_show=kwargs.get("frame_info_show", False),
        frame_info_type=kwargs.get("frame_info_timecode_or_frame", "timecode"),
        font_color=kwargs.get("frame_info_font_color", "#FFFFFF"),
        bg_color=kwargs.get("frame_info_bg_color", "#000000"),
        position=kwargs.get("frame_info_position", "bottom_left"),
        size=kwargs.get("frame_info_size", 12),
        margin=kwargs.get("frame_info_margin", 5),
    )

    grid_conf = GridConfig(
        output_path=kwargs.get("output_path", ""),
        columns=kwargs.get("columns", 5),
        padding=kwargs.get("padding", 5),
        bg_color_hex=kwargs.get("background_color_hex", "#1E1E1E"),
        grid_margin=kwargs.get("grid_margin", 0),
        rounded_corners=kwargs.get("rounded_corners", 0),
        rotation=kwargs.get("rotation", 0),
        quality=kwargs.get("quality", 95),
        target_thumb_width=kwargs.get("target_thumbnail_width"),
        layout_mode=kwargs.get("layout_mode", "grid"),
        target_row_height=kwargs.get("target_row_height", 150),
        output_width=kwargs.get("max_grid_width", 1920), # mapped from caller
        font_settings=font_conf
    )
    
    logger = kwargs.get("logger", logging.getLogger("image_grid"))
    image_source_data = kwargs.get("image_source_data", [])

    if grid_conf.layout_mode == "grid":
        return _create_fixed_column_grid(image_source_data, grid_conf, logger)
    elif grid_conf.layout_mode == "timeline":
        return _create_timeline_grid(image_source_data, grid_conf, logger)
    
    return False, []