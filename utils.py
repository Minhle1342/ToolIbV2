import os
import glob
import shutil
import json
import math
import yaml
import random
from sqlalchemy import or_
from datetime import datetime
from models import db, Image, Project, View, Tag

try:
    import cv2
    import numpy as np
except ImportError:
    cv2 = None
    np = None

ALLOWED_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.bmp'}


def get_dataset_tags_path(project):
    return os.path.join(project.root_path, 'dataset_tags.json')


def persist_dataset_tags(project):
    """
    Persist project tags and image-tag assignments to dataset_tags.json
    inside the project root for recovery outside the database.
    """
    if not project or not project.root_path:
        return None

    os.makedirs(project.root_path, exist_ok=True)

    tags = Tag.query.filter_by(project_id=project.id).order_by(Tag.id.asc()).all()
    images = Image.query.filter_by(project_id=project.id).order_by(Image.id.asc()).all()

    payload = {
        'project_id': project.id,
        'project_name': project.name,
        'updated_at': datetime.utcnow().isoformat() + 'Z',
        'project_tags': [
            {
                'id': tag.id,
                'name': tag.name,
                'color': tag.color,
            }
            for tag in tags
        ],
        'images': {}
    }

    for image in images:
        tag_names = sorted(tag.name for tag in image.tags)
        if tag_names:
            payload['images'][image.filename] = tag_names

    tags_file = get_dataset_tags_path(project)
    with open(tags_file, 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, indent=4)

    return tags_file


def imread_with_exif(image_path, flags=None):
    """
    Read an image with cv2 and apply EXIF orientation exactly once.

    OpenCV normally applies EXIF orientation during ``imread``. Reading the
    image that way and rotating it again from the EXIF tag causes portrait
    images to be double-rotated, so inference coordinates no longer match the
    browser canvas. Decode the stored pixels without automatic orientation and
    then apply every EXIF orientation explicitly.
    """
    if cv2 is None:
        return None

    read_flags = cv2.IMREAD_COLOR if flags is None else flags
    if read_flags != cv2.IMREAD_UNCHANGED:
        read_flags |= cv2.IMREAD_IGNORE_ORIENTATION

    img = cv2.imread(image_path, read_flags)

    if img is None:
        return None

    try:
        from PIL import Image as PILImage
        with PILImage.open(image_path) as pil_img:
            orientation = pil_img.getexif().get(274, 1)

        if orientation == 2:       # Mirrored horizontally
            img = cv2.flip(img, 1)
        elif orientation == 3:     # Rotated 180 degrees
            img = cv2.rotate(img, cv2.ROTATE_180)
        elif orientation == 4:     # Mirrored vertically
            img = cv2.flip(img, 0)
        elif orientation == 5:     # Mirrored across the top-left diagonal
            img = cv2.transpose(img)
        elif orientation == 6:     # Rotated 90 degrees clockwise
            img = cv2.rotate(img, cv2.ROTATE_90_CLOCKWISE)
        elif orientation == 7:     # Mirrored across the top-right diagonal
            img = cv2.flip(cv2.transpose(img), -1)
        elif orientation == 8:     # Rotated 90 degrees counter-clockwise
            img = cv2.rotate(img, cv2.ROTATE_90_COUNTERCLOCKWISE)
    except (OSError, ValueError, TypeError, ImportError):
        pass  # Missing/invalid EXIF: keep the decoded pixel orientation.

    return img


def resize_image_quality(img, target_size):
    """
    Resize with interpolation tuned for image quality:
    - downscale: INTER_AREA
    - upscale: INTER_CUBIC
    """
    if img is None:
        return None

    target_w, target_h = target_size
    src_h, src_w = img.shape[:2]
    if src_w <= 0 or src_h <= 0 or target_w <= 0 or target_h <= 0:
        return img

    interpolation = cv2.INTER_CUBIC if target_w > src_w or target_h > src_h else cv2.INTER_AREA
    return cv2.resize(img, (int(target_w), int(target_h)), interpolation=interpolation)


def clip_pixel_bounds(xmin, ymin, xmax, ymax, img_w, img_h):
    x1 = max(0, min(img_w, int(math.floor(xmin))))
    y1 = max(0, min(img_h, int(math.floor(ymin))))
    x2 = max(0, min(img_w, int(math.ceil(xmax))))
    y2 = max(0, min(img_h, int(math.ceil(ymax))))

    if x2 <= x1 or y2 <= y1:
        return None

    return (x1, y1, x2, y2)


def region_to_pixel_bounds(region, img_w, img_h):
    if not region:
        return None

    r_x = float(region.get('x', 0))
    r_y = float(region.get('y', 0))
    r_w = float(region.get('w', 0))
    r_h = float(region.get('h', 0))

    if r_w <= 0 or r_h <= 0:
        return None

    is_normalized = r_x <= 1.0 and r_y <= 1.0 and r_w <= 1.0 and r_h <= 1.0
    if is_normalized:
        left = r_x * img_w
        top = r_y * img_h
        width = r_w * img_w
        height = r_h * img_h
    else:
        left = r_x
        top = r_y
        width = r_w
        height = r_h

    return clip_pixel_bounds(left, top, left + width, top + height, img_w, img_h)


def yolo_box_to_pixel_bounds(box, img_w, img_h, padding_ratio=0.0, min_padding_px=0):
    cx = float(box.get('x', 0))
    cy = float(box.get('y', 0))
    bw = float(box.get('w', 0))
    bh = float(box.get('h', 0))

    if bw <= 0 or bh <= 0:
        return None

    is_normalized = (
        abs(cx) <= 1.0 and abs(cy) <= 1.0 and
        abs(bw) <= 1.0 and abs(bh) <= 1.0
    )

    if is_normalized:
        abs_cx = cx * img_w
        abs_cy = cy * img_h
        abs_w = bw * img_w
        abs_h = bh * img_h
    else:
        abs_cx = cx
        abs_cy = cy
        abs_w = bw
        abs_h = bh

    padding = max(min_padding_px, max(abs_w, abs_h) * float(padding_ratio))
    half_w = abs_w / 2.0
    half_h = abs_h / 2.0

    return clip_pixel_bounds(
        abs_cx - half_w - padding,
        abs_cy - half_h - padding,
        abs_cx + half_w + padding,
        abs_cy + half_h + padding,
        img_w,
        img_h
    )


def crop_bgr_with_bounds(img, bounds):
    if img is None or bounds is None:
        return None

    x1, y1, x2, y2 = bounds
    if x2 <= x1 or y2 <= y1:
        return None

    return img[y1:y2, x1:x2].copy()

def scan_and_sync_images(project):
    """
    Scans project.root_path for images.
    Adds new images to DB.
    Checks for existing corresponding .txt label files and sets is_labeled=True.
    Returns number of new images added.
    """
    if not os.path.exists(project.root_path):
        return 0

    # Auto-generate or overwrite classes.txt from data.yaml if it exists
    classes_file = os.path.join(project.root_path, 'classes.txt')
    for yaml_name in ['data.yaml', 'data.yml']:
        yaml_path = os.path.join(project.root_path, yaml_name)
        if os.path.exists(yaml_path):
            try:
                with open(yaml_path, 'r', encoding='utf-8') as f:
                    data = yaml.safe_load(f)
                    if data and 'names' in data:
                        names = data['names']
                        if isinstance(names, dict):
                            names = [str(names[k]) for k in sorted(names.keys())]
                        elif isinstance(names, list):
                            names = [str(n) for n in names]
                        with open(classes_file, 'w', encoding='utf-8') as cf:
                            cf.write('\n'.join(names))
                        break
            except Exception as e:
                print(f"Error parsing {yaml_name}: {e}")

    db_images_by_filename = {img.filename: img for img in project.images}
    existing_images = set(db_images_by_filename.keys())
    new_images_count = 0
    
    # Scan folder
    for root, dirs, files in os.walk(project.root_path):
        for file in files:
            ext = os.path.splitext(file)[1].lower()
            if ext in ALLOWED_EXTENSIONS:
                label_file = os.path.join(root, os.path.splitext(file)[0] + '.txt')
                
                # Check if file has coordinate data
                has_coords = False
                if os.path.exists(label_file):
                    try:
                        with open(label_file, 'r', encoding='utf-8') as lf:
                            for line in lf:
                                parts = line.strip().split()
                                if len(parts) == 5:
                                    try:
                                        int(parts[0])
                                        float(parts[1])
                                        float(parts[2])
                                        width = float(parts[3])
                                        height = float(parts[4])
                                        if width <= 0 or height <= 0:
                                            continue
                                        has_coords = True
                                        break
                                    except ValueError:
                                        pass
                    except Exception:
                        pass
                
                if file not in existing_images:
                    new_image = Image(
                        filename=file,
                        project_id=project.id,
                        is_labeled=has_coords
                    )
                    db.session.add(new_image)
                    new_images_count += 1
                else:
                    img_obj = db_images_by_filename[file]
                    if img_obj.is_labeled != has_coords:
                        img_obj.is_labeled = has_coords
    
    db.session.commit()
    return new_images_count

def sync_dataset_tags(project):
    """
    Syncs tags from dataset_tags.json if it exists in the project root.
    """
    tags_file = get_dataset_tags_path(project)
    if not os.path.exists(tags_file):
        return

    try:
        with open(tags_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
            
        project_tags = data.get('project_tags', [])
        images_data = data.get('images', {})
        
        # Ensure tags exist
        tag_map = {}
        existing_tags = Tag.query.filter_by(project_id=project.id).all()
        for t in existing_tags:
            tag_map[t.name] = t
            
        for pt in project_tags:
            name = pt.get('name')
            color = pt.get('color', '#3B82F6')
            if name and name not in tag_map:
                new_tag = Tag(name=name, color=color, project_id=project.id)
                db.session.add(new_tag)
                tag_map[name] = new_tag
                
        db.session.commit()
        
        # Assign tags to images
        db_images = Image.query.filter_by(project_id=project.id).all()
        img_dict = {img.filename: img for img in db_images}
        
        for filename, tag_names in images_data.items():
            if filename in img_dict:
                img = img_dict[filename]
                current_tags = set(t.name for t in img.tags)
                
                for t_name in tag_names:
                    if t_name in tag_map and t_name not in current_tags:
                        img.tags.append(tag_map[t_name])
                        current_tags.add(t_name)
                        
        db.session.commit()
        
    except Exception as e:
        print(f"Error syncing dataset tags: {e}")

def assign_images_to_view(view_id, count, project_id, assign_mode='both'):
    """
    Assigns 'count' unassigned images from 'project_id' to 'view_id'.
    Returns number of assigned images.
    """
    try:
        count = int(count)
    except ValueError:
        return 0

    query = Image.query.filter_by(project_id=project_id, view_id=None)
    
    if assign_mode == 'labeled':
        query = query.filter_by(is_labeled=True)
    elif assign_mode == 'unlabeled':
        query = query.filter_by(is_labeled=False)

    unassigned_images = query.limit(count).all()
    
    for img in unassigned_images:
        img.view_id = view_id
    
    db.session.commit()
    return len(unassigned_images)

def read_yolo_label(image):
    """
    Reads corresponding .txt file for the image.
    Returns list of parsed label objects.
    """
    project = Project.query.get(image.project_id)
    label_file = os.path.join(project.root_path, os.path.splitext(image.filename)[0] + '.txt')
    
    labels = []
    if os.path.exists(label_file):
        with open(label_file, 'r') as f:
            for line in f:
                parts = line.strip().split()
                if len(parts) == 5:
                    try:
                        class_id = int(parts[0])
                        x = float(parts[1])
                        y = float(parts[2])
                        w = float(parts[3])
                        h = float(parts[4])
                        if w <= 0 or h <= 0:
                            continue
                        labels.append({
                            'class_id': class_id,
                            'x': x,
                            'y': y,
                            'w': w,
                            'h': h
                        })
                    except ValueError:
                        pass
    return labels

def save_yolo_label(image, labels):
    """
    Writes labels to .txt file.
    labels: list of dicts: {'class_id', 'x', 'y', 'w', 'h'}
    """
    project = Project.query.get(image.project_id)
    label_file = os.path.join(project.root_path, os.path.splitext(image.filename)[0] + '.txt')
    
    saved_count = 0
    with open(label_file, 'w') as f:
        for label in labels:
            try:
                class_id = int(label['class_id'])
                x = float(label['x'])
                y = float(label['y'])
                w = float(label['w'])
                h = float(label['h'])
                if w <= 0 or h <= 0:
                    continue
                line = f"{class_id} {x} {y} {w} {h}\n"
                f.write(line)
                saved_count += 1
            except (KeyError, TypeError, ValueError):
                pass
    return saved_count

def export_dataset(criteria, splits=None, format='yolo'):
    """
    Exports dataset based on criteria.
    criteria: { ... }
    format: 'yolo' | 'split'
    splits: {'train': 80, 'val': 10, 'test': 10}
    """
    if splits is None:
        splits = {'train': 80, 'val': 20, 'test': 0}
    elif isinstance(splits, (int, float)):
        # Backward compatibility: old callers passed a train ratio like 0.8.
        train_ratio = float(splits)
        if 0 <= train_ratio <= 1:
            train_pct = int(round(train_ratio * 100))
        else:
            train_pct = int(round(train_ratio))
        train_pct = max(0, min(train_pct, 100))
        splits = {
            'train': train_pct,
            'val': 100 - train_pct,
            'test': 0
        }
        
    # 1. Prepare Export Directory
    base_export_dir = os.path.abspath("exported_dataset")
    if os.path.exists(base_export_dir):
        shutil.rmtree(base_export_dir)
    
    # Define paths based on format
    # structure map: split_name -> { 'images': rel_path, 'labels': rel_path }
    dirs_map = {}
    
    if format == 'split':
        # Structure: train/images, train/labels
        dirs_map = {
            'train': {'images': 'train/images', 'labels': 'train/labels'},
            'val': {'images': 'val/images', 'labels': 'val/labels'},
            'test': {'images': 'test/images', 'labels': 'test/labels'}
        }
    else:
        # Default 'yolo': images/train, labels/train
        dirs_map = {
            'train': {'images': 'images/train', 'labels': 'labels/train'},
            'val': {'images': 'images/val', 'labels': 'labels/val'},
            'test': {'images': 'images/test', 'labels': 'labels/test'}
        }

    # Create directories
    for split in ['train', 'val', 'test']:
        if splits.get(split, 0) > 0:
            os.makedirs(os.path.join(base_export_dir, dirs_map[split]['images']))
            os.makedirs(os.path.join(base_export_dir, dirs_map[split]['labels']))

    all_images = []
    
    # 2. Gather Images based on Criteria
    target_images = []
    include_untagged = criteria.get('include_untagged', False)
    include_unlabeled = criteria.get('include_unlabeled', False)
    
    if criteria.get('image_ids'):
        # Specific images (e.g. from selection)
        target_images = Image.query.filter(Image.id.in_(criteria['image_ids'])).all()
        
    elif criteria.get('view_id'):
        query = Image.query.filter_by(view_id=criteria['view_id'])
        if not include_unlabeled:
            query = query.filter_by(is_labeled=True)
        target_images = query.all()
        
    elif criteria.get('tags') and criteria.get('project_ids'):
        query = Image.query.filter(Image.project_id.in_(criteria['project_ids']))
        if not include_unlabeled:
            query = query.filter(Image.is_labeled == True)
        if include_untagged:
            query = query.filter(
                or_(
                    Image.tags.any(Tag.id.in_(criteria['tags'])),
                    ~Image.tags.any()
                )
            )
        else:
            query = query.filter(Image.tags.any(Tag.id.in_(criteria['tags'])))
        target_images = query.all()
        
    elif criteria.get('project_ids'):
        # Multiple projects
        query = Image.query.filter(Image.project_id.in_(criteria['project_ids']))
        if not include_unlabeled:
            query = query.filter(Image.is_labeled == True)
        target_images = query.all()
        
    # Filter out flagged images if requested
    if criteria.get('exclude_flagged', False):
         target_images = [img for img in target_images if img.flag_status != 'Flagged']
         
    if criteria.get('has_any_tag', False):
         target_images = [img for img in target_images if len(img.tags) > 0]
         
    if not target_images:
         return {'status': 'error', 'message': 'No images found matching criteria.'}

    # 3. Process Images
    # We need projects to resolve paths. Cache them.
    projects_cache = {}
    
    class_names = []
    # Attempt to get classes from the first project available
    first_img = target_images[0]
    p = Project.query.get(first_img.project_id)
    if p:
        class_names = get_classes(p)

    for img in target_images:
        if img.project_id not in projects_cache:
            projects_cache[img.project_id] = Project.query.get(img.project_id)
        
        project = projects_cache[img.project_id]
        
        src_img_path = os.path.join(project.root_path, img.filename)
        src_label_path = os.path.join(project.root_path, os.path.splitext(img.filename)[0] + '.txt')
        
        if os.path.exists(src_img_path):
            # Check if label file has at least one bounding box and get classes
            has_boxes = False
            box_count = 0
            classes_in_image = set()
            if os.path.exists(src_label_path):
                try:
                    with open(src_label_path, 'r', encoding='utf-8') as f:
                        for line in f:
                            parts = line.strip().split()
                            if len(parts) == 5:
                                try:
                                    class_id = int(parts[0])
                                    x = float(parts[1])
                                    y = float(parts[2])
                                    w = float(parts[3])
                                    h = float(parts[4])
                                    if w <= 0 or h <= 0:
                                        continue
                                    classes_in_image.add(class_id)
                                    has_boxes = True
                                    box_count += 1
                                except ValueError:
                                    pass
                except (OSError, UnicodeError):
                    pass

            if has_boxes or include_unlabeled:
                all_images.append({
                    'image_obj': img,
                    'img_path': src_img_path,
                    'label_path': src_label_path if has_boxes else None,
                    'filename': f"{img.project_id}_{img.filename}", # Prefix to avoid collision
                    'box_count': box_count,
                    'classes': list(classes_in_image)
                })

    if not all_images:
        return {'status': 'error', 'message': 'No valid images found.'}

    forced_assignments = criteria.get('tagged_split_assignments') or {}
    forced_ids_by_split = {
        'train': {int(image_id) for image_id in forced_assignments.get('train', [])},
        'val': {int(image_id) for image_id in forced_assignments.get('val', [])},
        'test': {int(image_id) for image_id in forced_assignments.get('test', [])}
    }

    if any(forced_ids_by_split.values()):
        train_set, val_set, test_set = [], [], []
        assigned_ids = set()

        for item in all_images:
            image_id = item['image_obj'].id
            if image_id in forced_ids_by_split['train']:
                train_set.append(item)
                assigned_ids.add(image_id)
            elif image_id in forced_ids_by_split['val']:
                val_set.append(item)
                assigned_ids.add(image_id)
            elif image_id in forced_ids_by_split['test']:
                test_set.append(item)
                assigned_ids.add(image_id)

        for item in all_images:
            if item['image_obj'].id in assigned_ids:
                continue

            split_name = item['image_obj'].split_type or 'train'
            if split_name == 'val':
                val_set.append(item)
            elif split_name == 'test':
                test_set.append(item)
            else:
                train_set.append(item)

        random.shuffle(train_set)
        random.shuffle(val_set)
        random.shuffle(test_set)
    else:
        # Calculate exact target split sizes
        total_images = len(all_images)
        train_pct = splits.get('train', 0) / 100.0
        val_pct = splits.get('val', 0) / 100.0
        
        train_count = round(total_images * train_pct)
        val_count = round(total_images * val_pct)
        test_count = total_images - train_count - val_count

        # Stratified Split logic
        class_counts = {}
        for img_data in all_images:
            for c in img_data['classes']:
                class_counts[c] = class_counts.get(c, 0) + 1
                
        for img_data in all_images:
            rarest_class = None
            min_count = float('inf')
            for c in img_data['classes']:
                if class_counts[c] < min_count:
                    min_count = class_counts[c]
                    rarest_class = c
            img_data['rarest_class'] = rarest_class
            
        class_groups = {}
        for img_data in all_images:
            rc = img_data['rarest_class']
            if rc not in class_groups:
                class_groups[rc] = []
            class_groups[rc].append(img_data)
            
        train_set, val_set, test_set = [], [], []
        
        for c, group in class_groups.items():
            random.shuffle(group)
            group_size = len(group)
            g_train = round(group_size * train_pct)
            g_val = round(group_size * val_pct)
            g_val = min(g_val, group_size - g_train)
            
            train_set.extend(group[:g_train])
            val_set.extend(group[g_train:g_train + g_val])
            test_set.extend(group[g_train + g_val:])
            
        # Rebalance to meet exact targets
        sets = [train_set, val_set, test_set]
        targets = [train_count, val_count, test_count]
        
        for i in range(3):
            while len(sets[i]) > targets[i]:
                for j in range(3):
                    if len(sets[j]) < targets[j]:
                        sets[j].append(sets[i].pop())
                        break
                        
        random.shuffle(train_set)
        random.shuffle(val_set)
        random.shuffle(test_set)

    def copy_files(dataset, split_name):
        if not dataset:
            return
        paths = dirs_map[split_name]
        for item in dataset:
            item['image_obj'].split_type = split_name
            # Copy Image
            shutil.copy(item['img_path'], os.path.join(base_export_dir, paths['images'], item['filename']))
            # Negative/background samples use an empty YOLO label file.
            destination_label = os.path.join(
                base_export_dir,
                paths['labels'],
                os.path.splitext(item['filename'])[0] + '.txt'
            )
            if item['label_path']:
                shutil.copy(item['label_path'], destination_label)
            else:
                with open(destination_label, 'w', encoding='utf-8'):
                    pass

    copy_files(train_set, 'train')
    copy_files(val_set, 'val')
    copy_files(test_set, 'test')
    
    db.session.commit()

    # Generate data.yaml
    # Update paths in yaml to be relative to the yaml file location (base_export_dir)
    # YOLO expects paths relative to the dataset root or absolute. Relative is safer for portability.
    
    # Ensure forward slashes for cross-platform compatibility in YAML
    yaml_content = {
        'path': '.', # Root relative to data.yaml
        'nc': len(class_names),
        'names': class_names
    }
    
    if splits.get('train', 0) > 0:
        yaml_content['train'] = dirs_map['train']['images'].replace(os.sep, '/')
    if splits.get('val', 0) > 0:
        yaml_content['val'] = dirs_map['val']['images'].replace(os.sep, '/')
    if splits.get('test', 0) > 0:
        yaml_content['test'] = dirs_map['test']['images'].replace(os.sep, '/')
    
    yaml_path = os.path.join(base_export_dir, 'data.yaml')
    with open(yaml_path, 'w', encoding='utf-8') as f:
        yaml.dump(yaml_content, f, default_flow_style=False, sort_keys=False, allow_unicode=True)

    import json
    tags_metadata = {
        'project_tags': [],
        'images': {}
    }
    selected_metadata_tag_ids = set()
    for tag_id in criteria.get('tags') or []:
        try:
            selected_metadata_tag_ids.add(int(tag_id))
        except (TypeError, ValueError):
            pass

    used_tags = {}
    
    for split_set in [train_set, val_set, test_set]:
        for item in split_set:
            img = item['image_obj']
            exported_filename = item['filename']
            if getattr(img, 'tags', None):
                tag_names = []
                for tag in img.tags:
                    if selected_metadata_tag_ids and tag.id not in selected_metadata_tag_ids:
                        continue
                    tag_names.append(tag.name)
                    if tag.id not in used_tags:
                        used_tags[tag.id] = {'name': tag.name, 'color': tag.color}
                if tag_names:
                    tags_metadata['images'][exported_filename] = tag_names
                
    for tag_data in used_tags.values():
        tags_metadata['project_tags'].append(tag_data)
        
    if used_tags:
        tags_json_path = os.path.join(base_export_dir, 'dataset_tags.json')
        with open(tags_json_path, 'w', encoding='utf-8') as f:
            json.dump(tags_metadata, f, ensure_ascii=False, indent=4)

    return {
        'status': 'success',
        'export_path': base_export_dir,
        'stats': {
            'total': len(all_images),
            'unlabeled': sum(1 for item in all_images if not item['label_path']),
            'train': len(train_set),
            'val': len(val_set),
            'test': len(test_set)
        }
    }

def get_classes(project):
    classes_file = os.path.join(project.root_path, 'classes.txt')
    if os.path.exists(classes_file):
        with open(classes_file, 'r', encoding='utf-8') as f:
            classes = [line.strip() for line in f.readlines() if line.strip()]
            if classes:
                return classes
                
    # If missing or empty, find max class id from all label files
    max_id = -1
    label_files = glob.glob(os.path.join(project.root_path, '*.txt'))
    for lf in label_files:
        if os.path.basename(lf) == 'classes.txt':
            continue
        try:
            with open(lf, 'r', encoding='utf-8') as f:
                for line in f:
                    parts = line.strip().split()
                    if len(parts) == 5:
                        try:
                            cid = int(parts[0])
                            float(parts[1])
                            float(parts[2])
                            width = float(parts[3])
                            height = float(parts[4])
                            if width <= 0 or height <= 0:
                                continue
                            if cid > max_id:
                                max_id = cid
                        except ValueError:
                            pass
        except Exception:
            pass
            
    if max_id >= 0:
        classes = [f'Class {i}' for i in range(max_id + 1)]
    else:
        classes = ['Class 0', 'Class 1', 'Class 2', 'Class 3', 'Class 4']
    
    save_classes(project, classes)
    return classes

def save_classes(project, classes):
    classes_file = os.path.join(project.root_path, 'classes.txt')
    with open(classes_file, 'w', encoding='utf-8') as f:
        f.write('\n'.join(classes))

    # Also update data.yaml or data.yml if it exists
    for yaml_name in ['data.yaml', 'data.yml']:
        yaml_path = os.path.join(project.root_path, yaml_name)
        if os.path.exists(yaml_path):
            try:
                with open(yaml_path, 'r', encoding='utf-8') as f:
                    data = yaml.safe_load(f) or {}
                
                data['names'] = classes
                data['nc'] = len(classes)
                
                with open(yaml_path, 'w', encoding='utf-8') as f:
                    yaml.dump(data, f, default_flow_style=False, sort_keys=False, allow_unicode=True)
            except Exception as e:
                print(f"Error updating {yaml_name}: {e}")


def get_image_classes(image):
    """
    Reads the unique class IDs present in the image's label file.
    """
    project = Project.query.get(image.project_id)
    label_file = os.path.join(project.root_path, os.path.splitext(image.filename)[0] + '.txt')
    classes = set()
    if os.path.exists(label_file):
        try:
            with open(label_file, 'r') as f:
                for line in f:
                    parts = line.strip().split()
                    if len(parts) == 5:
                        try:
                            class_id = int(parts[0])
                            float(parts[1])
                            float(parts[2])
                            width = float(parts[3])
                            height = float(parts[4])
                            if width <= 0 or height <= 0:
                                continue
                            classes.add(class_id)
                        except ValueError:
                            pass
        except Exception:
            pass
    return sorted(list(classes))
