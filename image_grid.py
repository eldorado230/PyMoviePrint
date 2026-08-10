from PIL import Image, ImageDraw, ImageColor, ImageFont, ImageChops, ImageOps
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
    header_title: str = ""
    # Grid Specific
    columns: int = 5
    rows: int = 5 # Added explicit row count for calculation
    target_thumb_width: Optional[int] = None
    
    # Timeline Specific
    layout_mode: str = "grid" # 'grid' or 'timeline'
    target_row_height: int = 150
    
    # NEW: Fixed Dimensions
    fit_to_output_params: bool = False
    output_width: int = 1920
    output_height: int = 1080
    
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

def _save_image_optimized(img: Image.Image, path: str, quality: int, logger: logging.Logger) -> bool:
    try:
        ext = os.path.splitext(path)[1].lower()
        save_kwargs = {"optimize": True} 

        if ext in [".jpg", ".jpeg"]:
            save_kwargs["quality"] = quality
            save_kwargs["subsampling"] = 0 if quality >= 90 else 2
        elif ext == ".png":
            save_kwargs["compress_level"] = 9
            
        img.save(path, **save_kwargs)
        return True
    except Exception as e:
        logger.error(f"Failed to save image to {path}: {e}")
        return False

def _coerce_image_item(item: Union[str, Dict[str, Any]]) -> Tuple[str, Dict[str, Any]]:
    if isinstance(item, dict):
        return item.get("image_path", ""), item
    return item, {"image_path": item}

def _format_timecode(seconds: Any) -> Optional[str]:
    if seconds is None:
        return None
    try:
        total_seconds = max(0.0, float(seconds))
    except (TypeError, ValueError):
        return None

    hours = int(total_seconds // 3600)
    minutes = int((total_seconds % 3600) // 60)
    secs = total_seconds % 60
    if hours:
        return f"{hours:02d}:{minutes:02d}:{secs:06.3f}"
    return f"{minutes:02d}:{secs:06.3f}"

def _frame_info_label(meta: Dict[str, Any], index: int, conf: FontConfig) -> str:
    if conf.frame_info_type == "frame":
        if not conf.show_frame_num:
            return ""
        frame_number = meta.get("frame_number")
        return f"#{frame_number}" if frame_number is not None else f"#{index + 1}"

    if not conf.show_timecode:
        return ""
    return _format_timecode(meta.get("timestamp_sec")) or f"#{index + 1}"

def _header_text(first_path: str, first_meta: Dict[str, Any], config: GridConfig) -> str:
    if config.font_settings.show_file_path and first_meta.get("video_path"):
        return first_meta["video_path"]
    if config.header_title:
        return config.header_title
    return first_meta.get("video_filename") or os.path.basename(first_path)

# --- Layout Engines ---

def _create_fixed_column_grid(image_paths: List[Union[str, Dict[str, Any]]], config: GridConfig, logger: logging.Logger):
    """Standard grid layout. Supports both dynamic size and fixed output size."""
    layout_data = []
    image_items = [_coerce_image_item(item) for item in image_paths]
    image_items = [(path, meta) for path, meta in image_items if path]
    if not image_items: return False, []

    num_images = len(image_items)
    header_height = 50 if config.font_settings.show_header else 0

    # --- Mode 1: Fixed Output Resolution (Wallpaper Mode) ---
    if config.fit_to_output_params:
        grid_w = config.output_width
        grid_h = config.output_height
        effective_rows = config.rows or max(1, math.ceil(num_images / config.columns))

        # Calculate available space for thumbnails
        avail_w = grid_w - (2 * config.grid_margin) - ((config.columns - 1) * config.padding)
        avail_h = grid_h - (2 * config.grid_margin) - header_height - ((effective_rows - 1) * config.padding)

        cell_w = max(1, avail_w // config.columns)
        cell_h = max(1, avail_h // effective_rows)

        # We process 'rows * columns' max images to ensure fit
        max_images = effective_rows * config.columns
        image_items = image_items[:max_images]

    # --- Mode 2: Dynamic Growth (Standard Mode) ---
    else:
        # Determine Cell Size from content
        cell_w, cell_h = 0, 0
        max_w, max_h = 0, 0

        # Sample first few images to guess aspect ratio
        for p, _meta in image_items[:5]:
            try:
                with Image.open(p) as img:
                    if config.rotation in [90, 270]: w, h = img.height, img.width
                    else: w, h = img.size
                    max_w = max(max_w, w)
                    max_h = max(max_h, h)
            except Exception as e:
                logger.warning(f"Could not inspect thumbnail '{p}' for sizing: {e}")
        
        cell_w = config.target_thumb_width if config.target_thumb_width else (max_w or 200)
        if max_w > 0: cell_h = int(cell_w * (max_h / max_w))
        else: cell_h = 150

        rows_calculated = math.ceil(num_images / config.columns)
        
        grid_w = (config.columns * cell_w) + ((config.columns - 1) * config.padding) + (2 * config.grid_margin)
        grid_h = (rows_calculated * cell_h) + ((rows_calculated - 1) * config.padding) + (2 * config.grid_margin) + header_height

    # --- Create Canvas ---
    try:
        bg_rgb = ImageColor.getrgb(config.bg_color_hex)
        grid_image = Image.new("RGB", (grid_w, grid_h), bg_rgb)
    except: return False, []

    draw = ImageDraw.Draw(grid_image)
    if config.font_settings.show_header:
        f = _load_font(config.font_settings.get_font_path(), 20)
        first_path, first_meta = image_items[0]
        draw.text((config.grid_margin, config.grid_margin), _header_text(first_path, first_meta, config), font=f, fill=config.font_settings.font_color)

    current_x = config.grid_margin
    current_y = config.grid_margin + header_height
    info_font = _load_font(config.font_settings.get_font_path(), config.font_settings.size)
    radius_scale_factor = cell_w / 480.0 if cell_w > 0 else 1.0

    for i, (path, meta) in enumerate(image_items):
        try:
            with Image.open(path) as img:
                # 1. Rotate
                img = _apply_rotation(img, config.rotation)
                img = img.convert("RGBA")
                
                # 2. Resize / Fit
                if config.fit_to_output_params:
                    # Smart crop to fill cell exactly
                    img = ImageOps.fit(img, (cell_w, cell_h), method=Image.Resampling.LANCZOS)
                else:
                    # Standard resize keeping aspect ratio
                    img.thumbnail((cell_w, cell_h), Image.Resampling.BICUBIC)
                
                # 3. Apply Rounded Corners
                if config.rounded_corners > 0:
                    scaled_radius = int(config.rounded_corners * radius_scale_factor)
                    scaled_radius = max(1, scaled_radius)
                    img = _apply_rounding(img, scaled_radius)
                
                # Center centering for standard mode (if thumbnail aspect ratio < cell aspect ratio)
                # For fixed mode, ImageOps.fit ensures full fill, so no centering needed usually.
                paste_x = current_x + (cell_w - img.width) // 2
                paste_y = current_y + (cell_h - img.height) // 2

                if config.font_settings.frame_info_show:
                    d_tmp = ImageDraw.Draw(img)
                    label = _frame_info_label(meta, i, config.font_settings)
                    if label:
                        _draw_frame_info(d_tmp, label, img.width, img.height, config.font_settings, info_font)

                grid_image.paste(img, (paste_x, paste_y), mask=img)
                layout_data.append({'image_path': path, 'x': paste_x, 'y': paste_y, 'width': img.width, 'height': img.height})

        except Exception as e: logger.error(f"Error thumb {path}: {e}")

        if (i + 1) % config.columns == 0:
            current_x = config.grid_margin
            current_y += cell_h + config.padding
        else:
            current_x += cell_w + config.padding

    if _save_image_optimized(grid_image, config.output_path, config.quality, logger):
        return True, layout_data
    else:
        return False, []

def _create_timeline_grid(source_data: List[Dict[str, Any]], config: GridConfig, logger: logging.Logger):
    """Timeline layout (Variable width rows)."""
    layout_data = []
    if not source_data: return False, []

    target_h = config.target_row_height
    max_w = max(1, config.output_width - (2 * config.grid_margin))

    rows = []
    current_row = []
    current_row_width = 0

    source_items = [_coerce_image_item(item) for item in source_data]
    width_ratios = []
    for _path, meta in source_items:
        try:
            width_ratios.append(max(0.01, float(meta.get("width_ratio", 1.0))))
        except (TypeError, ValueError):
            width_ratios.append(1.0)
    average_ratio = sum(width_ratios) / len(width_ratios) if width_ratios else 1.0

    items = []
    for index, (path, meta) in enumerate(source_items):
        if not path:
            continue
        try:
            with Image.open(path) as img:
                 native_w, native_h = img.size
                 aspect = native_w / native_h
                 try:
                     ratio = max(0.01, float(meta.get("width_ratio", 1.0)))
                 except (TypeError, ValueError):
                     ratio = 1.0
                 duration_factor = max(0.35, min(3.0, ratio / average_ratio))
                 base_w = max(1, min(max_w, int(target_h * aspect * duration_factor)))
                 items.append({'path': path, 'w': base_w, 'h': target_h, 'meta': meta, 'index': index})
        except Exception as e:
            logger.warning(f"Could not inspect timeline source '{path}': {e}")
            continue

    if not items:
        return False, []

    for item in items:
        if current_row and current_row_width + item['w'] + config.padding > max_w:
            rows.append(current_row)
            current_row = []
            current_row_width = 0
        current_row.append(item)
        current_row_width += item['w'] + config.padding
    if current_row: rows.append(current_row)

    header_height = 50 if config.font_settings.show_header else 0
    render_row_h = target_h
    if config.fit_to_output_params:
        available_h = (
            config.output_height
            - header_height
            - (2 * config.grid_margin)
            - ((len(rows) - 1) * config.padding)
        )
        render_row_h = max(1, available_h // len(rows))
        total_grid_h = config.output_height
    else:
        total_grid_h = (len(rows) * (target_h + config.padding)) + header_height + (2 * config.grid_margin)

    try:
        bg_rgb = ImageColor.getrgb(config.bg_color_hex)
        grid_image = Image.new("RGB", (config.output_width, total_grid_h), bg_rgb)
    except: return False, []

    draw = ImageDraw.Draw(grid_image)
    if config.font_settings.show_header and source_data:
        f = _load_font(config.font_settings.get_font_path(), 20)
        first_path, first_meta = source_items[0]
        draw.text((config.grid_margin, config.grid_margin), _header_text(first_path, first_meta, config), font=f, fill=config.font_settings.font_color)

    y = config.grid_margin + header_height
    info_font = _load_font(config.font_settings.get_font_path(), config.font_settings.size)

    for row in rows:
        x = config.grid_margin
        height_scale = render_row_h / target_h
        row_widths = [max(1, int(i['w'] * height_scale)) for i in row]
        row_content_w = sum(row_widths) + ((len(row)-1) * config.padding)
        available_w = max_w

        scale = 1.0
        if row_content_w > 0 and (len(rows) == 1 or row != rows[-1] or row_content_w > available_w):
             scale = available_w / row_content_w

        for item, item_width in zip(row, row_widths):
            try:
                draw_w = max(1, int(item_width * scale))

                with Image.open(item['path']) as img:
                    img = _apply_rotation(img, config.rotation)
                    img = img.convert("RGBA")
                    img = img.resize((draw_w, render_row_h), Image.Resampling.BICUBIC)

                    if config.rounded_corners > 0:
                        radius_scale_factor = render_row_h / 150.0
                        scaled_radius = int(config.rounded_corners * radius_scale_factor)
                        scaled_radius = max(1, scaled_radius)
                        img = _apply_rounding(img, scaled_radius)

                    if config.font_settings.frame_info_show:
                        d_tmp = ImageDraw.Draw(img)
                        label = _frame_info_label(item['meta'], item['index'], config.font_settings)
                        if label:
                            _draw_frame_info(d_tmp, label, draw_w, render_row_h, config.font_settings, info_font)

                    grid_image.paste(img, (x, y), mask=img)
                    
                    layout_data.append({'image_path': item['path'], 'x': x, 'y': y, 'width': draw_w, 'height': render_row_h})
                    x += draw_w + int(config.padding * scale)
            except Exception as e:
                logger.warning(f"Failed to render timeline thumbnail '{item.get('path')}': {e}")
        y += render_row_h + config.padding

    if _save_image_optimized(grid_image, config.output_path, config.quality, logger):
        return True, layout_data
    else:
        return False, []

def create_image_grid(**kwargs):
    """Adapter function."""
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

    grid_conf = GridConfig(
        output_path=kwargs.get("output_path", ""),
        header_title=kwargs.get("header_title", ""),
        columns=kwargs.get("columns", 5),
        rows=kwargs.get("rows", 5), # Passed explicitly
        padding=kwargs.get("padding", 5),
        bg_color_hex=kwargs.get("background_color_hex", "#1E1E1E"),
        grid_margin=kwargs.get("grid_margin", 0),
        rounded_corners=kwargs.get("rounded_corners", 0),
        rotation=kwargs.get("rotation", 0),
        quality=kwargs.get("quality", 95),
        target_thumb_width=kwargs.get("target_thumbnail_width"),
        layout_mode=kwargs.get("layout_mode", "grid"),
        target_row_height=kwargs.get("target_row_height", 150),
        # New Settings
        output_width=kwargs.get("output_width", 1920), 
        output_height=kwargs.get("output_height", 1080),
        fit_to_output_params=kwargs.get("fit_to_output_params", False),
        font_settings=font_conf
    )
    
    logger = kwargs.get("logger", logging.getLogger("image_grid"))
    image_source_data = kwargs.get("image_source_data", [])

    if grid_conf.layout_mode == "grid":
        return _create_fixed_column_grid(image_source_data, grid_conf, logger)
    elif grid_conf.layout_mode == "timeline":
        return _create_timeline_grid(image_source_data, grid_conf, logger)
    
    return False, []
