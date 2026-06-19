# pyrefly: ignore [missing-import]
from flask import Blueprint, jsonify, request, current_app
# pyrefly: ignore [missing-import]
import flask
from models import db, Project, View, Image, AIModel
import os
import utils
from inference import YOLOInference

# Initialize Inference Engine
inference_engine = None

def get_inference_engine():
    global inference_engine
    if inference_engine is None:
        active_model = AIModel.query.filter_by(is_active=True).first()
        if active_model:
            model_path = os.path.join(os.getcwd(), 'models', active_model.filename)
            if os.path.exists(model_path):
                inference_engine = YOLOInference(model_path)
        else:
            # Fallback to default if no active model is set
            model_path = os.path.join(os.getcwd(), 'models', 'yolo12s.onnx')
            if os.path.exists(model_path):
                inference_engine = YOLOInference(model_path)
    return inference_engine


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

@api_bp.route('/projects/scan/<int:project_id>', methods=['POST'])
def scan_project(project_id):
    project = Project.query.get_or_404(project_id)
    added_count = utils.scan_and_sync_images(project)
    return jsonify({'message': f'Scanned and synced. Added {added_count} new images.'})

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
            if ext in {'.jpg', '.jpeg', '.png', '.bmp', '.txt', '.yaml', '.yml'}:
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
    saved_count = 0
    for file in files:
        if file.filename:
            basename = os.path.basename(file.filename)
            ext = os.path.splitext(basename)[1].lower()
            if ext in {'.jpg', '.jpeg', '.png', '.bmp', '.txt', '.yaml', '.yml', '.JPG', '.JPEG', '.PNG', '.BMP'}:
                dest_path = os.path.join(project.root_path, basename)
                file.save(dest_path)
                saved_count += 1
                
    if saved_count > 0:
        try:
            utils.scan_and_sync_images(project)
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
    if is_labeled is not None:
        if is_labeled.lower() == 'true':
            query = query.filter_by(is_labeled=True)
        elif is_labeled.lower() == 'false':
            query = query.filter_by(is_labeled=False)
    
    # Pagination could be added here
    images = query.all()
    result = []
    for img in images:
        d = img.to_dict()
        d['classes'] = utils.get_image_classes(img)
        result.append(d)
    return jsonify(result)

@api_bp.route('/labels/<int:image_id>', methods=['GET'])
def get_label(image_id):
    image = Image.query.get_or_404(image_id)
    labels = utils.read_yolo_label(image)
    return jsonify(labels)

@api_bp.route('/save', methods=['POST'])
def save_label():
    data = request.json
    # data: { image_id, labels: [...], flag_status }
    image = Image.query.get_or_404(data['image_id'])
    utils.save_yolo_label(image, data['labels'])
    
    image.is_labeled = True
    if 'flag_status' in data:
        image.flag_status = data['flag_status']
    if 'split_type' in data:
        image.split_type = data['split_type']
    
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
                else:
                    f.write('') # Clear file if no boxes left

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
    
    if 'exclude_flagged' in data:
        criteria['exclude_flagged'] = data['exclude_flagged']
        
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
    
    result = engine.predict(image_path)
    
    if 'error' in result:
        return jsonify(result), 400
        
    return jsonify(result)

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
        
        new_model = AIModel(
            name=name,
            description=description,
            filename=filename
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
            file_uploaded = None
        else:
            name = request.form.get('name', '').strip()
            description = request.form.get('description', '')
            file_uploaded = request.files.get('file')
            filename_val = None
            
        if name:
            m.name = name
        if description is not None:
            m.description = description
            
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
        db.session.delete(m)
        db.session.commit()
        if was_active:
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
        # Deactivate all
        AIModel.query.update({AIModel.is_active: False})
        m.is_active = True
        db.session.commit()
        # Reset inference engine
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
                            img = cv2.imread(temp_path)
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
