from PIL import Image, ImageDraw, ImageColor, ImageFont
import logging
import os
import math
import shutil


def save_thumbnails(thumbnail_paths, output_dir, logger):
    """
    Saves a list of thumbnail images to a specified directory.

    :param thumbnail_paths: A list of paths to the thumbnail image files.
    :param output_dir: The directory where the thumbnails will be saved.
    :param logger: A logger instance for logging messages.
    :return: A tuple (bool, list) indicating success and a list of saved thumbnail paths.
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


def _create_fixed_column_grid(image_objects_with_paths, output_path, columns, padding, background_color_rgb, logger, target_thumbnail_width=None, output_width=None, output_height=None, target_thumbnail_height=None, grid_margin=0, rounded_corners=0, frame_info_show=True, show_header=True, show_file_path=True, show_timecode=True, show_frame_num=True, frame_info_timecode_or_frame="timecode", frame_info_font_color="#FFFFFF", frame_info_bg_color="#000000", frame_info_position="bottom_left", frame_info_size=10, frame_info_margin=5, **kwargs):
    thumbnail_layout_data = []
    if not image_objects_with_paths:
        logger.error("Error (_create_fixed_column_grid): No image objects provided.")
        return False, thumbnail_layout_data

    image_objects = [item[0] for item in image_objects_with_paths]
    original_paths = [item[1] for item in image_objects_with_paths]

    cell_w, cell_h = 0, 0
    if target_thumbnail_width and isinstance(target_thumbnail_width, int) and target_thumbnail_width > 0:
        cell_w = target_thumbnail_width
        max_scaled_height = 0
        if image_objects:
            for img in image_objects:
                if img.width > 0: # Avoid division by zero
                    aspect_ratio = img.height / img.width
                    scaled_height = int(target_thumbnail_width * aspect_ratio)
                    max_scaled_height = max(max_scaled_height, scaled_height)
            cell_h = max_scaled_height
            if cell_h == 0: # Fallback if all images had zero width or other issues
                logger.warning("Max scaled height was 0. Defaulting cell_h to 1 for non-empty image list.")
                cell_h = 1 # Ensure cell_h is at least 1 if there are images
        else: # No images
            cell_h = 1
    elif target_thumbnail_height and isinstance(target_thumbnail_height, int) and target_thumbnail_height > 0:
        cell_h = target_thumbnail_height
        max_scaled_width = 0
        if image_objects:
            for img in image_objects:
                if img.height > 0: # Avoid division by zero
                    aspect_ratio = img.width / img.height
                    scaled_width = int(target_thumbnail_height * aspect_ratio)
                    max_scaled_width = max(max_scaled_width, scaled_width)
            cell_w = max_scaled_width
            if cell_w == 0: # Fallback if all images had zero height or other issues
                logger.warning("Max scaled width was 0. Defaulting cell_w to 1 for non-empty image list.")
                cell_w = 1
        else: # No images
            cell_w = 1
    else:
        max_thumb_width = 0
        max_thumb_height = 0
        for img in image_objects:
            if img.width > max_thumb_width: max_thumb_width = img.width
            if img.height > max_thumb_height: max_thumb_height = img.height
        cell_w = max_thumb_width
        cell_h = max_thumb_height

    if cell_w == 0 or cell_h == 0:
        if image_objects: # If there are images, but cell dimensions are zero (e.g. all images zero width/height)
            logger.error("Error (_create_fixed_column_grid): Could not determine valid cell dimensions for images.")
            return False, thumbnail_layout_data
        # If no images, cell_w/cell_h can be 0, grid will be padding only.
        # This case should ideally be caught by "No image objects provided" or lead to a minimal padding-only grid.
        # To prevent division by zero or tiny grids if only padding, let's ensure they are at least 1 if we proceed.
        # However, the main loop over images won't run if image_objects is empty.
        # Let's rely on the initial check for empty image_objects_with_paths.
        # If that check passes, image_objects is not empty. So if cell_w/h is 0 here, it's an error.
        logger.error(f"Error (_create_fixed_column_grid): Cell dimensions are zero (w:{cell_w}, h:{cell_h}). This shouldn't happen if images are present.")
        return False, thumbnail_layout_data


    num_images = len(image_objects)
    rows = math.ceil(num_images / columns) if columns > 0 else 0
    if rows == 0 and num_images > 0 : rows = 1 # Ensure at least one row if there are images but columns is somehow 0

    grid_width = (columns * cell_w) + ((columns - 1) * padding) + (2 * grid_margin)
    grid_height = (rows * cell_h) + ((rows - 1) * padding) + (2 * grid_margin)

    # Ensure grid dimensions are at least padding if no images (or minimal size)
    if not image_objects:
        grid_width = padding
        grid_height = padding
        # If no images, create an empty image of padding size.
        # The function should ideally return earlier if image_objects is empty.
        # This is a safeguard.
    elif grid_width <= 0 or grid_height <= 0 : # check if calculated grid size is valid
        logger.error(f"Error (_create_fixed_column_grid): Invalid grid dimensions calculated ({grid_width}x{grid_height}).")
        return False, thumbnail_layout_data


    header_height = 0
    if show_header:
        header_height = 50 # Adjust as needed
        grid_height += header_height

    grid_image = Image.new("RGB", (grid_width, grid_height), background_color_rgb)
    draw = ImageDraw.Draw(grid_image)

    if show_header:
        try:
            font = ImageFont.truetype("arial.ttf", 20)
        except IOError:
            font = ImageFont.load_default()
        header_text = ""
        if show_file_path:
            header_text += f"{original_paths[0]}"
        if show_timecode:
            header_text += f" TC: {0}"
        if show_frame_num:
            header_text += f" F: {0}"
        draw.text((grid_margin, grid_margin), header_text, font=font, fill=frame_info_font_color)

    logger.info(f"Creating fixed-column grid: {columns}c, {rows}r. Cell: {cell_w}x{cell_h} (target_width: {target_thumbnail_width if target_thumbnail_width else 'auto'}). Output: {grid_width}x{grid_height}px.")

    current_x = grid_margin
    current_y = grid_margin + header_height
    for i, img_obj in enumerate(image_objects):
        img_copy = img_obj.copy()
        # Resize an image to fit within the cell_w x cell_h box, preserving aspect ratio
        img_copy.thumbnail((cell_w, cell_h), Image.Resampling.BICUBIC)

        final_w, final_h = img_copy.width, img_copy.height
        # Calculate offsets to center the thumbnail in the cell
        x_offset = (cell_w - final_w) // 2
        y_offset = (cell_h - final_h) // 2

        paste_x = current_x + x_offset
        paste_y = current_y + y_offset
        if frame_info_show:
            draw = ImageDraw.Draw(img_copy)
            try:
                font = ImageFont.truetype("arial.ttf", frame_info_size)
            except IOError:
                font = ImageFont.load_default()

            if frame_info_timecode_or_frame == "timecode":
                text = f"TC: {i}"
            else:
                text = f"F: {i}"

            text_bbox = draw.textbbox((0, 0), text, font=font)
            text_width = text_bbox[2] - text_bbox[0]
            text_height = text_bbox[3] - text_bbox[1]

            if frame_info_position == "bottom_left":
                text_x = frame_info_margin
                text_y = final_h - text_height - frame_info_margin
            elif frame_info_position == "bottom_right":
                text_x = final_w - text_width - frame_info_margin
                text_y = final_h - text_height - frame_info_margin
            elif frame_info_position == "top_left":
                text_x = frame_info_margin
                text_y = frame_info_margin
            else: # top_right
                text_x = final_w - text_width - frame_info_margin
                text_y = frame_info_margin

            bg_rect = (text_x - 2, text_y - 2, text_x + text_width + 2, text_y + text_height + 2)
            draw.rectangle(bg_rect, fill=frame_info_bg_color)
            draw.text((text_x, text_y), text, font=font, fill=frame_info_font_color)

        if rounded_corners > 0:
            mask = Image.new('L', (final_w, final_h), 0)
            draw = ImageDraw.Draw(mask)
            draw.rounded_rectangle((0, 0, final_w, final_h), radius=rounded_corners, fill=255)
            grid_image.paste(img_copy, (paste_x, paste_y), mask)
        else:
            grid_image.paste(img_copy, (paste_x, paste_y))

        thumbnail_layout_data.append({
            'image_path': original_paths[i],
            'x': paste_x, 'y': paste_y,
            'width': final_w, 'height': final_h
        })
        img_copy.close()

        if (i + 1) % columns == 0:
            current_x = grid_margin
            current_y += cell_h + padding
        else:
            current_x += cell_w + padding

    try:
        if output_width and output_height:
            logger.info(f"Resizing final grid to user-defined dimensions: {output_width}x{output_height}")
            grid_image = grid_image.resize((output_width, output_height), Image.Resampling.BICUBIC)

        grid_image.save(output_path)
        logger.info(f"Fixed-column grid saved to {output_path}")
        return True, thumbnail_layout_data
    except Exception as e:
        logger.error(f"Error saving fixed-column grid: {e}")
        return False, thumbnail_layout_data
    finally:
        grid_image.close()

def _create_timeline_view_grid(image_objects_with_paths_ratios, output_path,
                               max_grid_width, target_row_height, padding, background_color_rgb, logger, **kwargs):
    thumbnail_layout_data = []
    if not image_objects_with_paths_ratios:
        logger.error("Error (_create_timeline_view_grid): Invalid inputs.")
        return False, thumbnail_layout_data

    pil_images = [item[0] for item in image_objects_with_paths_ratios]
    original_paths = [item[1] for item in image_objects_with_paths_ratios]
    width_ratios = [item[2] for item in image_objects_with_paths_ratios]

    if target_row_height <= 0 or max_grid_width <= 0:
        logger.error("Error (_create_timeline_view_grid): target_row_height and max_grid_width must be positive.")
        return False, thumbnail_layout_data

    logger.info(f"Creating timeline view: MaxW={max_grid_width}, RowH={target_row_height}, Pad={padding}")

    scaled_images_info = []
    for i, img_obj in enumerate(pil_images):
        aspect_ratio = img_obj.width / img_obj.height
        new_height = target_row_height
        new_width = int(new_height * aspect_ratio)
        try:
            scaled_img = img_obj.resize((new_width, new_height), Image.Resampling.BICUBIC)
            scaled_images_info.append({
                'image': scaled_img, 'original_path': original_paths[i],
                'original_width_at_row_h': new_width, 'ratio': width_ratios[i]
            })
        except Exception as e:
            logger.warning(f"Warning: Could not resize image {original_paths[i]}: {e}. Skipping.")
            continue

    if not scaled_images_info:
        logger.error("Error: No images could be scaled for timeline view.")
        return False, thumbnail_layout_data

    final_rows_layout_details = []
    current_y = padding
    row_buffer = []
    current_row_sum_original_widths_at_row_h = 0
    current_row_sum_ratios = 0.0

    for i, item_info in enumerate(scaled_images_info):
        potential_sum_widths = current_row_sum_original_widths_at_row_h + item_info['original_width_at_row_h']
        potential_paddings = (len(row_buffer) + 1 + 1) * padding

        if row_buffer and (potential_sum_widths + potential_paddings > max_grid_width):
            final_rows_layout_details.append({
                'items_info': list(row_buffer),
                'sum_ratios_in_row': current_row_sum_ratios, 'y_pos': current_y
            })
            current_y += target_row_height + padding
            row_buffer = []
            current_row_sum_original_widths_at_row_h = 0
            current_row_sum_ratios = 0.0

        row_buffer.append(item_info)
        current_row_sum_original_widths_at_row_h += item_info['original_width_at_row_h']
        current_row_sum_ratios += item_info['ratio']

    if row_buffer:
        final_rows_layout_details.append({
            'items_info': list(row_buffer),
            'sum_ratios_in_row': current_row_sum_ratios, 'y_pos': current_y
        })
        current_y += target_row_height + padding

    total_grid_height = current_y if final_rows_layout_details else padding
    if total_grid_height <= padding and scaled_images_info:
         total_grid_height = padding + target_row_height + padding

    if not final_rows_layout_details:
        logger.error("Error: No images could be laid out in timeline view (possibly max_grid_width too small).")
        for item in scaled_images_info: item['image'].close()
        return False, thumbnail_layout_data

    grid_image = Image.new("RGB", (max_grid_width, total_grid_height), background_color_rgb)

    for row_detail in final_rows_layout_details:
        current_x = padding
        y_pos = row_detail['y_pos']
        num_images_in_row = len(row_detail['items_info'])
        available_width_for_images = max_grid_width - (num_images_in_row + 1) * padding

        if available_width_for_images <= 0 or row_detail['sum_ratios_in_row'] == 0:
            logger.warning(f"Warning: Row at y={y_pos} has no space or zero sum_ratios. Skipping paste.")
            continue

        for item_info in row_detail['items_info']:
            img_scaled_to_row_h = item_info['image']
            final_thumb_width = int((item_info['ratio'] / row_detail['sum_ratios_in_row']) * available_width_for_images)
            final_thumb_height = target_row_height

            if final_thumb_width <= 0:
                logger.warning(f"Warning: Calculated width for image {item_info['original_path']} is <=0. Skipping.")
                continue

            final_img_for_cell = img_scaled_to_row_h.resize((final_thumb_width, final_thumb_height), Image.Resampling.BICUBIC)
            grid_image.paste(final_img_for_cell, (current_x, y_pos))
            thumbnail_layout_data.append({
                'image_path': item_info['original_path'], 'x': current_x, 'y': y_pos,
                'width': final_thumb_width, 'height': final_thumb_height
            })
            current_x += final_thumb_width + padding

    try:
        grid_image.save(output_path)
        logger.info(f"Timeline view grid saved to {output_path}")
        return True, thumbnail_layout_data
    except Exception as e:
        logger.error(f"Error saving timeline view grid: {e}")
        return False, thumbnail_layout_data
    finally:
        for item in scaled_images_info: item['image'].close() # Close images opened in this function
        grid_image.close()

def create_image_grid(
    image_source_data, output_path, padding, logger, background_color_hex="#FFFFFF",
    layout_mode="grid", columns=None, rows=None, target_row_height=None,
    max_grid_width=None, target_thumbnail_width=None, output_width=None, output_height=None, target_thumbnail_height=None, grid_margin=0, rounded_corners=0, frame_info_show=True, show_header=True, show_file_path=True, show_timecode=True, show_frame_num=True, frame_info_timecode_or_frame="timecode", frame_info_font_color="#FFFFFF", frame_info_bg_color="#000000", frame_info_position="bottom_left", frame_info_size=10, frame_info_margin=5):
    thumbnail_layout_data = []
    if not image_source_data:
        logger.error("No image source data provided."); return False, thumbnail_layout_data
    if padding < 0:
        logger.error("Padding cannot be negative."); return False, thumbnail_layout_data

    try: background_color_rgb = ImageColor.getrgb(background_color_hex)
    except ValueError: logger.warning(f"Invalid hex '{background_color_hex}'. Using white."); background_color_rgb = (255,255,255)

    processed_image_input = []

    if layout_mode == "timeline":
        if not all(isinstance(item, dict) and 'image_path' in item and 'width_ratio' in item for item in image_source_data):
            logger.error("For timeline mode, image_source_data requires dicts with 'image_path' and 'width_ratio'.")
            return False, thumbnail_layout_data
        if target_row_height is None or max_grid_width is None or target_row_height <= 0 or max_grid_width <= 0:
            logger.error("For timeline mode, target_row_height and max_grid_width must be positive.")
            return False, thumbnail_layout_data

        for item in image_source_data:
            img_path = item['image_path']
            ratio = item['width_ratio']
            if not os.path.exists(img_path): logger.warning(f"Image not found: {img_path}. Skipping."); continue
            try:
                img = Image.open(img_path); img.load() # Load to ensure file is read
                processed_image_input.append((img, img_path, float(ratio)))
            except Exception as e: logger.warning(f"Could not load image {img_path}: {e}. Skipping."); continue

    elif layout_mode == "grid":
        if (columns is None or columns <= 0) and (rows is None or rows <= 0):
            logger.error("For grid mode, either 'columns' or 'rows' must be a positive integer.")
            return False, thumbnail_layout_data

        # If explicit columns are not provided (or invalid), but rows are provided,
        # calculate columns based on rows.
        # This prioritizes explicit 'columns' if both are present (fixing GUI slider bug).
        if (columns is None or columns <= 0) and (rows is not None and rows > 0):
            num_imgs = len(image_source_data)
            columns = max(1, math.ceil(num_imgs / rows))

        if target_thumbnail_width is not None and not (isinstance(target_thumbnail_width, int) and target_thumbnail_width > 0):
            logger.error("For grid mode, if target_thumbnail_width is provided, it must be a positive integer."); return False, thumbnail_layout_data
        if not all(isinstance(p, str) for p in image_source_data):
             logger.error("For grid mode, image_source_data must be a list of image file paths."); return False, thumbnail_layout_data

        for img_path in image_source_data:
            if not os.path.exists(img_path): logger.warning(f"Image not found: {img_path}. Skipping."); continue
            try:
                img = Image.open(img_path); img.load() # Load to ensure file is read
                processed_image_input.append((img, img_path))
            except Exception as e: logger.warning(f"Could not load image {img_path}: {e}. Skipping."); continue
    else:
        logger.error(f"Unknown layout_mode '{layout_mode}'."); return False, thumbnail_layout_data

    if not processed_image_input:
        logger.error("No valid images could be loaded or processed."); return False, thumbnail_layout_data

    output_dir = os.path.dirname(output_path)
    if output_dir and not os.path.exists(output_dir):
        try: os.makedirs(output_dir); logger.info(f"Created output directory: {output_dir}")
        except OSError as e: logger.error(f"Error creating output dir {output_dir}: {e}"); return False, thumbnail_layout_data

    success = False
    # Pass **kwargs implicitly if they are expected by helpers, or remove if not used
    if layout_mode == "grid":
        success, thumbnail_layout_data = _create_fixed_column_grid(
            processed_image_input, output_path, columns, padding, background_color_rgb, logger=logger, target_thumbnail_width=target_thumbnail_width, output_width=output_width, output_height=output_height, target_thumbnail_height=target_thumbnail_height, grid_margin=grid_margin, rounded_corners=rounded_corners, frame_info_show=frame_info_show, show_header=show_header, show_file_path=show_file_path, show_timecode=show_timecode, show_frame_num=show_frame_num, frame_info_timecode_or_frame=frame_info_timecode_or_frame, frame_info_font_color=frame_info_font_color, frame_info_bg_color=frame_info_bg_color, frame_info_position=frame_info_position, frame_info_size=frame_info_size, frame_info_margin=frame_info_margin
        )
    elif layout_mode == "timeline":
        success, thumbnail_layout_data = _create_timeline_view_grid(
            processed_image_input, output_path, max_grid_width, target_row_height, padding, background_color_rgb, logger=logger
        )

    for item_tuple in processed_image_input:
        try: item_tuple[0].close()
        except Exception: pass

    return success, thumbnail_layout_data

if __name__ == "__main__":
    test_logger = logging.getLogger("image_grid_test")
    test_logger.setLevel(logging.INFO)
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
    test_logger.addHandler(handler)
    test_logger.propagate = False
    import shutil
    test_logger.info("Starting image grid creation process demonstrations...") # Changed
    dummy_image_folder = "dummy_thumbnails_grid_metadata"
    if os.path.exists(dummy_image_folder): shutil.rmtree(dummy_image_folder)
    os.makedirs(dummy_image_folder)

    num_dummy_images = 12
    dummy_paths_for_grid = []
    dummy_data_for_timeline = []

    for i in range(num_dummy_images):
        path = os.path.join(dummy_image_folder, f"dummy_thumb_{i+1:02d}.png")
        try:
            img = Image.new("RGB", (120 + (i%3*20), 90 + (i%2*15)), ((i*20)%255, (i*10)%255, (i*5)%255))
            ImageDraw.Draw(img).text((10,10), f"T{i+1}", fill=(255,255,255))
            img.save(path); img.close()
            dummy_paths_for_grid.append(path)
            dummy_data_for_timeline.append({'image_path': path, 'width_ratio': 1.0 + (i % 4)})
        except Exception as e: test_logger.error(f"Error creating dummy img {path}: {e}")

    output_grids_folder = "output_grids_metadata"
    if os.path.exists(output_grids_folder): shutil.rmtree(output_grids_folder)
    os.makedirs(output_grids_folder)

    if not dummy_paths_for_grid:
        test_logger.error("No dummy images created. Aborting examples.")
    else:
        test_logger.info(f"\n--- Example 1: Fixed Column Grid (returning layout) ---") # Changed
        grid_ok, grid_layout = create_image_grid(
            image_source_data=dummy_paths_for_grid,
            output_path=os.path.join(output_grids_folder, "grid_fixed_metadata.png"),
            padding=5, logger=test_logger, layout_mode="grid", columns=4 # Added logger
        )
        if grid_ok: test_logger.info(f"  Grid layout items: {len(grid_layout)}. First item: {grid_layout[0] if grid_layout else 'N/A'}")

        test_logger.info(f"\n--- Example 1b: Fixed Column Grid with target_thumbnail_width ---")
        grid_target_ok, grid_target_layout = create_image_grid(
            image_source_data=dummy_paths_for_grid,
            output_path=os.path.join(output_grids_folder, "grid_fixed_target_width_metadata.png"),
            padding=5, logger=test_logger, layout_mode="grid", columns=3, target_thumbnail_width=100
        )
        if grid_target_ok: test_logger.info(f"  Grid (target_width=100) layout items: {len(grid_target_layout)}. First item: {grid_target_layout[0] if grid_target_layout else 'N/A'}")


        test_logger.info(f"\n--- Example 2: Timeline View Grid (returning layout) ---") # Changed
        timeline_ok, timeline_layout = create_image_grid(
            image_source_data=dummy_data_for_timeline,
            output_path=os.path.join(output_grids_folder, "grid_timeline_metadata.png"),
            padding=8, logger=test_logger, layout_mode="timeline", target_row_height=90, max_grid_width=700 # Added logger
        )
        if timeline_ok: test_logger.info(f"  Timeline layout items: {len(timeline_layout)}. First item: {timeline_layout[0] if timeline_layout else 'N/A'}")

    test_logger.info("\nImage grid script demonstrations finished.") # Changed
