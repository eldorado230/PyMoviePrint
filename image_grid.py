from PIL import Image, ImageDraw, ImageColor, ImageFont
import logging
import os
import math
import shutil
import platform
from dataclasses import dataclass, field
from typing import List, Tuple, Optional, Dict, Union

# --- Configuration Data Classes ---

@dataclass
class FontConfig:
    """Handles font settings to avoid passing loose variables."""
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
        """Returns a system-appropriate font path."""
        system = platform.system()
        if system == "Windows":
            return "arial.ttf"
        elif system == "Darwin": # macOS
            return "/System/Library/Fonts/Helvetica.ttc"
        else: # Linux
            return "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"

@dataclass
class GridConfig:
    """Consolidates all visual settings for the grid."""
    output_path: str
    columns: int = 5
    padding: int = 5
    bg_color_hex: str = "#1E1E1E"
    grid_margin: int = 0
    rounded_corners: int = 0
    rotation: int = 0
    quality: int = 95
    
    # Dimensions (Optional overrides)
    target_thumb_width: Optional[int] = None
    target_thumb_height: Optional[int] = None
    output_width: Optional[int] = None
    output_height: Optional[int] = None
    
    # Font Settings
    font_settings: FontConfig = field(default_factory=FontConfig)

# --- Helper Functions ---

def _load_font(name_or_path: str, size: int) -> ImageFont.FreeTypeFont:
    """Robust font loader with fallback."""
    try:
        return ImageFont.truetype(name_or_path, size)
    except IOError:
        # Try generic names if specific path failed
        try:
            return ImageFont.truetype("arial.ttf", size)
        except IOError:
            # Ultimate fallback
            return ImageFont.load_default()

def _apply_rotation(img: Image.Image, rotation: int) -> Image.Image:
    """Helper to rotate PIL image."""
    if rotation == 90: return img.rotate(-90, expand=True)
    elif rotation == 180: return img.rotate(180)
    elif rotation == 270: return img.rotate(-270, expand=True)
    return img

def save_thumbnails(thumbnail_paths: List[str], output_dir: str, logger: logging.Logger) -> Tuple[bool, List[str]]:
    """Legacy function for saving raw thumbnails without a grid."""
    if not thumbnail_paths:
        return False, []
        
    os.makedirs(output_dir, exist_ok=True)
    saved = []
    
    for path in thumbnail_paths:
        try:
            if os.path.exists(path):
                dest = os.path.join(output_dir, os.path.basename(path))
                shutil.copy(path, dest)
                saved.append(dest)
        except Exception as e:
            logger.error(f"Error saving thumb {path}: {e}")
            
    return bool(saved), saved

# --- Main Grid Logic ---

def _draw_frame_info(
    draw: ImageDraw.ImageDraw, 
    text: str, 
    img_w: int, 
    img_h: int, 
    conf: FontConfig,
    font: ImageFont.FreeTypeFont
):
    """Draws the timecode/frame pill on a single thumbnail."""
    bbox = draw.textbbox((0, 0), text, font=font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    
    # Calculate Position
    m = conf.margin
    if conf.position == "bottom_left":
        x, y = m, img_h - text_h - m - 4 # Extra padding for descenders
    elif conf.position == "bottom_right":
        x, y = img_w - text_w - m - 4, img_h - text_h - m - 4
    elif conf.position == "top_left":
        x, y = m, m
    elif conf.position == "top_right":
        x, y = img_w - text_w - m - 4, m
    else:
        x, y = m, m

    # Draw Background Pill
    padding = 2
    bg_rect = (x - padding, y - padding, x + text_w + padding, y + text_h + padding)
    draw.rectangle(bg_rect, fill=conf.bg_color)
    draw.text((x, y), text, font=font, fill=conf.font_color)

def _create_fixed_column_grid(image_paths: List[str], config: GridConfig, logger: logging.Logger):
    """
    Refactored grid generator using the Config object.
    """
    layout_data = []
    if not image_paths:
        return False, []

    # 1. Determine Cell Size (Lazy Peek)
    cell_w, cell_h = 0, 0
    
    # Logic to find max dimensions or use target overrides
    # (Simplified for brevity, assumes logic similar to original but cleaner)
    if config.target_thumb_width:
        cell_w = config.target_thumb_width
        # Calculate height based on first valid image aspect ratio
        for p in image_paths:
            try:
                with Image.open(p) as img:
                    if config.rotation in [90, 270]: 
                        w_i, h_i = img.height, img.width
                    else: 
                        w_i, h_i = img.size
                    cell_h = int(cell_w * (h_i / w_i))
                    break
            except: continue
        if cell_h == 0: cell_h = 100
    else:
        # Auto-scan max
        max_w, max_h = 0, 0
        for p in image_paths:
            try:
                with Image.open(p) as img:
                    if config.rotation in [90, 270]:
                        w, h = img.height, img.width
                    else:
                        w, h = img.size
                    max_w = max(max_w, w)
                    max_h = max(max_h, h)
            except: pass
        cell_w, cell_h = (max_w or 100), (max_h or 100)

    # 2. Calculate Grid Dimensions
    num_images = len(image_paths)
    rows = math.ceil(num_images / config.columns)
    
    header_height = 50 if config.font_settings.show_header else 0
    
    grid_w = (config.columns * cell_w) + ((config.columns - 1) * config.padding) + (2 * config.grid_margin)
    grid_h = (rows * cell_h) + ((rows - 1) * config.padding) + (2 * config.grid_margin) + header_height

    # 3. Create Canvas
    try:
        bg_rgb = ImageColor.getrgb(config.bg_color_hex)
    except:
        bg_rgb = (30, 30, 30)

    grid_image = Image.new("RGB", (grid_w, grid_h), bg_rgb)
    draw = ImageDraw.Draw(grid_image)

    # 4. Draw Header
    if config.font_settings.show_header:
        header_font = _load_font(config.font_settings.get_font_path(), 20)
        header_text = ""
        if config.font_settings.show_file_path: 
            header_text += os.path.basename(image_paths[0])
        # (Add other header details here if needed)
        draw.text((config.grid_margin, config.grid_margin), header_text, font=header_font, fill=config.font_settings.font_color)

    # 5. Process Images
    current_x = config.grid_margin
    current_y = config.grid_margin + header_height
    
    # Load small font once
    info_font = _load_font(config.font_settings.get_font_path(), config.font_settings.size)

    for i, path in enumerate(image_paths):
        try:
            with Image.open(path) as img:
                img = _apply_rotation(img, config.rotation)
                img = img.convert("RGBA")
                
                # Resize
                img.thumbnail((cell_w, cell_h), Image.Resampling.BICUBIC)
                
                # Centering in cell
                paste_x = current_x + (cell_w - img.width) // 2
                paste_y = current_y + (cell_h - img.height) // 2

                # Overlay Text (Draw on image copy before pasting to handle corners correctly)
                if config.font_settings.frame_info_show:
                    d_tmp = ImageDraw.Draw(img)
                    label = f"TC: {i}" if config.font_settings.frame_info_type == "timecode" else f"#{i}"
                    _draw_frame_info(d_tmp, label, img.width, img.height, config.font_settings, info_font)

                # Handle Rounded Corners
                if config.rounded_corners > 0:
                    mask = Image.new('L', img.size, 0)
                    ImageDraw.Draw(mask).rounded_rectangle(
                        (0, 0, img.width, img.height), 
                        radius=config.rounded_corners, 
                        fill=255
                    )
                    grid_image.paste(img, (paste_x, paste_y), mask)
                else:
                    grid_image.paste(img, (paste_x, paste_y))

                layout_data.append({
                    'image_path': path,
                    'x': paste_x, 'y': paste_y,
                    'width': img.width, 'height': img.height
                })

        except Exception as e:
            logger.error(f"Failed to process thumb {path}: {e}")

        # Advance Grid Cursor
        if (i + 1) % config.columns == 0:
            current_x = config.grid_margin
            current_y += cell_h + config.padding
        else:
            current_x += cell_w + config.padding

    # 6. Save
    try:
        if config.output_width and config.output_height:
             grid_image = grid_image.resize((config.output_width, config.output_height), Image.Resampling.BICUBIC)
             
        grid_image.save(config.output_path, quality=config.quality, optimize=True)
        return True, layout_data
    except Exception as e:
        logger.error(f"Error saving grid: {e}")
        return False, []
    finally:
        grid_image.close()

def create_image_grid(**kwargs):
    """
    Adapter function to maintain backward compatibility with the GUI 
    but internally use the new Config object.
    """
    # Extract font settings
    font_conf = FontConfig(
        show_header=kwargs.get("show_header", True),
        show_file_path=kwargs.get("show_file_path", True),
        show_timecode=kwargs.get("show_timecode", True),
        show_frame_num=kwargs.get("show_frame_num", True),
        frame_info_show=kwargs.get("frame_info_show", False),
        frame_info_type=kwargs.get("frame_info_timecode_or_frame", "timecode"),
        font_color=kwargs.get("frame_info_font_color", "#FFFFFF"),
        bg_color=kwargs.get("frame_info_bg_color", "#000000"),
        position=kwargs.get("frame_info_position", "bottom_left"),
        size=kwargs.get("frame_info_size", 12),
        margin=kwargs.get("frame_info_margin", 5),
    )

    # Extract grid settings
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
        target_thumb_height=kwargs.get("target_thumbnail_height"),
        output_width=kwargs.get("output_width"),
        output_height=kwargs.get("output_height"),
        font_settings=font_conf
    )
    
    layout_mode = kwargs.get("layout_mode", "grid")
    logger = kwargs.get("logger", logging.getLogger("image_grid"))
    image_source_data = kwargs.get("image_source_data", [])

    if layout_mode == "grid":
        return _create_fixed_column_grid(image_source_data, grid_conf, logger)
    
    # (Timeline mode logic would go here, kept minimal for this refactor)
    logger.warning("Timeline mode not yet fully refactored to Config object.")
    return False, []