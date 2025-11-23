from PIL import Image, ImageDraw, ImageColor, ImageFont
import logging
import os
import math
import shutil

def save_thumbnails(thumbnail_paths, output_dir, logger):
    """
    Saves a list of thumbnail images to a specified directory.
    """
    if not thumbnail_paths:
        logger.warning("No thumbnail paths provided to save.")
        return False, []

    if not os.path.exists(output_dir):
        try:
            os.makedirs(output_dir)
            logger.info(f"Created directory for saving thumbnails: {output_dir}")
        except OSError as e:
            logger.error(f"Error creating thumbnail output directory {output_dir}: {e}")
            return False, []

    saved_thumbnails = []
    for thumb_path in thumbnail_paths:
        try:
            if os.path.exists(thumb_path):
                filename = os.path.basename(thumb_path)
                dest_path = os.path.join(output_dir, filename)
                shutil.copy(thumb_path, dest_path)
                saved_thumbnails.append(dest_path)
            else:
                logger.warning(f"Thumbnail not found, cannot save: {thumb_path}")
        except Exception as e:
            logger.error(f"Error saving thumbnail {thumb_path} to {output_dir}: {e}")

    if saved_thumbnails:
        logger.info(f"Successfully saved {len(saved_thumbnails)} thumbnails to {output_dir}")
        return True, saved_thumbnails
    else:
        logger.error("Failed to save any thumbnails.")
        return False, []

def _apply_rotation(img, rotation):
    """Helper to rotate PIL image if needed."""
    if rotation == 90: return img.rotate(-90, expand=True) # PIL rotates Counter-Clockwise
    elif rotation == 180: return img.rotate(180)
    elif rotation == 270: return img.rotate(-270, expand=True)
    return img

def _create_fixed_column_grid(image_paths, output_path, columns, padding, background_color_rgb, logger, target_thumbnail_width=None, output_width=None, output_height=None, target_thumbnail_height=None, grid_margin=0, rounded_corners=0, frame_info_show=True, show_header=True, show_file_path=True, show_timecode=True, show_frame_num=True, frame_info_timecode_or_frame="timecode", frame_info_font_color="#FFFFFF", frame_info_bg_color="#000000", frame_info_position="bottom_left", frame_info_size=10, frame_info_margin=5, quality=95, rotation=0, **kwargs):
    thumbnail_layout_data = []
    if not image_paths:
        logger.error("Error (_create_fixed_column_grid): No image paths provided.")
        return False, thumbnail_layout_data

    # Helper to peek at an image size without loading pixel data
    def get_image_size(path):
        with Image.open(path) as img:
            if rotation in [90, 270]: return img.height, img.width # Swap dims
            return img.size

    # --- 1. Calculate Dimensions (Lazy) ---
    cell_w, cell_h = 0, 0
    
    if target_thumbnail_width and isinstance(target_thumbnail_width, int) and target_thumbnail_width > 0:
        cell_w = target_thumbnail_width
        max_scaled_height = 0
        for path in image_paths:
            try:
                w, h = get_image_size(path)
                if w > 0:
                    aspect_ratio = h / w
                    scaled_height = int(target_thumbnail_width * aspect_ratio)
                    max_scaled_height = max(max_scaled_height, scaled_height)
            except Exception: pass
        cell_h = max_scaled_height if max_scaled_height > 0 else 1

    elif target_thumbnail_height and isinstance(target_thumbnail_height, int) and target_thumbnail_height > 0:
        cell_h = target_thumbnail_height
        max_scaled_width = 0
        for path in image_paths:
            try:
                w, h = get_image_size(path)
                if h > 0:
                    aspect_ratio = w / h
                    scaled_width = int(target_thumbnail_height * aspect_ratio)
                    max_scaled_width = max(max_scaled_width, scaled_width)
            except Exception: pass
        cell_w = max_scaled_width if max_scaled_width > 0 else 1
    else:
        # Auto-detect max dimensions
        max_thumb_width = 0
        max_thumb_height = 0
        for path in image_paths:
            try:
                w, h = get_image_size(path)
                if w > max_thumb_width: max_thumb_width = w
                if h > max_thumb_height: max_thumb_height = h
            except Exception: pass
        cell_w = max_thumb_width
        cell_h = max_thumb_height

    if cell_w == 0 or cell_h == 0:
        # Fallback if detection failed
        cell_w, cell_h = 100, 100

    num_images = len(image_paths)
    rows = math.ceil(num_images / columns) if columns > 0 else 0
    if rows == 0 and num_images > 0 : rows = 1

    grid_width = (columns * cell_w) + ((columns - 1) * padding) + (2 * grid_margin)
    grid_height = (rows * cell_h) + ((rows - 1) * padding) + (2 * grid_margin)

    header_height = 0
    if show_header:
        header_height = 50
        grid_height += header_height

    # --- 2. Create Canvas ---
    grid_image = Image.new("RGBA", (grid_width, grid_height), (0,0,0,0))
    draw = ImageDraw.Draw(grid_image)

    # --- 3. Draw Header ---
    if show_header:
        try: font = ImageFont.truetype("arial.ttf", 20)
        except IOError: font = ImageFont.load_default()
        header_text = ""
        if show_file_path: header_text += f"{image_paths[0]}"
        if show_timecode: header_text += f" TC: {0}"
        if show_frame_num: header_text += f" F: {0}"
        draw.text((grid_margin, grid_margin), header_text, font=font, fill=frame_info_font_color)

    current_x = grid_margin
    current_y = grid_margin + header_height
    
    # --- 4. Process Thumbnails (LAZY LOADING) ---
    for i, path in enumerate(image_paths):
        try:
            # Open, Process, Paste, Close - Memory usage remains low/constant
            with Image.open(path) as img_obj:
                img_obj = _apply_rotation(img_obj, rotation)
                img_copy = img_obj.convert("RGBA")
                img_copy.thumbnail((cell_w, cell_h), Image.Resampling.BICUBIC)

                final_w, final_h = img_copy.width, img_copy.height
                x_offset = (cell_w - final_w) // 2
                y_offset = (cell_h - final_h) // 2

                paste_x = current_x + x_offset
                paste_y = current_y + y_offset

                # Draw Info Text
                if frame_info_show:
                    draw_thumb = ImageDraw.Draw(img_copy)
                    try: font = ImageFont.truetype("arial.ttf", frame_info_size)
                    except IOError: font = ImageFont.load_default()

                    text = f"TC: {i}" if frame_info_timecode_or_frame == "timecode" else f"F: {i}"
                    text_bbox = draw_thumb.textbbox((0, 0), text, font=font)
                    text_w = text_bbox[2] - text_bbox[0]
                    text_h = text_bbox[3] - text_bbox[1]

                    if frame_info_position == "bottom_left":
                        text_x, text_y = frame_info_margin, final_h - text_h - frame_info_margin
                    elif frame_info_position == "bottom_right":
                        text_x, text_y = final_w - text_w - frame_info_margin, final_h - text_h - frame_info_margin
                    elif frame_info_position == "top_left":
                        text_x, text_y = frame_info_margin, frame_info_margin
                    else: 
                        text_x, text_y = final_w - text_w - frame_info_margin, frame_info_margin

                    bg_rect = (text_x - 2, text_y - 2, text_x + text_w + 2, text_y + text_h + 2)
                    draw_thumb.rectangle(bg_rect, fill=frame_info_bg_color)
                    draw_thumb.text((text_x, text_y), text, font=font, fill=frame_info_font_color)

                # Paste with or without corners
                if rounded_corners > 0:
                    mask = Image.new('L', (final_w, final_h), 0)
                    draw_mask = ImageDraw.Draw(mask)
                    draw_mask.rounded_rectangle((0, 0, final_w, final_h), radius=rounded_corners, fill=255)
                    grid_image.paste(img_copy, (paste_x, paste_y), mask=mask)
                else:
                    grid_image.paste(img_copy, (paste_x, paste_y))
                    
                thumbnail_layout_data.append({
                    'image_path': path,
                    'x': paste_x, 'y': paste_y,
                    'width': final_w, 'height': final_h
                })
        except Exception as e:
            logger.error(f"Error processing thumbnail {path}: {e}")

        if (i + 1) % columns == 0:
            current_x = grid_margin
            current_y += cell_h + padding
        else:
            current_x += cell_w + padding

    # --- 5. Save Output ---
    try:
        if output_width and output_height:
            logger.info(f"Resizing final grid to: {output_width}x{output_height}")
            grid_image = grid_image.resize((output_width, output_height), Image.Resampling.BICUBIC)

        save_kwargs = {}
        ext = os.path.splitext(output_path)[1].lower()
        
        if ext in ['.jpg', '.jpeg']:
            solid_bg = Image.new("RGB", grid_image.size, background_color_rgb)
            solid_bg.paste(grid_image, (0, 0), grid_image)
            grid_image = solid_bg
            
            save_kwargs['quality'] = quality
            save_kwargs['optimize'] = True
        
        grid_image.save(output_path, **save_kwargs)
        logger.info(f"Fixed-column grid saved to {output_path}")
        return True, thumbnail_layout_data
    except Exception as e:
        logger.error(f"Error saving fixed-column grid: {e}")
        return False, thumbnail_layout_data
    finally:
        grid_image.close()

def _create_timeline_view_grid(source_data, output_path, max_grid_width, target_row_height, padding, background_color_rgb, logger, quality=95, rotation=0, **kwargs):
    # LAZY LOADING IMPLEMENTATION FOR TIMELINE
    thumbnail_layout_data = []
    if not source_data: return False, []
    
    # Pre-calculate layout without loading full images
    # We need dimensions to calc layout. We must open them briefly.
    scaled_items = []
    
    for item in source_data:
        path = item['image_path']
        ratio = item.get('width_ratio', 1.0)
        try:
            with Image.open(path) as img:
                img = _apply_rotation(img, rotation)
                ar = img.width / img.height
                new_h = target_row_height
                new_w = int(new_h * ar)
                scaled_items.append({'path': path, 'w': new_w, 'h': new_h, 'ratio': ratio})
        except: pass

    # Layout logic
    rows_layout = []
    curr_y = padding
    row_buf = []
    curr_w = 0
    curr_r = 0.0

    for item in scaled_items:
        potential_w = curr_w + item['w']
        potential_pad = (len(row_buf) + 2) * padding
        
        if row_buf and (potential_w + potential_pad > max_grid_width):
            rows_layout.append({'items': list(row_buf), 'sum_r': curr_r, 'y': curr_y})
            curr_y += target_row_height + padding
            row_buf = []
            curr_w = 0; curr_r = 0.0
        
        row_buf.append(item)
        curr_w += item['w']
        curr_r += item.get('ratio', 1.0)
    
    if row_buf: rows_layout.append({'items': list(row_buf), 'sum_r': curr_r, 'y': curr_y})
    
    total_h = curr_y + target_row_height + padding
    grid_image = Image.new("RGB", (max_grid_width, total_h), background_color_rgb)

    # Draw Loop (Lazy)
    for row in rows_layout:
        curr_x = padding
        avail_w = max_grid_width - (len(row['items']) + 1) * padding
        if avail_w <= 0 or row['sum_r'] == 0: continue
        
        for item in row['items']:
            final_w = int((item['ratio'] / row['sum_r']) * avail_w)
            if final_w <= 0: continue
            
            try:
                with Image.open(item['path']) as img:
                    img = _apply_rotation(img, rotation)
                    img_s = img.resize((final_w, target_row_height), Image.Resampling.BICUBIC)
                    grid_image.paste(img_s, (curr_x, row['y']))
                    thumbnail_layout_data.append({'image_path': item['path'], 'x': curr_x, 'y': row['y'], 'width': final_w, 'height': target_row_height})
            except: pass
            curr_x += final_w + padding

    grid_image.save(output_path, quality=quality)
    return True, thumbnail_layout_data

def create_image_grid(image_source_data, output_path, padding, logger, background_color_hex="#FFFFFF", layout_mode="grid", columns=None, rows=None, target_row_height=None, max_grid_width=None, target_thumbnail_width=None, output_width=None, output_height=None, target_thumbnail_height=None, grid_margin=0, rounded_corners=0, frame_info_show=True, show_header=True, show_file_path=True, show_timecode=True, show_frame_num=True, frame_info_timecode_or_frame="timecode", frame_info_font_color="#FFFFFF", frame_info_bg_color="#000000", frame_info_position="bottom_left", frame_info_size=10, frame_info_margin=5, quality=95, rotation=0):
    
    try: bg_rgb = ImageColor.getrgb(background_color_hex)
    except: bg_rgb = (255,255,255)

    if layout_mode == "grid":
        # Pass Paths directly
        paths = [p for p in image_source_data if isinstance(p, str) and os.path.exists(p)]
        return _create_fixed_column_grid(paths, output_path, columns, padding, bg_rgb, logger, target_thumbnail_width, output_width, output_height, target_thumbnail_height, grid_margin, rounded_corners, frame_info_show, show_header, show_file_path, show_timecode, show_frame_num, frame_info_timecode_or_frame, frame_info_font_color, frame_info_bg_color, frame_info_position, frame_info_size, frame_info_margin, quality, rotation)
        
    elif layout_mode == "timeline":
        # Pass Dicts directly
        return _create_timeline_view_grid(image_source_data, output_path, max_grid_width, target_row_height, padding, bg_rgb, logger, quality, rotation)
    
    return False, []