import os
import glob
from models import db, Image, Project

import os
import glob
import shutil
import yaml
import random
from models import db, Image, Project, View

ALLOWED_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.bmp'}

def scan_and_sync_images(project):
    """
    Scans project.root_path for images.
    Adds new images to DB.
    Checks for existing corresponding .txt label files and sets is_labeled=True.
    Returns number of new images added.
    """
    if not os.path.exists(project.root_path):
        return 0

    # Auto-generate classes.txt from data.yaml if it exists and classes.txt doesn't
    classes_file = os.path.join(project.root_path, 'classes.txt')
    if not os.path.exists(classes_file):
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

    existing_images = set(img.filename for img in project.images)
    new_images_count = 0
    
    # Scan folder
    for root, dirs, files in os.walk(project.root_path):
        for file in files:
            ext = os.path.splitext(file)[1].lower()
            if ext in ALLOWED_EXTENSIONS:
                if file not in existing_images:
                    # Check for labels (same directory)
                    label_file = os.path.join(root, os.path.splitext(file)[0] + '.txt')
                    is_labeled = os.path.exists(label_file) and os.path.getsize(label_file) > 0
                    
                    new_image = Image(
                        filename=file,
                        project_id=project.id,
                        is_labeled=is_labeled
                    )
                    db.session.add(new_image)
                    new_images_count += 1
    
    db.session.commit()
    return new_images_count

def assign_images_to_view(view_id, count, project_id):
    """
    Assigns 'count' unassigned images from 'project_id' to 'view_id'.
    Returns number of assigned images.
    """
    try:
        count = int(count)
    except ValueError:
        return 0

    unassigned_images = Image.query.filter_by(project_id=project_id, view_id=None).limit(count).all()
    
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
                if len(parts) >= 5:
                    labels.append({
                        'class_id': int(parts[0]),
                        'x': float(parts[1]),
                        'y': float(parts[2]),
                        'w': float(parts[3]),
                        'h': float(parts[4])
                    })
    return labels

def save_yolo_label(image, labels):
    """
    Writes labels to .txt file.
    labels: list of dicts: {'class_id', 'x', 'y', 'w', 'h'}
    """
    project = Project.query.get(image.project_id)
    label_file = os.path.join(project.root_path, os.path.splitext(image.filename)[0] + '.txt')
    
    with open(label_file, 'w') as f:
        for label in labels:
            line = f"{label['class_id']} {label['x']} {label['y']} {label['w']} {label['h']}\n"
            f.write(line)

def export_dataset(criteria, splits=None, format='yolo'):
    """
    Exports dataset based on criteria.
    criteria: { ... }
    format: 'yolo' | 'split'
    splits: {'train': 80, 'val': 10, 'test': 10}
    """
    if splits is None:
        splits = {'train': 80, 'val': 20, 'test': 0}
        
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
    
    if criteria.get('image_ids'):
        # Specific images (e.g. from selection)
        target_images = Image.query.filter(Image.id.in_(criteria['image_ids'])).all()
        
    elif criteria.get('view_id'):
        # All images in a view (labeled or not? User usually wants labeled. Let's filter labeled=True by default)
        target_images = Image.query.filter_by(view_id=criteria['view_id'], is_labeled=True).all()
        
    elif criteria.get('project_ids'):
        # Multiple projects
        target_images = Image.query.filter(
            Image.project_id.in_(criteria['project_ids']), 
            Image.is_labeled==True
        ).all()
        
    # Filter out flagged images if requested
    if criteria.get('exclude_flagged', False):
         target_images = [img for img in target_images if img.flag_status != 'Flagged']
         
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
        
        if os.path.exists(src_img_path) and os.path.exists(src_label_path):
            # Check if label file has at least one bounding box
            has_boxes = False
            try:
                with open(src_label_path, 'r') as f:
                    for line in f:
                        if line.strip():
                            has_boxes = True
                            break
            except Exception:
                pass

            if has_boxes:
                all_images.append({
                    'image_obj': img,
                    'img_path': src_img_path,
                    'label_path': src_label_path,
                    'filename': f"{img.project_id}_{img.filename}" # Prefix to avoid collision
                })

    if not all_images:
        return {'status': 'error', 'message': 'No valid labeled images found.'}

    # 4. Filter empty labels? (Optional)
    
    # Shuffle and Split
    random.shuffle(all_images)
    total_images = len(all_images)
    
    train_pct = splits.get('train', 0) / 100.0
    val_pct = splits.get('val', 0) / 100.0
    
    train_idx = int(total_images * train_pct)
    val_idx = train_idx + int(total_images * val_pct)
    
    train_set = all_images[:train_idx]
    val_set = all_images[train_idx:val_idx]
    test_set = all_images[val_idx:]

    def copy_files(dataset, split_name):
        if not dataset:
            return
        paths = dirs_map[split_name]
        for item in dataset:
            item['image_obj'].split_type = split_name
            # Copy Image
            shutil.copy(item['img_path'], os.path.join(base_export_dir, paths['images'], item['filename']))
            # Copy Label
            shutil.copy(item['label_path'], os.path.join(base_export_dir, paths['labels'], os.path.splitext(item['filename'])[0] + '.txt'))

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

    return {
        'status': 'success',
        'export_path': base_export_dir,
        'stats': {
            'total': len(all_images),
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
                    if parts:
                        try:
                            cid = int(parts[0])
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
                    if parts:
                        try:
                            classes.add(int(parts[0]))
                        except ValueError:
                            pass
        except Exception:
            pass
    return sorted(list(classes))
