# pyrefly: ignore [missing-import]
from flask import Blueprint, jsonify, request, current_app
# pyrefly: ignore [missing-import]
import flask
from models import db, Project, View, Image, AIModel, Tag
import os
import utils
from inference import YOLOInference, ClassificationInference

# Initialize Inference Engines
inference_engine = None
classifier_engine = None

def get_inference_engine():
    global inference_engine
    if inference_engine is None:
        active_model = AIModel.query.filter_by(is_active=True, model_type='detection').first()
        if active_model:
            model_path = os.path.join(os.getcwd(), 'models', active_model.filename)
            if os.path.exists(model_path):
                inference_engine = YOLOInference(model_path)
        else:
            # Fallback to default if no active detection model is set
            model_path = os.path.join(os.getcwd(), 'models', 'yolo12s.onnx')
            if os.path.exists(model_path):
                inference_engine = YOLOInference(model_path)
    return inference_engine

def get_classifier_engine():
    global classifier_engine
    if classifier_engine is None:
        active_cls_model = AIModel.query.filter_by(is_active=True, model_type='classification').first()
        if active_cls_model:
            model_path = os.path.join(os.getcwd(), 'models', active_cls_model.filename)
            if os.path.exists(model_path):
                classifier_engine = ClassificationInference(model_path)
        else:
            # Fallback to default if no active classification model is set
            model_path = os.path.join(os.getcwd(), 'models', 'classifier.onnx')
            if os.path.exists(model_path):
                classifier_engine = ClassificationInference(model_path)
    return classifier_engine




api_bp = Blueprint('api', __name__)

# --- Projects ---
@api_bp.route('/projects', methods=['GET'])
def get_projects():
    projects = Project.query.all()
    return jsonify([p.to_dict() for p in projects])

@api_bp.route('/projects', methods=['POST'])
def create_project():
    data = request.json
    try:
        new_project = Project(
            name=data['name'],
            root_path=data['root_path']
        )
        db.session.add(new_project)
        db.session.commit()
        
        # Tự động quét và đồng bộ ảnh từ thư mục ngay khi tạo project
        try:
            utils.scan_and_sync_images(new_project)
            utils.sync_dataset_tags(new_project)
        except Exception as scan_err:
            print(f"Error during auto-scanning: {scan_err}")
            
        return jsonify(new_project.to_dict()), 201
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@api_bp.route('/projects/<int:project_id>', methods=['PUT'])
def update_project(project_id):
    project = Project.query.get_or_404(project_id)
    data = request.json
    try:
        path_changed = False
        if 'name' in data:
            project.name = data['name']
        if 'root_path' in data and data['root_path'] != project.root_path:
            project.root_path = data['root_path']
            path_changed = True
            
        if path_changed:
            project.images.clear()
            project.views.clear()
            
        db.session.commit()
        
        if path_changed:
            try:
                utils.scan_and_sync_images(project)
                utils.sync_dataset_tags(project)
            except Exception as scan_err:
                print(f"Error during auto-scanning in update: {scan_err}")
                
        return jsonify(project.to_dict())
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 400

@api_bp.route('/projects/<int:project_id>', methods=['DELETE'])
def delete_project(project_id):
    project = Project.query.get_or_404(project_id)
    try:
        db.session.delete(project)
        db.session.commit()
        return jsonify({'message': 'Project deleted successfully'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 400

@api_bp.route('/images/<int:image_id>', methods=['DELETE'])
def delete_image(image_id):
    image = Image.query.get_or_404(image_id)
    project = Project.query.get(image.project_id)
    try:
        image_path = os.path.join(project.root_path, image.filename)
        if os.path.exists(image_path):
            os.remove(image_path)
            
        name_no_ext = os.path.splitext(image.filename)[0]
        label_path = os.path.join(project.root_path, f"{name_no_ext}.txt")
        if os.path.exists(label_path):
            os.remove(label_path)
            
        db.session.delete(image)
        db.session.commit()
        return jsonify({'message': 'Image deleted successfully'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 400

@api_bp.route('/images/batch-delete', methods=['POST'])
def batch_delete_images():
    data = request.json
    image_ids = data.get('image_ids', [])
    if not image_ids:
        return jsonify({'message': 'No images specified'}), 200
        
    deleted_count = 0
    try:
        images = Image.query.filter(Image.id.in_(image_ids)).all()
        for image in images:
            project = Project.query.get(image.project_id)
            if project:
                image_path = os.path.join(project.root_path, image.filename)
                if os.path.exists(image_path):
                    os.remove(image_path)
                    
                name_no_ext = os.path.splitext(image.filename)[0]
                label_path = os.path.join(project.root_path, f"{name_no_ext}.txt")
                if os.path.exists(label_path):
                    os.remove(label_path)
            db.session.delete(image)
            deleted_count += 1
        db.session.commit()
        return jsonify({'message': f'Successfully deleted {deleted_count} images'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 400


@api_bp.route('/projects/scan/<int:project_id>', methods=['POST'])
def scan_project(project_id):
    project = Project.query.get_or_404(project_id)
    try:
        new_count = utils.scan_and_sync_images(project)
        utils.sync_dataset_tags(project)
        return jsonify({'message': f'Synced successfully. Added {new_count} new images.'})
    except Exception as e:
        print(f"Error scanning project {project_id}: {e}")
        return jsonify({'error': str(e)}), 500

# --- Uploads for Drag-and-Drop Project Creation ---
ALLOWED_UPLOAD_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.bmp', '.txt', '.yaml', '.yml', '.JPG', '.JPEG', '.PNG', '.BMP'}

@api_bp.route('/upload-folder', methods=['POST'])
def upload_folder():
    project_name = request.form.get('project_name', 'default_project')
    # Clean project name for a safe folder name
    safe_project_name = "".join([c for c in project_name if c.isalnum() or c in (' ', '_')]).strip()
    safe_project_name = safe_project_name.replace(' ', '_')
    if not safe_project_name:
        safe_project_name = 'default_project'
        
    upload_dir = os.path.abspath(os.path.join('uploads', safe_project_name, 'images'))
    os.makedirs(upload_dir, exist_ok=True)
    
    files = request.files.getlist('files')
    saved_count = 0
    for file in files:
        if file.filename:
            basename = os.path.basename(file.filename)
            ext = os.path.splitext(basename)[1].lower()
            if ext in {'.jpg', '.jpeg', '.png', '.bmp', '.txt', '.yaml', '.yml', '.json'}:
                dest_path = os.path.join(upload_dir, basename)
                file.save(dest_path)
                saved_count += 1
                
    return jsonify({
        'status': 'success',
        'absolute_path': upload_dir,
        'count': saved_count
    })

@api_bp.route('/projects/<int:project_id>/upload', methods=['POST'])
def upload_project_images(project_id):
    project = Project.query.get_or_404(project_id)
    files = request.files.getlist('files')
    skip_sync = request.form.get('skip_sync', 'false').lower() == 'true'
    
    saved_count = 0
    for file in files:
        if file.filename:
            basename = os.path.basename(file.filename)
            ext = os.path.splitext(basename)[1].lower()
            if ext in {'.jpg', '.jpeg', '.png', '.bmp', '.txt', '.yaml', '.yml', '.json', '.JPG', '.JPEG', '.PNG', '.BMP'}:
                dest_path = os.path.join(project.root_path, basename)
                file.save(dest_path)
                saved_count += 1
                
    if saved_count > 0 and not skip_sync:
        try:
            utils.scan_and_sync_images(project)
            utils.sync_dataset_tags(project)
        except Exception as scan_err:
            print(f"Error during auto-scanning in upload: {scan_err}")
            
    return jsonify({
        'status': 'success',
        'count': saved_count
    })

# --- Views ---
@api_bp.route('/views', methods=['POST'])
def create_view():
    data = request.json
    view_name = data['name']
    project_id = data['project_id']
    
    existing_view = View.query.filter_by(name=view_name, project_id=project_id).first()
    if existing_view:
        return jsonify(existing_view.to_dict()), 200
        
    new_view = View(name=view_name, project_id=project_id)
    db.session.add(new_view)
    db.session.commit()
    return jsonify(new_view.to_dict()), 201

@api_bp.route('/views/assign', methods=['POST'])
def assign_view():
    # Logic to assign images to a view
    # data: { view_id, count, strategy='random'|'sequential', assign_mode='both'|'labeled'|'unlabeled' ... }
    data = request.json
    count = utils.assign_images_to_view(
        data['view_id'], 
        data.get('count', 0), 
        data.get('project_id'),
        data.get('assign_mode', 'both')
    )
    if count == 0:
        return jsonify({'error': 'Lỗi: Tổng ảnh chưa phân công hiện tại là 0 hoặc không có ảnh nào phù hợp để phân công.'}), 400
    return jsonify({'message': f'Phân công thành công {count} ảnh.', 'assigned_count': count})

@api_bp.route('/views/<int:view_id>', methods=['DELETE'])
def delete_view(view_id):
    view = View.query.get_or_404(view_id)
    try:
        # Unassign all images belonging to this view
        images = Image.query.filter_by(view_id=view.id).all()
        for img in images:
            img.view_id = None
        
        db.session.delete(view)
        db.session.commit()
        return jsonify({'message': 'View deleted successfully'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 400

# --- Images & Labels ---
@api_bp.route('/images', methods=['GET'])
def get_images():
    project_id = request.args.get('project_id')
    view_id = request.args.get('view_id')
    flag_status = request.args.get('flag_status')
    is_labeled = request.args.get('is_labeled')
    
    query = Image.query
    if project_id:
        query = query.filter_by(project_id=project_id)
    if view_id:
        query = query.filter_by(view_id=view_id)
    if flag_status:
        query = query.filter_by(flag_status=flag_status)
    
    is_reviewed = request.args.get('is_reviewed')
    if is_reviewed is not None:
        if is_reviewed.lower() == 'true':
            query = query.filter_by(is_reviewed=True)
        elif is_reviewed.lower() == 'false':
            query = query.filter_by(is_reviewed=False)
    
    images = query.all()
    result = []
    
    projects_cache = {}
    db_changed = False
    
    for img in images:
        if img.project_id not in projects_cache:
            projects_cache[img.project_id] = Project.query.get(img.project_id)
        project = projects_cache[img.project_id]
        
        has_coords = False
        classes = []
        boxes = []
        if project:
            label_file = os.path.join(project.root_path, os.path.splitext(img.filename)[0] + '.txt')
            if os.path.exists(label_file):
                try:
                    with open(label_file, 'r', encoding='utf-8') as f:
                        for line in f:
                            parts = line.strip().split()
                            if len(parts) >= 5:
                                has_coords = True
                                try:
                                    classes.append(int(parts[0]))
                                    boxes.append({
                                        'class_id': int(parts[0]),
                                        'x_center': float(parts[1]),
                                        'y_center': float(parts[2]),
                                        'width': float(parts[3]),
                                        'height': float(parts[4])
                                    })
                                except ValueError:
                                    pass
                except Exception:
                    pass
                    
        # Sync DB column
        if img.is_labeled != has_coords:
            img.is_labeled = has_coords
            db_changed = True
            
        # Apply the is_labeled filter dynamically
        if is_labeled is not None:
            if is_labeled.lower() == 'true' and not has_coords:
                continue
            elif is_labeled.lower() == 'false' and has_coords:
                continue
                
        d = img.to_dict()
        d['classes'] = sorted(list(set(classes)))
        d['boxes'] = boxes
        result.append(d)
        
    if db_changed:
        db.session.commit()
        
    return jsonify(result)

@api_bp.route('/labels/<int:image_id>', methods=['GET'])
def get_label(image_id):
    image = Image.query.get_or_404(image_id)
    labels = utils.read_yolo_label(image)
    return jsonify(labels)

@api_bp.route('/images/batch-review', methods=['POST'])
def batch_review():
    data = request.json
    image_ids = data.get('image_ids', [])
    is_reviewed = data.get('is_reviewed', True)
    
    if not image_ids:
        return jsonify({'message': 'No images to update'}), 200
        
    db.session.query(Image).filter(Image.id.in_(image_ids)).update(
        {Image.is_reviewed: is_reviewed},
        synchronize_session=False
    )
    db.session.commit()
    
    return jsonify({'message': f'Successfully updated {len(image_ids)} images'})

@api_bp.route('/save', methods=['POST'])
def save_label():
    data = request.json
    # data: { image_id, labels: [...], flag_status, save_time }
    image = Image.query.get_or_404(data['image_id'])
    
    save_time = data.get('save_time', 0)
    project = Project.query.get(image.project_id)
    label_file = os.path.join(project.root_path, os.path.splitext(image.filename)[0] + '.txt')
    
    # Kiểm tra thời gian save mới nhất (check newest save time)
    if os.path.exists(label_file) and save_time > 0:
        file_mtime = os.path.getmtime(label_file) * 1000 # convert to ms
        if save_time < file_mtime:
            return jsonify({'message': 'Ignored older save. Another user saved newer data.', 'ignored': True}), 200

    # Clear tọa độ của bounding box trước đó (clear previous bounding box coordinates)
    if os.path.exists(label_file):
        open(label_file, 'w').close()
        
    # Gọi đến hàm save() để lưu tọa độ của bounding box mới nhất
    utils.save_yolo_label(image, data['labels'])
    
    image.is_labeled = len(data.get('labels', [])) > 0
    if 'flag_status' in data:
        image.flag_status = data['flag_status']
    if 'split_type' in data:
        image.split_type = data['split_type']
    if 'is_reviewed' in data:
        image.is_reviewed = data['is_reviewed']
    
    db.session.commit()
    return jsonify({'message': 'Saved successfully'})

@api_bp.route('/image_data/<int:image_id>')
def serve_image(image_id):
    image = Image.query.get_or_404(image_id)
    project = Project.query.get(image.project_id)
    # Check if absolute path
    return flask.send_from_directory(project.root_path, image.filename)

@api_bp.route('/projects/<int:project_id>/classes', methods=['GET', 'POST'])
def handle_project_classes(project_id):
    project = Project.query.get_or_404(project_id)
    classes = utils.get_classes(project)
    
    if request.method == 'POST':
        data = request.json
        new_class_name = data.get('name')
        if not new_class_name:
            return jsonify({'error': 'Class name is required'}), 400
        
        if new_class_name in classes:
            return jsonify({'error': 'Class already exists', 'class_id': classes.index(new_class_name)}), 400
        
        classes.append(new_class_name)
        utils.save_classes(project, classes)
        return jsonify({'message': 'Class added', 'class_id': len(classes) - 1, 'classes': classes}), 201

    return jsonify(classes)

@api_bp.route('/projects/<int:project_id>/class-examples', methods=['GET'])
def get_class_examples(project_id):
    project = Project.query.get_or_404(project_id)
    classes = utils.get_classes(project)
    
    labeled_images = Image.query.filter_by(project_id=project_id, is_labeled=True).all()
    examples = {}
    
    for img in labeled_images:
        labels = utils.read_yolo_label(img)
        for label in labels:
            cid = str(label['class_id'])
            if cid not in examples:
                examples[cid] = []
            
            if len(examples[cid]) < 10:
                examples[cid].append({
                    'filename': img.filename,
                    'image_id': img.id,
                    'bbox': [label['x'], label['y'], label['w'], label['h']]
                })
            
        # Optimization: break if all classes have at least 10 examples
        all_full = len(examples) == len(classes) and all(len(v) == 10 for v in examples.values())
        if all_full:
            break
            
    return jsonify({
        'classes': classes,
        'examples': examples
    })

@api_bp.route('/projects/<int:project_id>/classes/<int:class_idx>', methods=['DELETE'])
def delete_project_class(project_id, class_idx):
    import os
    project = Project.query.get_or_404(project_id)
    classes = utils.get_classes(project)
    
    if class_idx < 0 or class_idx >= len(classes):
        return jsonify({'error': 'Invalid class index'}), 400
    
    classes.pop(class_idx)
    utils.save_classes(project, classes)
    
    # Update all label files in the project to remove boxes with deleted class and shift indexes
    images = Image.query.filter_by(project_id=project.id).all()
    for image in images:
        label_file = os.path.join(project.root_path, os.path.splitext(image.filename)[0] + '.txt')
        if os.path.exists(label_file):
            with open(label_file, 'r') as f:
                lines = f.readlines()
            
            new_lines = []
            for line in lines:
                parts = line.strip().split()
                if not parts:
                    continue
                cid = int(parts[0])
                if cid == class_idx:
                    continue # Drop this box
                elif cid > class_idx:
                    cid -= 1 # Shift index down
                parts[0] = str(cid)
                new_lines.append(' '.join(parts))
            
            with open(label_file, 'w') as f:
                if new_lines:
                    f.write('\n'.join(new_lines) + '\n')
                    image.is_labeled = True
                else:
                    f.write('') # Clear file if no boxes left
                    image.is_labeled = False

    db.session.commit()
    return jsonify({'message': 'Class deleted', 'classes': classes}), 200

# --- Export ---
@api_bp.route('/export', methods=['POST'])
def export_dataset():
    data = request.json
    # Support multiple criteria types
    criteria = {}
    if 'project_ids' in data:
        criteria['project_ids'] = data['project_ids']
    if 'view_id' in data:
        criteria['view_id'] = data['view_id']
    if 'image_ids' in data:
        criteria['image_ids'] = data['image_ids']
    
    if 'tags' in data:
        criteria['tags'] = data['tags']
        
    if 'exclude_flagged' in data:
        criteria['exclude_flagged'] = data['exclude_flagged']
        
    if 'has_any_tag' in data:
        criteria['has_any_tag'] = data['has_any_tag']
        
    # Default to 'yolo' if not specified
    export_fmt = data.get('format', 'yolo')
    
    # Get splits or default
    splits = data.get('splits', {'train': 80, 'val': 20, 'test': 0})
        
    result = utils.export_dataset(criteria, splits=splits, format=export_fmt)
    return jsonify(result)

@api_bp.route('/autolabel/<int:image_id>', methods=['POST'])
def auto_label(image_id):
    image = Image.query.get_or_404(image_id)
    project = Project.query.get(image.project_id)
    
    # Construct full image path
    image_path = os.path.join(project.root_path, image.filename)
    
    engine = get_inference_engine()
    if not engine:
        return jsonify({'error': 'No active AI model found or model file missing.'}), 400
    
    region = None
    if request.is_json:
        data = request.get_json()
        if data and 'region' in data:
            region = data['region']

    result = engine.predict(image_path, region=region)
    
    if 'error' in result:
        return jsonify(result), 400
    
    # --- Classifier re-labeling ---
    # If a classifier is active, crop each detected box and re-classify
    classifier = get_classifier_engine()
    if classifier and result.get('success') and result.get('boxes'):
        import cv2, sys
        sys.stderr.write(f"[AutoLabel] Classifier ACTIVE - Re-classifying {len(result['boxes'])} boxes...\n")
        sys.stderr.flush()
        img = utils.imread_with_exif(image_path)
        if img is not None:
            img_h, img_w = img.shape[:2]
            
            for i, box in enumerate(result['boxes']):
                # Convert normalized center coords to pixel coords
                cx, cy, bw, bh = box['x'], box['y'], box['w'], box['h']
                xmin = int((cx - bw / 2) * img_w)
                ymin = int((cy - bh / 2) * img_h)
                xmax = int((cx + bw / 2) * img_w)
                ymax = int((cy + bh / 2) * img_h)
                
                # Clip to image boundaries
                xmin = max(0, xmin)
                ymin = max(0, ymin)
                xmax = min(img_w, xmax)
                ymax = min(img_h, ymax)
                
                if xmin >= xmax or ymin >= ymax:
                    continue
                
                crop = img[ymin:ymax, xmin:xmax]
                cls_result = classifier.predict(crop)
                
                if 'error' not in cls_result:
                    old_class_id = box['class_id']
                    predicted_name = cls_result.get('class_name')
                    project_classes = utils.get_classes(project)
                    if predicted_name in project_classes:
                        project_class_id = project_classes.index(predicted_name)
                    else:
                        project_classes_lower = [c.lower() for c in project_classes]
                        if predicted_name.lower() in project_classes_lower:
                            project_class_id = project_classes_lower.index(predicted_name.lower())
                        else:
                            project_classes.append(predicted_name)
                            utils.save_classes(project, project_classes)
                            project_class_id = len(project_classes) - 1
                    
                    box['class_id'] = project_class_id
                    box['cls_confidence'] = cls_result['confidence']
                    box['cls_class_name'] = predicted_name
                    sys.stderr.write(f"  Box {i}: YOLO class {old_class_id} -> Classifier: {predicted_name} ({cls_result['confidence']*100:.1f}%)\n")
            sys.stderr.flush()
        sys.stderr.write(f"[AutoLabel] Classifier done.\n")
        sys.stderr.flush()
    elif not classifier:
        import sys
        sys.stderr.write(f"[AutoLabel] No Classifier active - using YOLO classes only.\n")
        sys.stderr.flush()
        
    return jsonify(result)

@api_bp.route('/classify-boxes', methods=['POST'])
def classify_boxes():
    """Classify specific bounding boxes on an image using the active Classifier model."""
    import cv2
    import sys
    
    data = request.json
    if not data:
        return jsonify({'error': 'No data provided'}), 400
        
    image_id = data.get('image_id')
    boxes = data.get('boxes')  # list of {x, y, w, h} (YOLO format)
    
    if not image_id or not boxes:
        return jsonify({'error': 'image_id and boxes are required'}), 400
        
    classifier = get_classifier_engine()
    if not classifier:
        return jsonify({'error': 'Không có mô hình Classifier nào đang active.'}), 400
        
    image = Image.query.get_or_404(image_id)
    project = Project.query.get(image.project_id)
    image_path = os.path.join(project.root_path, image.filename)
    
    img = utils.imread_with_exif(image_path)
    if img is None:
        return jsonify({'error': f'Could not load image: {image_path}'}), 400
        
    img_h, img_w = img.shape[:2]
    results = []
    
    for i, box in enumerate(boxes):
        cx, cy, bw, bh = box['x'], box['y'], box['w'], box['h']
        xmin = int((cx - bw / 2) * img_w)
        ymin = int((cy - bh / 2) * img_h)
        xmax = int((cx + bw / 2) * img_w)
        ymax = int((cy + bh / 2) * img_h)
        
        # Clip to image boundaries
        xmin = max(0, xmin)
        ymin = max(0, ymin)
        xmax = min(img_w, xmax)
        ymax = min(img_h, ymax)
        
        if xmin >= xmax or ymin >= ymax:
            results.append({'error': 'Invalid bounds'})
            continue
            
        crop = img[ymin:ymax, xmin:xmax]
        cls_result = classifier.predict(crop)
        
        if 'error' not in cls_result:
            predicted_name = cls_result.get('class_name')
            project_classes = utils.get_classes(project)
            if predicted_name in project_classes:
                project_class_id = project_classes.index(predicted_name)
            else:
                project_classes_lower = [c.lower() for c in project_classes]
                if predicted_name.lower() in project_classes_lower:
                    project_class_id = project_classes_lower.index(predicted_name.lower())
                else:
                    project_classes.append(predicted_name)
                    utils.save_classes(project, project_classes)
                    project_class_id = len(project_classes) - 1
            
            cls_result['class_id'] = project_class_id
            
        results.append(cls_result)
        
    return jsonify({'success': True, 'results': results})

# ============================================================
# Crop & Collect for Classifier Retraining
# ============================================================

CROPS_DIR = os.path.join(os.getcwd(), 'classification_crops')

@api_bp.route('/collect-crop', methods=['POST'])
def collect_crop():
    """Crop a bounding box region from an image and save it for classifier retraining."""
    import cv2
    from datetime import datetime as dt
    
    data = request.json
    if not data:
        return jsonify({'error': 'No data provided'}), 400
    
    image_id = data.get('image_id')
    box = data.get('box')  # {x, y, w, h} in YOLO normalized format
    class_name = data.get('class_name', '').strip()
    
    if not image_id or not box or not class_name:
        return jsonify({'error': 'image_id, box, and class_name are required'}), 400
    
    image = Image.query.get_or_404(image_id)
    project = Project.query.get(image.project_id)
    image_path = os.path.join(project.root_path, image.filename)
    
    img = utils.imread_with_exif(image_path)
    if img is None:
        return jsonify({'error': f'Could not load image: {image_path}'}), 400
    
    img_h, img_w = img.shape[:2]
    
    # Convert YOLO normalized to pixel coords
    cx, cy, bw, bh = float(box['x']), float(box['y']), float(box['w']), float(box['h'])
    xmin = int(max(0, (cx - bw / 2) * img_w))
    ymin = int(max(0, (cy - bh / 2) * img_h))
    xmax = int(min(img_w, (cx + bw / 2) * img_w))
    ymax = int(min(img_h, (cy + bh / 2) * img_h))
    
    if xmin >= xmax or ymin >= ymax:
        return jsonify({'error': 'Invalid bounding box dimensions'}), 400
    
    crop = img[ymin:ymax, xmin:xmax]
    
    # Save to classification_crops/<class_name>/
    class_dir = os.path.join(CROPS_DIR, class_name)
    os.makedirs(class_dir, exist_ok=True)
    
    timestamp = dt.now().strftime('%Y%m%d_%H%M%S')
    # Use image filename stem + timestamp for uniqueness
    img_stem = os.path.splitext(image.filename)[0].replace('/', '_').replace('\\', '_')
    crop_filename = f"crop_{img_stem}_{timestamp}_{len(os.listdir(class_dir)):04d}.jpg"
    crop_path = os.path.join(class_dir, crop_filename)
    
    cv2.imwrite(crop_path, crop)
    
    # Count total crops for this class
    total_class = len([f for f in os.listdir(class_dir) if f.endswith(('.jpg', '.png', '.jpeg'))])
    
    return jsonify({
        'success': True,
        'class_name': class_name,
        'filename': crop_filename,
        'total_class_crops': total_class
    })

@api_bp.route('/collect-crop/batch', methods=['POST'])
def collect_crop_batch():
    """Crop all bounding boxes from an image and save them for classifier retraining."""
    import cv2
    from datetime import datetime as dt
    
    data = request.json
    if not data:
        return jsonify({'error': 'No data provided'}), 400
    
    image_id = data.get('image_id')
    boxes = data.get('boxes')  # [{class_name, x, y, w, h}, ...]
    
    if not image_id or not boxes:
        return jsonify({'error': 'image_id and boxes are required'}), 400
    
    image = Image.query.get_or_404(image_id)
    project = Project.query.get(image.project_id)
    image_path = os.path.join(project.root_path, image.filename)
    
    img = utils.imread_with_exif(image_path)
    if img is None:
        return jsonify({'error': f'Could not load image: {image_path}'}), 400
    
    img_h, img_w = img.shape[:2]
    timestamp = dt.now().strftime('%Y%m%d_%H%M%S')
    img_stem = os.path.splitext(image.filename)[0].replace('/', '_').replace('\\', '_')
    
    collected = 0
    for i, box in enumerate(boxes):
        class_name = box.get('class_name', '').strip()
        if not class_name:
            continue
        
        cx, cy, bw, bh = float(box['x']), float(box['y']), float(box['w']), float(box['h'])
        xmin = int(max(0, (cx - bw / 2) * img_w))
        ymin = int(max(0, (cy - bh / 2) * img_h))
        xmax = int(min(img_w, (cx + bw / 2) * img_w))
        ymax = int(min(img_h, (cy + bh / 2) * img_h))
        
        if xmin >= xmax or ymin >= ymax:
            continue
        
        crop = img[ymin:ymax, xmin:xmax]
        
        class_dir = os.path.join(CROPS_DIR, class_name)
        os.makedirs(class_dir, exist_ok=True)
        
        count = len(os.listdir(class_dir))
        crop_filename = f"crop_{img_stem}_{timestamp}_{count:04d}_box{i}.jpg"
        cv2.imwrite(os.path.join(class_dir, crop_filename), crop)
        collected += 1
    
    return jsonify({
        'success': True,
        'collected': collected,
        'total_boxes': len(boxes)
    })

@api_bp.route('/collect-crops/stats', methods=['GET'])
def collect_crops_stats():
    """Get statistics about collected crops."""
    stats = {}
    total = 0
    
    if os.path.exists(CROPS_DIR):
        for class_name in sorted(os.listdir(CROPS_DIR)):
            class_dir = os.path.join(CROPS_DIR, class_name)
            if os.path.isdir(class_dir):
                count = len([f for f in os.listdir(class_dir) if f.lower().endswith(('.jpg', '.png', '.jpeg'))])
                if count > 0:
                    stats[class_name] = count
                    total += count
    
    return jsonify({
        'stats': stats,
        'total': total,
        'crops_dir': CROPS_DIR
    })

@api_bp.route('/collect-crops/export', methods=['POST'])
def collect_crops_export():
    """Export collected crops as a zip file organized into train/val splits."""
    import zipfile
    import random
    import tempfile
    
    if not os.path.exists(CROPS_DIR):
        return jsonify({'error': 'No crops collected yet'}), 400
    
    data = request.json or {}
    val_ratio = data.get('val_ratio', 0.2)
    
    # Create zip in temp
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix='.zip', prefix='cls_crops_')
    tmp_path = tmp.name
    tmp.close()
    
    try:
        with zipfile.ZipFile(tmp_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            # Write class_mapping.json
            mapping_src = os.path.join(os.getcwd(), 'models', 'class_mapping.json')
            if os.path.exists(mapping_src):
                zf.write(mapping_src, 'class_mapping.json')
            
            for class_name in sorted(os.listdir(CROPS_DIR)):
                class_dir = os.path.join(CROPS_DIR, class_name)
                if not os.path.isdir(class_dir):
                    continue
                
                files = [f for f in os.listdir(class_dir) if f.lower().endswith(('.jpg', '.png', '.jpeg'))]
                if not files:
                    continue
                
                random.shuffle(files)
                split_idx = max(1, int(len(files) * (1 - val_ratio)))
                
                train_files = files[:split_idx]
                val_files = files[split_idx:]
                
                for f in train_files:
                    zf.write(os.path.join(class_dir, f), f'train/{class_name}/{f}')
                for f in val_files:
                    zf.write(os.path.join(class_dir, f), f'val/{class_name}/{f}')
        
        return flask.send_file(tmp_path, as_attachment=True, download_name='classification_crops.zip', mimetype='application/zip')
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@api_bp.route('/collect-crops/<class_name>', methods=['DELETE'])
def delete_collected_class(class_name):
    """Delete all collected crops for a specific class."""
    import shutil
    class_dir = os.path.join(CROPS_DIR, class_name)
    
    if not os.path.exists(class_dir):
        return jsonify({'error': f'Class "{class_name}" not found in collected crops'}), 404
    
    count = len([f for f in os.listdir(class_dir) if f.lower().endswith(('.jpg', '.png', '.jpeg'))])
    shutil.rmtree(class_dir)
    
    return jsonify({'success': True, 'deleted_count': count, 'class_name': class_name})

@api_bp.route('/collect-crops/preview/<class_name>', methods=['GET'])
def preview_collected_class(class_name):
    """Return a list of crop image paths for preview."""
    class_dir = os.path.join(CROPS_DIR, class_name)
    
    if not os.path.exists(class_dir):
        return jsonify({'error': f'Class "{class_name}" not found'}), 404
    
    files = sorted([f for f in os.listdir(class_dir) if f.lower().endswith(('.jpg', '.png', '.jpeg'))])
    
    # Return only last 50 for preview
    files = files[-50:]
    
    return jsonify({
        'class_name': class_name,
        'files': files,
        'total': len(os.listdir(class_dir))
    })

@api_bp.route('/collect-crops/serve/<class_name>/<filename>')
def serve_collected_crop(class_name, filename):
    """Serve a collected crop image."""
    class_dir = os.path.join(CROPS_DIR, class_name)
    return flask.send_from_directory(class_dir, filename)

@api_bp.route('/progress', methods=['GET'])
def get_progress():
    projects = Project.query.all()
    res = []
    for p in projects:
        p_data = p.to_dict()
        p_data['views'] = []
        
        total_images = Image.query.filter_by(project_id=p.id).count()
        labeled_images = Image.query.filter_by(project_id=p.id, is_labeled=True).count()
        p_data['total_images'] = total_images
        p_data['labeled_images'] = labeled_images
        
        # Unassigned progress
        unassigned_total = Image.query.filter_by(project_id=p.id, view_id=None).count()
        unassigned_labeled = Image.query.filter_by(project_id=p.id, view_id=None, is_labeled=True).count()
        p_data['unassigned'] = {
            'total_images': unassigned_total,
            'labeled_images': unassigned_labeled
        }
        
        views = View.query.filter_by(project_id=p.id).all()
        for v in views:
            v_dict = v.to_dict()
            v_total = Image.query.filter_by(view_id=v.id).count()
            v_labeled = Image.query.filter_by(view_id=v.id, is_labeled=True).count()
            v_dict['total_images'] = v_total
            v_dict['labeled_images'] = v_labeled
            p_data['views'].append(v_dict)
            
        res.append(p_data)
    return jsonify(res)

@api_bp.route('/projects/<int:project_id>/assign-stats', methods=['GET'])
def get_project_assign_stats(project_id):
    project = Project.query.get_or_404(project_id)
    
    # Labeled (With Bounding Box)
    labeled_total = Image.query.filter_by(project_id=project.id, is_labeled=True).count()
    unassigned_labeled = Image.query.filter_by(project_id=project.id, view_id=None, is_labeled=True).count()
    assigned_labeled = labeled_total - unassigned_labeled
    
    # Unlabeled (Without Bounding Box)
    unlabeled_total = Image.query.filter_by(project_id=project.id, is_labeled=False).count()
    unassigned_unlabeled = Image.query.filter_by(project_id=project.id, view_id=None, is_labeled=False).count()
    assigned_unlabeled = unlabeled_total - unassigned_unlabeled
    
    # Total
    total_images = labeled_total + unlabeled_total
    unassigned_total = unassigned_labeled + unassigned_unlabeled
    assigned_total = assigned_labeled + assigned_unlabeled
    
    return jsonify({
        'all': {'assigned': assigned_total, 'unassigned': unassigned_total},
        'labeled': {'assigned': assigned_labeled, 'unassigned': unassigned_labeled},
        'unlabeled': {'assigned': assigned_unlabeled, 'unassigned': unassigned_unlabeled}
    })

# --- AI Models ---
@api_bp.route('/models/files', methods=['GET'])
def get_model_files():
    models_dir = os.path.join(os.getcwd(), 'models')
    if not os.path.exists(models_dir):
        return jsonify([])
    
    files = [f for f in os.listdir(models_dir) if f.endswith('.onnx')]
    return jsonify(files)

@api_bp.route('/models', methods=['GET'])
def get_models():
    # Auto sync onnx files in models/ folder with database
    models_dir = os.path.join(os.getcwd(), 'models')
    if os.path.exists(models_dir):
        onnx_files = [f for f in os.listdir(models_dir) if f.endswith('.onnx')]
        db_changed = False
        for filename in onnx_files:
            existing = AIModel.query.filter_by(filename=filename).first()
            if not existing:
                name = os.path.splitext(filename)[0]
                if name.lower().startswith('yolo'):
                    name = 'YOLO' + name[4:]
                else:
                    name = name.capitalize()
                
                new_model = AIModel(
                    name=name,
                    filename=filename,
                    description=f"Auto-discovered model file {filename}",
                    is_active=False
                )
                db.session.add(new_model)
                db_changed = True
        
        if db_changed:
            try:
                db.session.commit()
            except Exception as e:
                db.session.rollback()
                print(f"Error auto-syncing models: {e}")
        
        # Ensure at least one model is active if models exist
        if AIModel.query.count() > 0:
            active_exists = AIModel.query.filter_by(is_active=True).first()
            if not active_exists:
                default_model = AIModel.query.filter_by(filename='yolo12s.onnx').first()
                if default_model:
                    default_model.is_active = True
                else:
                    first_model = AIModel.query.first()
                    if first_model:
                        first_model.is_active = True
                try:
                    db.session.commit()
                except Exception as e:
                    db.session.rollback()
                    print(f"Error setting active model: {e}")

    models = AIModel.query.order_by(AIModel.created_at.desc()).all()
    return jsonify([m.to_dict() for m in models])

@api_bp.route('/models', methods=['POST'])
def add_model():
    from werkzeug.utils import secure_filename
    try:
        name = request.form.get('name', '').strip()
        description = request.form.get('description', '').strip()
        model_type = request.form.get('model_type', 'detection').strip()
        
        if 'file' not in request.files:
            return jsonify({'error': 'Không tìm thấy file model tải lên.'}), 400
            
        file = request.files['file']
        if file.filename == '':
            return jsonify({'error': 'Vui lòng chọn file .onnx.'}), 400
            
        if not file.filename.endswith('.onnx'):
            return jsonify({'error': 'Định dạng file không hợp lệ. Chỉ chấp nhận file .onnx.'}), 400
            
        filename = secure_filename(file.filename)
        if not filename:
            filename = file.filename
            
        if not name:
            return jsonify({'error': 'Tên hiển thị không được để trống.'}), 400
            
        if AIModel.query.filter_by(filename=filename).first():
            return jsonify({'error': 'File model này đã tồn tại trong danh sách. Vui lòng chọn file khác hoặc sửa model hiện tại.'}), 400
            
        models_dir = os.path.join(os.getcwd(), 'models')
        os.makedirs(models_dir, exist_ok=True)
        file_path = os.path.join(models_dir, filename)
        file.save(file_path)
        
        # Also save class_mapping.json if uploaded (for classification models)
        mapping_file = request.files.get('mapping_file')
        if mapping_file and mapping_file.filename:
            mapping_path = os.path.join(models_dir, 'class_mapping.json')
            mapping_file.save(mapping_path)
        
        new_model = AIModel(
            name=name,
            description=description,
            filename=filename,
            model_type=model_type
        )
        # If it's the first model, make it active
        if AIModel.query.count() == 0:
            new_model.is_active = True
        db.session.add(new_model)
        db.session.commit()
        return jsonify(new_model.to_dict()), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'Database error: {str(e)}'}), 400

@api_bp.route('/models/<int:model_id>', methods=['PUT'])
def update_model(model_id):
    from werkzeug.utils import secure_filename
    m = AIModel.query.get_or_404(model_id)
    try:
        if request.is_json:
            data = request.json
            name = data.get('name', '').strip()
            description = data.get('description', '')
            filename_val = data.get('filename', '').strip()
            model_type = data.get('model_type', '').strip()
            file_uploaded = None
        else:
            name = request.form.get('name', '').strip()
            description = request.form.get('description', '')
            file_uploaded = request.files.get('file')
            filename_val = None
            model_type = request.form.get('model_type', '').strip()
            
            # Save class_mapping.json if uploaded
            mapping_file = request.files.get('mapping_file')
            if mapping_file and mapping_file.filename:
                models_dir = os.path.join(os.getcwd(), 'models')
                os.makedirs(models_dir, exist_ok=True)
                mapping_path = os.path.join(models_dir, 'class_mapping.json')
                mapping_file.save(mapping_path)
            
        if name:
            m.name = name
        if description is not None:
            m.description = description
        if model_type:
            m.model_type = model_type
            
        if file_uploaded:
            if not file_uploaded.filename.endswith('.onnx'):
                return jsonify({'error': 'Định dạng file không hợp lệ. Chỉ chấp nhận file .onnx.'}), 400
                
            filename = secure_filename(file_uploaded.filename)
            if not filename:
                filename = file_uploaded.filename
                
            # Check uniqueness excluding self
            existing = AIModel.query.filter(AIModel.filename == filename, AIModel.id != model_id).first()
            if existing:
                return jsonify({'error': 'File model này đã được gán cho một model khác trong danh sách.'}), 400
                
            models_dir = os.path.join(os.getcwd(), 'models')
            os.makedirs(models_dir, exist_ok=True)
            file_path = os.path.join(models_dir, filename)
            file_uploaded.save(file_path)
            
            m.filename = filename
        elif filename_val:
            existing = AIModel.query.filter(AIModel.filename == filename_val, AIModel.id != model_id).first()
            if existing:
                return jsonify({'error': 'File model này đã được gán cho một model khác trong danh sách.'}), 400
            m.filename = filename_val
            
        if not m.name or not m.filename:
            return jsonify({'error': 'Tên hiển thị và Tên File không được để trống.'}), 400
            
        db.session.commit()
        return jsonify(m.to_dict())
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'Database error: {str(e)}'}), 400

@api_bp.route('/models/<int:model_id>', methods=['DELETE'])
def delete_model(model_id):
    m = AIModel.query.get_or_404(model_id)
    try:
        was_active = m.is_active
        was_type = m.model_type
        db.session.delete(m)
        db.session.commit()
        if was_active:
            if was_type == 'classification':
                global classifier_engine
                classifier_engine = None
            else:
                global inference_engine
                inference_engine = None
        return jsonify({'message': 'Deleted'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 400

@api_bp.route('/models/<int:model_id>/activate', methods=['POST'])
def activate_model(model_id):
    m = AIModel.query.get_or_404(model_id)
    try:
        # Deactivate only models of the same type (detection OR classification)
        # This allows YOLO and Classifier to be active simultaneously
        AIModel.query.filter_by(model_type=m.model_type).update({AIModel.is_active: False})
        m.is_active = True
        db.session.commit()
        # Reset the appropriate engine
        if m.model_type == 'classification':
            global classifier_engine
            classifier_engine = None
        else:
            global inference_engine
            inference_engine = None
        return jsonify(m.to_dict())
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 400

@api_bp.route('/models/test', methods=['POST'])
def test_models():
    if 'image' not in request.files:
        return jsonify({'error': 'No image uploaded'}), 400
        
    image_file = request.files['image']
    model_ids = request.form.get('model_ids') # comma separated
    if not model_ids:
        return jsonify({'error': 'No models selected'}), 400
        
    import tempfile
    import uuid
    temp_dir = tempfile.gettempdir()
    temp_path = os.path.join(temp_dir, f"{uuid.uuid4().hex}_{image_file.filename}")
    image_file.save(temp_path)
    
    results = {}
    try:
        for mid in model_ids.split(','):
            if not mid.strip(): continue
            m = AIModel.query.get(int(mid.strip()))
            if m:
                m_path = os.path.join(os.getcwd(), 'models', m.filename)
                if os.path.exists(m_path):
                    try:
                        import time
                        engine = YOLOInference(m_path)
                        start_time = time.time()
                        pred = engine.predict(temp_path)
                        duration_ms = (time.time() - start_time) * 1000
                        
                        if pred.get('success') and 'boxes' in pred:
                            import cv2
                            img = utils.imread_with_exif(temp_path)
                            img_h, img_w = img.shape[:2]
                            
                            predictions = []
                            for box in pred['boxes']:
                                cx = box['x']
                                cy = box['y']
                                bw = box['w']
                                bh = box['h']
                                
                                x_min = int((cx - bw / 2) * img_w)
                                y_min = int((cy - bh / 2) * img_h)
                                x_max = int((cx + bw / 2) * img_w)
                                y_max = int((cy + bh / 2) * img_h)
                                
                                class_id = box['class_id']
                                class_name = engine.class_names.get(class_id, f"Class {class_id}")
                                
                                predictions.append({
                                    'bbox': [x_min, y_min, x_max, y_max],
                                    'class_name': class_name,
                                    'confidence': box['conf']
                                })
                            results[m.id] = {'success': True, 'predictions': predictions, 'time_ms': round(duration_ms, 2)}
                        else:
                            res_dict = dict(pred)
                            res_dict['time_ms'] = round(duration_ms, 2)
                            results[m.id] = res_dict
                    except Exception as e:
                        results[m.id] = {'error': str(e)}
                else:
                    results[m.id] = {'error': 'Model file not found'}
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)
            
    return jsonify(results)

# --- Tags ---
@api_bp.route('/projects/<int:project_id>/tags', methods=['GET'])
def get_tags(project_id):
    tags = Tag.query.filter_by(project_id=project_id).all()
    result = []
    for tag in tags:
        tag_dict = tag.to_dict()
        tag_dict['image_count'] = tag.images_list.count()
        result.append(tag_dict)
    return jsonify(result)

@api_bp.route('/projects/<int:project_id>/tags', methods=['POST'])
def create_tag(project_id):
    data = request.json
    name = data.get('name')
    color = data.get('color', '#3b82f6')
    if not name:
        return jsonify({'error': 'Name is required'}), 400
    
    existing = Tag.query.filter_by(project_id=project_id, name=name).first()
    if existing:
        return jsonify({'error': 'Tag already exists'}), 400
        
    tag = Tag(name=name, project_id=project_id, color=color)
    db.session.add(tag)
    db.session.commit()
    return jsonify(tag.to_dict()), 201

@api_bp.route('/tags/<int:tag_id>', methods=['PUT'])
def update_tag(tag_id):
    tag = Tag.query.get_or_404(tag_id)
    data = request.json
    if 'name' in data:
        existing = Tag.query.filter_by(project_id=tag.project_id, name=data['name']).first()
        if existing and existing.id != tag_id:
            return jsonify({'error': 'Tag name already exists'}), 400
        tag.name = data['name']
    if 'color' in data:
        tag.color = data['color']
        
    db.session.commit()
    return jsonify(tag.to_dict())

@api_bp.route('/tags/<int:tag_id>', methods=['DELETE'])
def delete_tag(tag_id):
    tag = Tag.query.get_or_404(tag_id)
    try:
        db.session.delete(tag)
        db.session.commit()
        return jsonify({'message': 'Tag deleted'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 400

@api_bp.route('/images/<int:image_id>/tags', methods=['POST'])
def set_image_tags(image_id):
    image = Image.query.get_or_404(image_id)
    data = request.json
    tag_ids = data.get('tag_ids', [])
    
    tags = Tag.query.filter(Tag.id.in_(tag_ids), Tag.project_id == image.project_id).all()
    image.tags = tags
    db.session.commit()
    
    return jsonify({'message': 'Tags updated', 'tags': [t.to_dict() for t in image.tags]})

@api_bp.route('/projects/<int:project_id>/images_paginated', methods=['GET'])
def get_images_paginated(project_id):
    Project.query.get_or_404(project_id)
    page = request.args.get('page', 1, type=int)
    limit = request.args.get('limit', 50, type=int)
    
    if limit > 200:
        limit = 200
        
    query = Image.query.filter_by(project_id=project_id)
    total = query.count()
    images = query.offset((page - 1) * limit).limit(limit).all()
    
    return jsonify({
        'total': total,
        'page': page,
        'limit': limit,
        'images': [img.to_dict() for img in images]
    })

@api_bp.route('/projects/<int:project_id>/bulk_assign_tags', methods=['POST'])
def bulk_assign_tags(project_id):
    Project.query.get_or_404(project_id)
    data = request.json
    image_ids = data.get('image_ids', []) # Can be "all" or list of ids
    tag_ids = data.get('tag_ids', [])
    action = data.get('action', 'assign') # assign, unassign, set
    
    tags = Tag.query.filter(Tag.id.in_(tag_ids), Tag.project_id == project_id).all()
    
    if image_ids == 'all':
        images = Image.query.filter_by(project_id=project_id).all()
    else:
        images = Image.query.filter(Image.id.in_(image_ids), Image.project_id == project_id).all()
        
    for image in images:
        if action == 'set':
            image.tags = list(tags)
        elif action == 'assign':
            for t in tags:
                if t not in image.tags:
                    image.tags.append(t)
        elif action == 'unassign':
            for t in tags:
                if t in image.tags:
                    image.tags.remove(t)
                    
    db.session.commit()
    return jsonify({'message': f'Bulk tags updated for {len(images)} images', 'success': True})
