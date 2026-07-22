# pyrefly: ignore [missing-import]
from flask import Blueprint, jsonify, request, current_app
# pyrefly: ignore [missing-import]
import flask
from models import db, Project, View, Image, AIModel, Tag
import os
import re
import shutil
import contextlib
import csv
import io
import json
import random
import subprocess
import tempfile
import threading
import time
import uuid
import zipfile
try:
    from clear_header import validate_and_rename_yolo_dataset
except ModuleNotFoundError:
    from scripts.clear_header import validate_and_rename_yolo_dataset
from inference import YOLOInference, ClassificationInference

# Initialize Inference Engines
inference_engine = None
classifier_engine = None
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
GUIDE_STORAGE_DIR = os.path.join(BASE_DIR, 'project_guides')


def get_project_guide_path(project_id):
    return os.path.join(GUIDE_STORAGE_DIR, str(project_id), 'guide.pdf')


def get_project_guide_meta_path(project_id):
    return os.path.join(GUIDE_STORAGE_DIR, str(project_id), 'guide.json')


def normalize_deletable_directory(path):
    if not path or not os.path.isdir(path):
        return None

    normalized = os.path.abspath(path)
    parent_root = os.path.dirname(normalized)
    if not normalized or not parent_root or normalized == parent_root:
        raise ValueError(f'Unsafe project directory: {path}')

    return normalized


def move_directory_to_recycle_bin(path):
    normalized = normalize_deletable_directory(path)
    if not normalized:
        return False

    powershell_exe = shutil.which('powershell.exe') or shutil.which('powershell') or shutil.which('pwsh')
    if not powershell_exe:
        raise RuntimeError('PowerShell is not available to move the folder to Recycle Bin.')

    escaped_path = normalized.replace("'", "''")
    recycle_script = (
        "Add-Type -AssemblyName Microsoft.VisualBasic; "
        f"$target = '{escaped_path}'; "
        "if (-not (Test-Path -LiteralPath $target)) { exit 0 }; "
        "[Microsoft.VisualBasic.FileIO.FileSystem]::DeleteDirectory("
        "$target, "
        "[Microsoft.VisualBasic.FileIO.UIOption]::OnlyErrorDialogs, "
        "[Microsoft.VisualBasic.FileIO.RecycleOption]::SendToRecycleBin)"
    )

    result = subprocess.run(
        [powershell_exe, '-NoProfile', '-NonInteractive', '-Command', recycle_script],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        error_text = (result.stderr or result.stdout or '').strip()
        raise RuntimeError(error_text or 'Failed to move the project folder to Recycle Bin.')

    return True


def get_pdf_page_count(pdf_path):
    if not os.path.exists(pdf_path):
        return 0

    try:
        from pypdf import PdfReader
        return len(PdfReader(pdf_path).pages)
    except Exception:
        try:
            with open(pdf_path, 'rb') as f:
                content = f.read().decode('latin-1', errors='ignore')
            return len(re.findall(r'/Type\s*/Page\b', content))
        except Exception:
            return 0


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
@api_bp.route('/system/select-directory', methods=['POST'])
def select_directory():
    """Open a native folder picker and return the selected absolute path."""
    data = request.get_json(silent=True) or {}
    title = (data.get('title') or 'Chon thu muc').strip()
    initial_path = (data.get('initial_path') or '').strip()

    if not os.path.isdir(initial_path):
        initial_path = os.getcwd()

    root = None
    try:
        import tkinter as tk
        from tkinter import filedialog

        root = tk.Tk()
        root.withdraw()
        with contextlib.suppress(Exception):
            root.attributes('-topmost', True)
            root.lift()
            root.focus_force()

        selected_path = filedialog.askdirectory(
            parent=root,
            initialdir=initial_path,
            title=title,
            mustexist=False
        )
    except Exception as exc:
        return jsonify({'error': f'Cannot open folder picker: {exc}'}), 500
    finally:
        if root is not None:
            with contextlib.suppress(Exception):
                root.destroy()

    if not selected_path:
        return jsonify({'cancelled': True, 'path': ''})

    return jsonify({
        'cancelled': False,
        'path': os.path.abspath(selected_path)
    })

@api_bp.route('/projects', methods=['GET'])
def get_projects():
    projects = Project.query.all()
    return jsonify([p.to_dict() for p in projects])

@api_bp.route('/projects', methods=['POST'])
def create_project():
    data = request.json
    try:
        dataset_root = str(utils.find_dataset_root(data['root_path']))
        new_project = Project(
            name=data['name'],
            root_path=dataset_root
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
        if 'root_path' in data:
            new_root = str(utils.find_dataset_root(data['root_path']))
            if new_root != project.root_path:
                project.root_path = new_root
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
    data = request.get_json(silent=True) or {}
    delete_folder = data.get('delete_folder', False)
    project_root = project.root_path
    guide_path = get_project_guide_path(project.id)
    try:
        moved_to_recycle_bin = False
        if delete_folder:
            moved_to_recycle_bin = move_directory_to_recycle_bin(project_root)

        db.session.delete(project)
        db.session.commit()
        guide_dir = os.path.dirname(guide_path)
        if os.path.isdir(guide_dir):
            shutil.rmtree(guide_dir, ignore_errors=True)
        message = 'Project deleted successfully'
        if moved_to_recycle_bin:
            message = 'Project deleted successfully. The project folder was moved to Recycle Bin.'
        return jsonify({'message': message})
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 400



@api_bp.route('/projects/<int:project_id>/guide', methods=['GET', 'POST'])
def project_guide(project_id):
    Project.query.get_or_404(project_id)
    guide_path = get_project_guide_path(project_id)

    if request.method == 'GET':
        if not os.path.exists(guide_path):
            return jsonify({
                'exists': False,
                'filename': None,
                'page_count': 0
            })

        try:
            page_count = get_pdf_page_count(guide_path)
            meta_path = get_project_guide_meta_path(project_id)
            display_name = os.path.basename(guide_path)
            if os.path.exists(meta_path):
                try:
                    import json
                    with open(meta_path, 'r', encoding='utf-8') as f:
                        meta = json.load(f)
                    display_name = meta.get('filename') or display_name
                except Exception:
                    pass
            return jsonify({
                'exists': True,
                'filename': display_name,
                'page_count': page_count,
                'file_url': f'/api/projects/{project_id}/guide/file',
                'modified_at': os.path.getmtime(guide_path)
            })
        except Exception as e:
            return jsonify({'error': f'Cannot read guide file: {str(e)}'}), 400

    from werkzeug.utils import secure_filename

    file = request.files.get('file')
    if not file or not file.filename:
        return jsonify({'error': 'Vui lòng chọn file .pdf.'}), 400
    if not file.filename.lower().endswith('.pdf'):
        return jsonify({'error': 'Chỉ chấp nhận file .pdf.'}), 400

    guide_dir = os.path.dirname(guide_path)
    os.makedirs(guide_dir, exist_ok=True)

    try:
        file.save(guide_path)
        meta_path = get_project_guide_meta_path(project_id)
        import json
        with open(meta_path, 'w', encoding='utf-8') as f:
            json.dump({
                'filename': secure_filename(file.filename),
                'stored_filename': 'guide.pdf',
                'modified_at': datetime.utcnow().isoformat()
            }, f, ensure_ascii=False, indent=2)
        page_count = get_pdf_page_count(guide_path)
        return jsonify({
            'message': 'Guide uploaded successfully',
            'exists': True,
            'filename': secure_filename(file.filename),
            'page_count': page_count,
            'file_url': f'/api/projects/{project_id}/guide/file',
            'modified_at': os.path.getmtime(guide_path)
        }), 201
    except Exception as e:
        if os.path.exists(guide_path):
            try:
                os.remove(guide_path)
            except Exception:
                pass
        meta_path = get_project_guide_meta_path(project_id)
        if os.path.exists(meta_path):
            try:
                os.remove(meta_path)
            except Exception:
                pass
        return jsonify({'error': f'Cannot save guide file: {str(e)}'}), 400


@api_bp.route('/projects/<int:project_id>/guide/file', methods=['GET'])
def serve_project_guide_file(project_id):
    Project.query.get_or_404(project_id)
    guide_path = get_project_guide_path(project_id)
    if not os.path.exists(guide_path):
        return jsonify({'error': 'Guide file not found'}), 404

    return flask.send_file(
        guide_path,
        mimetype='application/pdf',
        as_attachment=False,
        download_name='guide.pdf'
    )

# --- Merge helper and endpoints at end of file (plan_project_merge_impl) ---

@api_bp.route('/images/<int:image_id>', methods=['DELETE'])
def delete_image(image_id):
    image = Image.query.get_or_404(image_id)
    project = Project.query.get(image.project_id)
    try:
        image_path = utils.resolve_image_path(project.root_path, image.filename)
        if os.path.exists(image_path):
            os.remove(image_path)

        label_path = utils.resolve_label_path(project.root_path, image.filename)
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
                image_path = utils.resolve_image_path(project.root_path, image.filename)
                if os.path.exists(image_path):
                    os.remove(image_path)

                label_path = utils.resolve_label_path(project.root_path, image.filename)
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
    has_any_tag = request.args.get('has_any_tag')

    query = Image.query
    if project_id:
        query = query.filter_by(project_id=project_id)
    if view_id:
        query = query.filter_by(view_id=view_id)
    if flag_status:
        query = query.filter_by(flag_status=flag_status)
    if has_any_tag is not None and has_any_tag.lower() in ('true', '1', 'yes'):
        query = query.filter(Image.tags.any())

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
            label_file = utils.resolve_label_path(project.root_path, img.filename)
            if os.path.exists(label_file):
                try:
                    with open(label_file, 'r', encoding='utf-8') as f:
                        for line in f:
                            parts = line.strip().split()
                            if len(parts) == 5:
                                try:
                                    class_id = int(parts[0])
                                    x_center = float(parts[1])
                                    y_center = float(parts[2])
                                    width = float(parts[3])
                                    height = float(parts[4])
                                    if width <= 0 or height <= 0:
                                        continue
                                    has_coords = True
                                    classes.append(class_id)
                                    boxes.append({
                                        'class_id': class_id,
                                        'x_center': x_center,
                                        'y_center': y_center,
                                        'width': width,
                                        'height': height
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
    label_file = utils.resolve_label_path(project.root_path, image.filename)
    import os
    os.makedirs(os.path.dirname(label_file), exist_ok=True)

    # Kiểm tra thời gian save mới nhất (check newest save time)
    if os.path.exists(label_file) and save_time > 0:
        file_mtime = os.path.getmtime(label_file) * 1000 # convert to ms
        if save_time < file_mtime:
            return jsonify({'message': 'Ignored older save. Another user saved newer data.', 'ignored': True}), 200

    # Clear tọa độ của bounding box trước đó (clear previous bounding box coordinates)
    if os.path.exists(label_file):
        open(label_file, 'w').close()

    # Gọi đến hàm save() để lưu tọa độ của bounding box mới nhất
    saved_count = utils.save_yolo_label(image, data['labels'])

    image.is_labeled = saved_count > 0
    if 'flag_status' in data:
        image.flag_status = data['flag_status']
    if 'split_type' in data:
        image.split_type = data['split_type']
    if 'is_reviewed' in data:
        image.is_reviewed = data['is_reviewed']

    db.session.commit()
    return jsonify({
        'message': 'Saved successfully',
        'saved_count': saved_count,
        'is_labeled': image.is_labeled
    })

@api_bp.route('/image_data/<int:image_id>')
def serve_image(image_id):
    image = Image.query.get_or_404(image_id)
    project = Project.query.get(image.project_id)
    # Check if absolute path
    real_img_path = utils.resolve_image_path(project.root_path, image.filename)
    return flask.send_file(real_img_path)

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
        label_file = utils.resolve_label_path(project.root_path, image.filename)
        if os.path.exists(label_file):
            with open(label_file, 'r') as f:
                lines = f.readlines()

            new_lines = []
            for line in lines:
                parts = line.strip().split()
                if len(parts) != 5:
                    continue
                try:
                    cid = int(parts[0])
                    float(parts[1])
                    float(parts[2])
                    width = float(parts[3])
                    height = float(parts[4])
                    if width <= 0 or height <= 0:
                        continue
                except ValueError:
                    continue
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

@api_bp.route('/projects/<int:project_id>/classes/merge', methods=['POST'])
def merge_project_classes(project_id):
    """Merge one or more classes into a single new class name.

    Expects JSON body:
        source_class_indices: list[int] – indices of classes to merge
        new_class_name: str – the target class name after merging
    """
    project = Project.query.get_or_404(project_id)
    data = request.get_json(silent=True) or {}
    source_indices = data.get('source_class_indices')
    new_name = (data.get('new_class_name') or '').strip()

    if not source_indices or not isinstance(source_indices, list):
        return jsonify({'error': 'source_class_indices is required (list of int)'}), 400
    if not new_name:
        return jsonify({'error': 'new_class_name is required'}), 400

    classes = utils.get_classes(project)

    # Validate indices
    for idx in source_indices:
        if not isinstance(idx, int) or idx < 0 or idx >= len(classes):
            return jsonify({'error': f'Invalid class index: {idx}'}), 400

    source_indices = sorted(set(source_indices))

    # Check name conflict with non-selected classes
    non_selected = [cls for i, cls in enumerate(classes) if i not in source_indices]
    if new_name in non_selected:
        return jsonify({'error': f'Class name "{new_name}" already exists in non-selected classes'}), 400

    # The target index is the smallest among selected
    target_idx = source_indices[0]
    indices_to_remove = source_indices[1:]  # all except the target

    # Build remap: source IDs → target_idx
    remap = {idx: target_idx for idx in source_indices}
    removed_classes = [classes[idx] for idx in indices_to_remove]

    # Phase 1: Remap class IDs in label files (merge selected → target)
    images = Image.query.filter_by(project_id=project.id).all()
    updated_files = 0
    updated_boxes = 0

    for image in images:
        label_file = utils.resolve_label_path(project.root_path, image.filename)
        if not os.path.exists(label_file):
            continue

        with open(label_file, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        new_lines = []
        file_changed = False
        for line in lines:
            parts = line.strip().split()
            if len(parts) != 5:
                continue
            try:
                cid = int(parts[0])
                float(parts[1])
                float(parts[2])
                width = float(parts[3])
                height = float(parts[4])
                if width <= 0 or height <= 0:
                    continue
            except ValueError:
                continue

            if cid in remap and cid != target_idx:
                parts[0] = str(target_idx)
                file_changed = True
                updated_boxes += 1
            new_lines.append(' '.join(parts))

        if file_changed:
            with open(label_file, 'w', encoding='utf-8') as f:
                if new_lines:
                    f.write('\n'.join(new_lines) + '\n')
                else:
                    f.write('')
            updated_files += 1

    # Phase 2: Remove extra classes and compact IDs in labels
    # Remove indices in reverse order so earlier indices stay valid
    classes[target_idx] = new_name
    for idx in reversed(indices_to_remove):
        classes.pop(idx)

    # Build compaction remap: old IDs → new IDs after removals
    # We need to adjust IDs in label files for the removed gaps
    old_to_new = {}
    new_id = 0
    for old_id in range(len(classes) + len(indices_to_remove)):
        if old_id in indices_to_remove:
            continue
        if old_id in remap:
            old_to_new[old_id] = old_to_new.get(target_idx, new_id)
            if old_id == target_idx:
                old_to_new[target_idx] = new_id
                new_id += 1
        else:
            old_to_new[old_id] = new_id
            new_id += 1

    # Phase 3: Compact class IDs in label files
    for image in images:
        label_file = utils.resolve_label_path(project.root_path, image.filename)
        if not os.path.exists(label_file):
            continue

        with open(label_file, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        new_lines = []
        file_changed = False
        for line in lines:
            parts = line.strip().split()
            if len(parts) != 5:
                continue
            try:
                cid = int(parts[0])
                float(parts[1])
                float(parts[2])
                width = float(parts[3])
                height = float(parts[4])
                if width <= 0 or height <= 0:
                    continue
            except ValueError:
                continue

            new_cid = old_to_new.get(cid, cid)
            if new_cid != cid:
                parts[0] = str(new_cid)
                file_changed = True
            new_lines.append(' '.join(parts))

        if file_changed:
            with open(label_file, 'w', encoding='utf-8') as f:
                if new_lines:
                    f.write('\n'.join(new_lines) + '\n')
                else:
                    f.write('')
                    image.is_labeled = False

    utils.save_classes(project, classes)
    db.session.commit()

    return jsonify({
        'message': 'Classes merged successfully',
        'classes': classes,
        'updated_files': updated_files,
        'updated_boxes': updated_boxes,
        'removed_classes': removed_classes
    }), 200

# --- Export ---
def run_clear_header_for_export(export_path):
    """Remove generated numeric prefixes from exported YOLO image/label pairs."""
    cleaned_splits = []
    split_layouts = [
        (split, os.path.join(export_path, 'images', split), os.path.join(export_path, 'labels', split))
        for split in ('train', 'val', 'test')
    ] + [
        (split, os.path.join(export_path, split, 'images'), os.path.join(export_path, split, 'labels'))
        for split in ('train', 'val', 'test')
    ]

    for split, image_path, label_path in split_layouts:
        if not os.path.isdir(image_path) or not os.path.isdir(label_path):
            continue

        with contextlib.redirect_stdout(io.StringIO()):
            validate_and_rename_yolo_dataset(image_path, label_path, dry_run=False)
        cleaned_splits.append(split)

    return cleaned_splits


@api_bp.route('/export', methods=['POST'])
def export_dataset():
    data = request.get_json(silent=True) or {}
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

    if 'include_untagged' in data:
        criteria['include_untagged'] = data['include_untagged']

    if 'include_unlabeled' in data:
        criteria['include_unlabeled'] = bool(data['include_unlabeled'])

    if 'tagged_split_assignments' in data:
        criteria['tagged_split_assignments'] = data['tagged_split_assignments']

    # Default to 'yolo' if not specified
    export_fmt = data.get('format', 'yolo')

    # Get splits or default
    splits = data.get('splits', {'train': 80, 'val': 20, 'test': 0})

    try:
        result = utils.export_dataset(criteria, splits=splits, format=export_fmt)
        status_code = 200 if result.get('status') == 'success' else 400
        if status_code == 200:
            result['clear_header_splits'] = run_clear_header_for_export(result['export_path'])
        return jsonify(result), status_code
    except PermissionError as exc:
        current_app.logger.exception('Export failed because the export directory is locked')
        return jsonify({
            'status': 'error',
            'message': (
                'Cannot prepare exported_dataset because it is being used by another process. '
                'Close File Explorer, terminal, archive tools, or any program currently opening that folder, then export again.'
            ),
            'detail': str(exc)
        }), 423
    except Exception as exc:
        current_app.logger.exception('Export failed')
        return jsonify({
            'status': 'error',
            'message': 'Export failed on the server. Please check the server log for details.',
            'detail': str(exc)
        }), 500

@api_bp.route('/autolabel/<int:image_id>', methods=['POST'])
def auto_label(image_id):
    image = Image.query.get_or_404(image_id)
    project = Project.query.get(image.project_id)

    # Construct full image path
    image_path = utils.resolve_image_path(project.root_path, image.filename)

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
                bounds = utils.yolo_box_to_pixel_bounds(box, img_w, img_h, padding_ratio=0.12, min_padding_px=6)
                crop = utils.crop_bgr_with_bounds(img, bounds)

                if crop is None:
                    continue

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
    image_path = utils.resolve_image_path(project.root_path, image.filename)

    img = utils.imread_with_exif(image_path)
    if img is None:
        return jsonify({'error': f'Could not load image: {image_path}'}), 400

    img_h, img_w = img.shape[:2]
    results = []

    for i, box in enumerate(boxes):
        bounds = utils.yolo_box_to_pixel_bounds(box, img_w, img_h, padding_ratio=0.12, min_padding_px=6)
        crop = utils.crop_bgr_with_bounds(img, bounds)

        if crop is None:
            results.append({'error': 'Invalid bounds'})
            continue

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
EXPORT_JOBS_DIR = os.path.join(os.getcwd(), 'exports', 'classification_jobs')
CROP_JOB_LOCK = threading.Lock()
CROP_JOBS = {}
CROP_IMAGE_EXTENSIONS = ('.jpg', '.jpeg', '.png')
CROP_ACTIVE_STATUSES = {'queued', 'running'}
EXPORT_JOB_LOCK = threading.Lock()
EXPORT_JOB_FILE_LOCK = threading.RLock()
EXPORT_JOBS = {}
EXPORT_ACTIVE_STATUSES = {'queued', 'running', 'cancelling'}


def sanitize_crop_class_name(class_name):
    safe = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', '_', str(class_name or '').strip())
    safe = safe.strip(' .')
    return safe or 'unknown'


def get_project_crops_dir(project_id):
    return os.path.join(CROPS_DIR, f'project_{project_id}')


def is_crop_image(filename):
    return filename.lower().endswith(CROP_IMAGE_EXTENSIONS)


def infer_crop_source_image(filename):
    name = os.path.splitext(filename)[0]
    if name.startswith('crop_'):
        name = name[5:]
    name = re.sub(r'_\d{8}_\d{6}.*$', '', name)
    name = re.sub(r'_box\d+.*$', '', name)
    name = re.sub(r'^\d+_', '', name)
    return name or ''


def iter_collected_crop_records():
    if not os.path.exists(CROPS_DIR):
        return

    try:
        crop_entries = sorted(os.listdir(CROPS_DIR))
    except OSError:
        return

    for entry in crop_entries:
        entry_path = os.path.join(CROPS_DIR, entry)
        if not os.path.isdir(entry_path):
            continue

        project_match = re.fullmatch(r'project_(\d+)', entry)
        if project_match:
            project_id = int(project_match.group(1))
            try:
                class_names = sorted(os.listdir(entry_path))
            except OSError:
                continue

            for class_name in class_names:
                class_dir = os.path.join(entry_path, class_name)
                if not os.path.isdir(class_dir):
                    continue
                try:
                    filenames = sorted(os.listdir(class_dir))
                except OSError:
                    continue

                for filename in filenames:
                    crop_path = os.path.join(class_dir, filename)
                    if is_crop_image(filename):
                        yield {
                            'project_id': project_id,
                            'class_name': class_name,
                            'filename': filename,
                            'path': crop_path,
                            'source_image': infer_crop_source_image(filename)
                        }
            continue

        # Legacy layout: classification_crops/<class_name>/<crop>.jpg
        try:
            filenames = sorted(os.listdir(entry_path))
        except OSError:
            continue

        for filename in filenames:
            crop_path = os.path.join(entry_path, filename)
            if is_crop_image(filename):
                yield {
                    'project_id': '',
                    'class_name': entry,
                    'filename': filename,
                    'path': crop_path,
                    'source_image': infer_crop_source_image(filename)
                }


def find_collected_crop_path(class_name, filename):
    for record in iter_collected_crop_records() or []:
        if record['class_name'] == class_name and record['filename'] == filename:
            return record['path']
    return None


def update_crop_job(job_id, **updates):
    with CROP_JOB_LOCK:
        job = CROP_JOBS.get(job_id)
        if not job:
            return
        job.update(updates)
        job['updated_at'] = datetime.utcnow().isoformat() + 'Z'


def get_active_crop_jobs():
    with CROP_JOB_LOCK:
        return [
            dict(job)
            for job in CROP_JOBS.values()
            if job.get('status') in CROP_ACTIVE_STATUSES
        ]


def update_export_job(job_id, **updates):
    with EXPORT_JOB_LOCK:
        job = EXPORT_JOBS.get(job_id)
    if not job:
        job = load_export_job_from_disk(job_id)
        if not job:
            return

    with EXPORT_JOB_LOCK:
        job.update(updates)
        job['updated_at'] = datetime.utcnow().isoformat() + 'Z'
        EXPORT_JOBS[job_id] = job
    persist_export_job(job)


def get_active_export_jobs():
    load_persisted_export_jobs()
    with EXPORT_JOB_LOCK:
        return [
            dict(job)
            for job in EXPORT_JOBS.values()
            if job.get('status') in EXPORT_ACTIVE_STATUSES
        ]


def get_export_job_dir(job_id):
    return os.path.join(EXPORT_JOBS_DIR, job_id)


def get_export_job_path(job_id):
    return os.path.join(get_export_job_dir(job_id), 'job.json')


def get_export_snapshot_path(job_id):
    return os.path.join(get_export_job_dir(job_id), 'snapshot_manifest.json')


def safe_export_job(job):
    safe = dict(job)
    safe.pop('file_path', None)
    safe.pop('partial_path', None)
    safe.pop('job_dir', None)
    safe.pop('snapshot_path', None)
    return safe


def persist_export_job(job, retries=8):
    job_snapshot = dict(job)
    job_dir = job.get('job_dir') or get_export_job_dir(job['job_id'])
    os.makedirs(job_dir, exist_ok=True)
    job_path = os.path.join(job_dir, 'job.json')
    last_error = None

    for attempt in range(retries):
        tmp_path = f"{job_path}.{os.getpid()}.{threading.get_ident()}.{uuid.uuid4().hex}.tmp"
        try:
            with EXPORT_JOB_FILE_LOCK:
                with open(tmp_path, 'w', encoding='utf-8') as f:
                    json.dump(job_snapshot, f, ensure_ascii=False, indent=2)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmp_path, job_path)
            return True
        except PermissionError as exc:
            last_error = exc
            try:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
            except OSError:
                pass
            time.sleep(0.05 * (attempt + 1))
        except OSError as exc:
            last_error = exc
            try:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
            except OSError:
                pass
            time.sleep(0.05 * (attempt + 1))

    raise last_error or OSError(f'Could not persist export job: {job_path}')


def load_export_job_from_disk(job_id):
    job_path = get_export_job_path(job_id)
    if not os.path.exists(job_path):
        return None
    try:
        with EXPORT_JOB_FILE_LOCK:
            with open(job_path, 'r', encoding='utf-8') as f:
                job = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None
    if job.get('status') in EXPORT_ACTIVE_STATUSES and job_id not in EXPORT_JOBS:
        job['status'] = 'failed'
        job['error'] = 'Export interrupted before completion. Please start export again.'
        job['message'] = 'Export interrupted'
        job['updated_at'] = datetime.utcnow().isoformat() + 'Z'
        persist_export_job(job)
    with EXPORT_JOB_LOCK:
        EXPORT_JOBS[job_id] = job
    return job


def load_persisted_export_jobs():
    if not os.path.isdir(EXPORT_JOBS_DIR):
        return
    for job_id in os.listdir(EXPORT_JOBS_DIR):
        if job_id in EXPORT_JOBS:
            continue
        load_export_job_from_disk(job_id)


def get_export_job(job_id):
    with EXPORT_JOB_LOCK:
        job = EXPORT_JOBS.get(job_id)
    if job:
        return job
    return load_export_job_from_disk(job_id)


def get_latest_export_job():
    load_persisted_export_jobs()
    with EXPORT_JOB_LOCK:
        jobs = list(EXPORT_JOBS.values())
    if not jobs:
        return None
    return max(jobs, key=lambda job: job.get('created_at', ''))


def estimate_records_size(records):
    total = 0
    missing = 0
    for record in records:
        try:
            total += os.path.getsize(record['path'])
        except OSError:
            missing += 1
    return total, missing


def write_export_snapshot(job_id, records):
    snapshot_path = get_export_snapshot_path(job_id)
    with open(snapshot_path, 'w', encoding='utf-8') as f:
        json.dump(records, f, ensure_ascii=False, indent=2)
    return snapshot_path


def crop_box_to_dir(img, img_w, img_h, box, class_dir, crop_filename):
    import cv2

    cx, cy, bw, bh = float(box['x']), float(box['y']), float(box['w']), float(box['h'])
    xmin = int(max(0, (cx - bw / 2) * img_w))
    ymin = int(max(0, (cy - bh / 2) * img_h))
    xmax = int(min(img_w, (cx + bw / 2) * img_w))
    ymax = int(min(img_h, (cy + bh / 2) * img_h))

    if xmin >= xmax or ymin >= ymax:
        return False

    crop = img[ymin:ymax, xmin:xmax]
    os.makedirs(class_dir, exist_ok=True)
    return bool(cv2.imwrite(os.path.join(class_dir, crop_filename), crop))


def build_classification_colab_code():
    return '''!pip install -U ultralytics

from google.colab import files
from ultralytics import YOLO
import pathlib
import zipfile

uploaded = files.upload()
zip_path = next(iter(uploaded))

extract_root = pathlib.Path("/content")
with zipfile.ZipFile(zip_path, "r") as z:
    z.extractall(extract_root)

dataset_root = extract_root / "classification_dataset"
print("Train:", dataset_root / "train")
print("Val:", dataset_root / "val")

model = YOLO("yolo11n-cls.pt")
results = model.train(
    data=str(dataset_root),
    epochs=50,
    imgsz=224,
    batch=32,
    patience=10,
    device=0
)

metrics = model.val(data=str(dataset_root))
print(metrics)
'''


def build_classification_crops_zip(records, tmp_path, val_ratio=0.2, progress_callback=None, cancel_check=None):
    grouped = {}
    for record in records:
        grouped.setdefault(record['class_name'], []).append(record)

    class_names = sorted(grouped.keys())
    class_mapping = {str(idx): class_name for idx, class_name in enumerate(class_names)}
    manifest_rows = []
    rng = random.Random(42)
    total_files = sum(len(items) for items in grouped.values())
    processed_files = 0
    written_files = 0
    skipped_files = 0
    skipped_rows = []

    with zipfile.ZipFile(tmp_path, 'w', compression=zipfile.ZIP_STORED, allowZip64=True) as zf:
        for class_name in class_names:
            if cancel_check and cancel_check():
                raise InterruptedError('Export cancelled')

            class_records = list(grouped[class_name])
            rng.shuffle(class_records)
            zf.writestr(f"classification_dataset/train/{class_name}/", '', compress_type=zipfile.ZIP_STORED)
            zf.writestr(f"classification_dataset/val/{class_name}/", '', compress_type=zipfile.ZIP_STORED)

            if len(class_records) <= 1:
                split_idx = len(class_records)
            else:
                split_idx = int(len(class_records) * (1 - val_ratio))
                split_idx = max(1, min(len(class_records) - 1, split_idx))

            for index, record in enumerate(class_records):
                processed_files += 1
                if progress_callback:
                    progress_callback(
                        processed_files=processed_files,
                        total_files=total_files,
                        written_files=written_files,
                        skipped_files=skipped_files,
                        current_file=record['filename'],
                        message=f"Exporting {record['filename']}"
                    )

                if cancel_check and cancel_check():
                    raise InterruptedError('Export cancelled')

                if not os.path.exists(record['path']):
                    skipped_files += 1
                    skipped_rows.append({
                        'project_id': record.get('project_id', ''),
                        'class_name': class_name,
                        'source_image': record.get('source_image', ''),
                        'crop_filename': record.get('filename', ''),
                        'reason': 'missing_file'
                    })
                    continue

                split = 'train' if index < split_idx else 'val'
                arcname = f"classification_dataset/{split}/{class_name}/{record['filename']}"
                try:
                    zf.write(record['path'], arcname, compress_type=zipfile.ZIP_STORED)
                    written_files += 1
                    manifest_rows.append({
                        'project_id': record['project_id'],
                        'class_name': class_name,
                        'source_image': record['source_image'],
                        'crop_filename': record['filename'],
                        'split': split
                    })
                except OSError as exc:
                    skipped_files += 1
                    skipped_rows.append({
                        'project_id': record.get('project_id', ''),
                        'class_name': class_name,
                        'source_image': record.get('source_image', ''),
                        'crop_filename': record.get('filename', ''),
                        'reason': str(exc)
                    })
                    continue

        zf.writestr(
            'classification_dataset/metadata/class_mapping.json',
            json.dumps(class_mapping, ensure_ascii=False, indent=2),
            compress_type=zipfile.ZIP_DEFLATED
        )

        manifest_buffer = io.StringIO()
        writer = csv.DictWriter(
            manifest_buffer,
            fieldnames=['project_id', 'class_name', 'source_image', 'crop_filename', 'split']
        )
        writer.writeheader()
        writer.writerows(manifest_rows)
        zf.writestr(
            'classification_dataset/metadata/manifest.csv',
            manifest_buffer.getvalue(),
            compress_type=zipfile.ZIP_DEFLATED
        )

        skipped_buffer = io.StringIO()
        skipped_writer = csv.DictWriter(
            skipped_buffer,
            fieldnames=['project_id', 'class_name', 'source_image', 'crop_filename', 'reason']
        )
        skipped_writer.writeheader()
        skipped_writer.writerows(skipped_rows)
        zf.writestr(
            'classification_dataset/metadata/skipped_files.csv',
            skipped_buffer.getvalue(),
            compress_type=zipfile.ZIP_DEFLATED
        )

        summary = {
            'total_files': total_files,
            'processed_files': processed_files,
            'written_files': written_files,
            'skipped_files': skipped_files,
            'class_count': len(class_names),
            'created_at': datetime.utcnow().isoformat() + 'Z',
            'format': 'ultralytics_classification'
        }
        zf.writestr(
            'classification_dataset/metadata/export_summary.json',
            json.dumps(summary, ensure_ascii=False, indent=2),
            compress_type=zipfile.ZIP_DEFLATED
        )
        zf.writestr(
            'classification_dataset/colab_train_classification.py',
            build_classification_colab_code(),
            compress_type=zipfile.ZIP_DEFLATED
        )

    return {
        'total_files': total_files,
        'processed_files': processed_files,
        'written_files': written_files,
        'skipped_files': skipped_files,
        'class_count': len(class_names)
    }


def run_export_crops_job(job_id, val_ratio):
    job = get_export_job(job_id)
    if not job:
        return

    snapshot_path = job.get('snapshot_path') or get_export_snapshot_path(job_id)
    partial_path = job.get('partial_path')
    final_path = job.get('file_path')
    last_progress_update = {'time': 0.0, 'processed_files': 0}

    def on_progress(**updates):
        now = time.monotonic()
        processed_files = int(updates.get('processed_files') or 0)
        total_files = int(updates.get('total_files') or 0)
        should_update = (
            processed_files >= total_files
            or processed_files - last_progress_update['processed_files'] >= 25
            or now - last_progress_update['time'] >= 0.5
        )
        if not should_update:
            return

        last_progress_update['time'] = now
        last_progress_update['processed_files'] = processed_files
        if partial_path and os.path.exists(partial_path):
            try:
                updates['file_size'] = os.path.getsize(partial_path)
            except OSError:
                pass
        update_export_job(job_id, **updates)

    def is_cancelled():
        current_job = get_export_job(job_id) or {}
        return bool(current_job.get('cancel_requested')) or current_job.get('status') == 'cancelling'

    try:
        with open(snapshot_path, 'r', encoding='utf-8') as f:
            records = json.load(f)

        update_export_job(
            job_id,
            status='running',
            total_files=len(records),
            processed_files=0,
            written_files=0,
            skipped_files=0,
            current_file='',
            message='Preparing export'
        )

        if is_cancelled():
            raise InterruptedError('Export cancelled')

        result = build_classification_crops_zip(records, partial_path, val_ratio, on_progress, is_cancelled)
        os.replace(partial_path, final_path)
        file_size = os.path.getsize(final_path) if os.path.exists(final_path) else 0
        update_export_job(
            job_id,
            status='completed',
            processed_files=result['processed_files'],
            total_files=result['total_files'],
            written_files=result['written_files'],
            skipped_files=result['skipped_files'],
            class_count=result['class_count'],
            current_file='',
            message='Completed',
            download_url=f'/api/collect-crops/export/jobs/{job_id}/download',
            partial_path=None,
            file_size=file_size
        )
    except InterruptedError as exc:
        if partial_path and os.path.exists(partial_path):
            try:
                os.remove(partial_path)
            except OSError:
                pass
        update_export_job(job_id, status='cancelled', current_file='', message='Cancelled', error=str(exc))
    except Exception as exc:
        if partial_path and os.path.exists(partial_path):
            try:
                os.remove(partial_path)
            except OSError:
                pass
        update_export_job(job_id, status='failed', error=str(exc), message='Export failed')


def run_collect_project_crops_job(app, job_id, project_id, reset_project=True):
    with app.app_context():
        try:
            project = Project.query.get(project_id)
            if not project:
                update_crop_job(job_id, status='failed', error='Project not found', message='Project not found')
                return

            images = Image.query.filter_by(project_id=project.id, is_labeled=True).order_by(Image.id.asc()).all()
            project_crop_dir = get_project_crops_dir(project.id)
            if reset_project and os.path.exists(project_crop_dir):
                shutil.rmtree(project_crop_dir)
            os.makedirs(project_crop_dir, exist_ok=True)

            classes = utils.get_classes(project)
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            collected = 0
            skipped = 0
            processed_boxes = 0
            per_class = {}

            update_crop_job(
                job_id,
                status='running',
                total_images=len(images),
                processed_images=0,
                message='Starting crop job'
            )

            for image_index, image in enumerate(images, start=1):
                update_crop_job(job_id, current_image=image.filename, message=f'Cropping {image.filename}')
                image_path = utils.resolve_image_path(project.root_path, image.filename)
                img = utils.imread_with_exif(image_path)
                if img is None:
                    skipped += 1
                    update_crop_job(
                        job_id,
                        processed_images=image_index,
                        skipped=skipped,
                        message=f'Skipped unreadable image: {image.filename}'
                    )
                    continue

                img_h, img_w = img.shape[:2]
                labels = utils.read_yolo_label(image)
                image_stem = os.path.splitext(image.filename)[0].replace('/', '_').replace('\\', '_')

                for box_index, label in enumerate(labels):
                    processed_boxes += 1
                    class_id = label.get('class_id')
                    if class_id is None or class_id < 0 or class_id >= len(classes):
                        skipped += 1
                        continue

                    class_name = sanitize_crop_class_name(classes[class_id])
                    class_dir = os.path.join(project_crop_dir, class_name)
                    crop_filename = f"crop_{image.id}_{image_stem}_{timestamp}_box{box_index:04d}.jpg"
                    try:
                        ok = crop_box_to_dir(img, img_w, img_h, label, class_dir, crop_filename)
                    except (KeyError, TypeError, ValueError):
                        ok = False

                    if ok:
                        collected += 1
                        per_class[class_name] = per_class.get(class_name, 0) + 1
                    else:
                        skipped += 1

                update_crop_job(
                    job_id,
                    processed_images=image_index,
                    processed_boxes=processed_boxes,
                    collected=collected,
                    skipped=skipped,
                    per_class=per_class
                )

            update_crop_job(
                job_id,
                status='completed',
                processed_images=len(images),
                current_image='',
                message='Completed',
                collected=collected,
                skipped=skipped,
                processed_boxes=processed_boxes,
                per_class=per_class
            )
        except Exception as exc:
            update_crop_job(job_id, status='failed', error=str(exc), message='Crop job failed')
        finally:
            db.session.remove()

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
    image_path = utils.resolve_image_path(project.root_path, image.filename)

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
    image_path = utils.resolve_image_path(project.root_path, image.filename)

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

@api_bp.route('/projects/<int:project_id>/collect-crops/jobs', methods=['POST'])
def start_collect_project_crops_job(project_id):
    """Start a background job to crop all labeled boxes for a project."""
    Project.query.get_or_404(project_id)
    data = request.json or {}
    reset_project = data.get('reset_project', True)
    job_id = uuid.uuid4().hex

    with CROP_JOB_LOCK:
        CROP_JOBS[job_id] = {
            'job_id': job_id,
            'status': 'queued',
            'project_id': project_id,
            'processed_images': 0,
            'total_images': 0,
            'processed_boxes': 0,
            'collected': 0,
            'skipped': 0,
            'current_image': '',
            'message': 'Queued',
            'error': None,
            'per_class': {},
            'created_at': datetime.utcnow().isoformat() + 'Z',
            'updated_at': datetime.utcnow().isoformat() + 'Z'
        }

    app = current_app._get_current_object()
    thread = threading.Thread(
        target=run_collect_project_crops_job,
        args=(app, job_id, project_id, bool(reset_project)),
        daemon=True
    )
    thread.start()

    return jsonify({'success': True, 'job_id': job_id})


@api_bp.route('/collect-crops/jobs/<job_id>', methods=['GET'])
def get_collect_crops_job(job_id):
    with CROP_JOB_LOCK:
        job = CROP_JOBS.get(job_id)
        if not job:
            return jsonify({'error': 'Job not found'}), 404
        return jsonify(dict(job))


@api_bp.route('/collect-crops/stats', methods=['GET'])
def collect_crops_stats():
    """Get statistics about collected crops."""
    stats = {}
    total = 0

    for record in iter_collected_crop_records() or []:
        class_name = record['class_name']
        stats[class_name] = stats.get(class_name, 0) + 1
        total += 1

    return jsonify({
        'stats': stats,
        'total': total,
        'crops_dir': CROPS_DIR
    })

@api_bp.route('/collect-crops/export', methods=['POST'])
@api_bp.route('/collect-crops/export/jobs', methods=['POST'])
def collect_crops_export():
    """Start a background export job for collected crops."""
    active_jobs = get_active_crop_jobs()
    if active_jobs:
        return jsonify({
            'error': 'Tiến trình crop ảnh vẫn đang chạy. Vui lòng đợi hoàn tất rồi export crops.',
            'active_jobs': active_jobs
        }), 409

    active_export_jobs = get_active_export_jobs()
    if active_export_jobs:
        return jsonify({
            'error': 'Tiến trình export crops vẫn đang chạy. Vui lòng đợi hoàn tất.',
            'active_jobs': active_export_jobs
        }), 409

    records = list(iter_collected_crop_records() or [])
    if not records:
        return jsonify({'error': 'No crops collected yet'}), 400

    data = request.json or {}
    val_ratio = float(data.get('val_ratio', 0.2))
    val_ratio = max(0.0, min(0.8, val_ratio))

    job_id = uuid.uuid4().hex
    job_dir = get_export_job_dir(job_id)
    os.makedirs(job_dir, exist_ok=True)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    partial_path = os.path.join(job_dir, f'classification_crops_{timestamp}.zip.part')
    final_path = os.path.join(job_dir, f'classification_crops_{timestamp}.zip')
    snapshot_path = write_export_snapshot(job_id, records)
    estimated_size, missing_at_snapshot = estimate_records_size(records)
    free_space = shutil.disk_usage(job_dir).free
    required_space = int(estimated_size * 1.05) + (100 * 1024 * 1024)
    if free_space < required_space:
        return jsonify({
            'error': 'Khong du dung luong trong de export crops.',
            'estimated_size': estimated_size,
            'required_space': required_space,
            'free_space': free_space
        }), 507

    job = {
        'job_id': job_id,
        'status': 'queued',
        'processed_files': 0,
        'total_files': len(records),
        'written_files': 0,
        'skipped_files': 0,
        'class_count': 0,
        'current_file': '',
        'message': 'Queued',
        'error': None,
        'download_url': None,
        'job_dir': job_dir,
        'snapshot_path': snapshot_path,
        'file_path': final_path,
        'partial_path': partial_path,
        'file_size': 0,
        'estimated_size': estimated_size,
        'missing_at_snapshot': missing_at_snapshot,
        'cancel_requested': False,
        'created_at': datetime.utcnow().isoformat() + 'Z',
        'updated_at': datetime.utcnow().isoformat() + 'Z'
    }

    with EXPORT_JOB_LOCK:
        EXPORT_JOBS[job_id] = job
    persist_export_job(job)

    thread = threading.Thread(
        target=run_export_crops_job,
        args=(job_id, val_ratio),
        daemon=True
    )
    thread.start()

    return jsonify({'success': True, 'job_id': job_id, 'total_files': len(records)})


@api_bp.route('/collect-crops/export/jobs/latest', methods=['GET'])
def get_latest_collect_crops_export_job():
    job = get_latest_export_job()
    if not job:
        return jsonify({'success': True, 'job': None})
    return jsonify({'success': True, 'job': safe_export_job(job)})


@api_bp.route('/collect-crops/export/jobs/<job_id>', methods=['GET'])
def get_collect_crops_export_job(job_id):
    job = get_export_job(job_id)
    if not job:
        return jsonify({'error': 'Export job not found'}), 404
    return jsonify(safe_export_job(job))


@api_bp.route('/collect-crops/export/jobs/<job_id>/download', methods=['GET'])
def download_collect_crops_export(job_id):
    job = get_export_job(job_id)
    if not job:
        return jsonify({'error': 'Export job not found'}), 404
    if job.get('status') != 'completed':
        return jsonify({'error': 'Export is not ready yet'}), 409
    file_path = job.get('file_path')

    if not file_path or not os.path.exists(file_path):
        return jsonify({'error': 'Export file is missing. Please run export again.'}), 404

    return flask.send_file(
        file_path,
        as_attachment=True,
        download_name='classification_crops.zip',
        mimetype='application/zip'
    )


@api_bp.route('/collect-crops/export/jobs/<job_id>', methods=['DELETE'])
def cancel_collect_crops_export_job(job_id):
    job = get_export_job(job_id)
    if not job:
        return jsonify({'error': 'Export job not found'}), 404
    if job.get('status') not in EXPORT_ACTIVE_STATUSES:
        return jsonify({'success': True, 'job': safe_export_job(job)})
    update_export_job(job_id, status='cancelling', cancel_requested=True, message='Cancelling export')
    updated = get_export_job(job_id)
    return jsonify({'success': True, 'job': safe_export_job(updated)})

@api_bp.route('/collect-crops/<class_name>', methods=['DELETE'])
def delete_collected_class(class_name):
    """Delete all collected crops for a specific class."""
    deleted_count = 0
    deleted_dirs = []

    legacy_dir = os.path.join(CROPS_DIR, class_name)
    if os.path.isdir(legacy_dir):
        deleted_count += len([f for f in os.listdir(legacy_dir) if is_crop_image(f)])
        shutil.rmtree(legacy_dir)
        deleted_dirs.append(legacy_dir)

    if os.path.exists(CROPS_DIR):
        for entry in os.listdir(CROPS_DIR):
            entry_path = os.path.join(CROPS_DIR, entry)
            if not re.fullmatch(r'project_\d+', entry) or not os.path.isdir(entry_path):
                continue
            project_class_dir = os.path.join(entry_path, class_name)
            if os.path.isdir(project_class_dir):
                deleted_count += len([f for f in os.listdir(project_class_dir) if is_crop_image(f)])
                shutil.rmtree(project_class_dir)
                deleted_dirs.append(project_class_dir)

    if not deleted_dirs:
        return jsonify({'error': f'Class "{class_name}" not found in collected crops'}), 404

    return jsonify({'success': True, 'deleted_count': deleted_count, 'class_name': class_name})

@api_bp.route('/collect-crops/preview/<class_name>', methods=['GET'])
def preview_collected_class(class_name):
    """Return a list of crop image paths for preview."""
    records = [record for record in (iter_collected_crop_records() or []) if record['class_name'] == class_name]

    if not records:
        return jsonify({'error': f'Class "{class_name}" not found'}), 404

    records.sort(key=lambda record: os.path.getmtime(record['path']))

    total = len(records)
    limit = request.args.get('limit', default=48, type=int) or 48
    page = request.args.get('page', default=1, type=int) or 1

    limit = max(1, min(limit, 200))
    total_pages = max(1, (total + limit - 1) // limit)
    page = max(1, min(page, total_pages))

    start_index = max(total - (page * limit), 0)
    end_index = total - ((page - 1) * limit)
    files = [record['filename'] for record in records[start_index:end_index]]

    return jsonify({
        'class_name': class_name,
        'files': files,
        'total': total,
        'page': page,
        'limit': limit,
        'total_pages': total_pages
    })

@api_bp.route('/collect-crops/serve/<class_name>/<filename>')
def serve_collected_crop(class_name, filename):
    """Serve a collected crop image."""
    crop_path = find_collected_crop_path(class_name, filename)
    if not crop_path:
        return jsonify({'error': 'Crop not found'}), 404
    return flask.send_from_directory(os.path.dirname(crop_path), os.path.basename(crop_path))

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
            v_tagged = Image.query.filter(
                Image.view_id == v.id,
                Image.tags.any()
            ).count()
            v_dict['total_images'] = v_total
            v_dict['labeled_images'] = v_labeled
            v_dict['tagged_images'] = v_tagged
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
        models_dir = os.path.join(os.getcwd(), 'models')
        model_path = os.path.join(models_dir, m.filename)
        remaining_classification_models = 0

        if was_type == 'classification':
            remaining_classification_models = AIModel.query.filter(
                AIModel.model_type == 'classification',
                AIModel.id != m.id
            ).count()

        if os.path.exists(model_path):
            os.remove(model_path)

        if was_type == 'classification' and remaining_classification_models == 0:
            mapping_path = os.path.join(models_dir, 'class_mapping.json')
            if os.path.exists(mapping_path):
                os.remove(mapping_path)

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
    conf_threshold = request.form.get('conf_threshold', default=0.25, type=float)
    iou_threshold = request.form.get('iou_threshold', default=0.45, type=float)
    if not model_ids:
        return jsonify({'error': 'No models selected'}), 400

    conf_threshold = min(max(conf_threshold, 0.0), 1.0)
    iou_threshold = min(max(iou_threshold, 0.0), 1.0)

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
                        pred = engine.predict(
                            temp_path,
                            conf_threshold=conf_threshold,
                            iou_threshold=iou_threshold
                        )
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
    project = Project.query.get_or_404(project_id)
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
    utils.persist_dataset_tags(project)
    return jsonify(tag.to_dict()), 201

@api_bp.route('/tags/<int:tag_id>', methods=['PUT'])
def update_tag(tag_id):
    tag = Tag.query.get_or_404(tag_id)
    project = Project.query.get_or_404(tag.project_id)
    data = request.json
    if 'name' in data:
        existing = Tag.query.filter_by(project_id=tag.project_id, name=data['name']).first()
        if existing and existing.id != tag_id:
            return jsonify({'error': 'Tag name already exists'}), 400
        tag.name = data['name']
    if 'color' in data:
        tag.color = data['color']

    db.session.commit()
    utils.persist_dataset_tags(project)
    return jsonify(tag.to_dict())

@api_bp.route('/tags/<int:tag_id>', methods=['DELETE'])
def delete_tag(tag_id):
    tag = Tag.query.get_or_404(tag_id)
    project = Project.query.get_or_404(tag.project_id)
    try:
        db.session.delete(tag)
        db.session.commit()
        utils.persist_dataset_tags(project)
        return jsonify({'message': 'Tag deleted'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 400

@api_bp.route('/images/<int:image_id>/tags', methods=['POST'])
def set_image_tags(image_id):
    image = Image.query.get_or_404(image_id)
    project = Project.query.get_or_404(image.project_id)
    data = request.json
    tag_ids = data.get('tag_ids', [])

    tags = Tag.query.filter(Tag.id.in_(tag_ids), Tag.project_id == image.project_id).all()
    image.tags = tags
    db.session.commit()
    utils.persist_dataset_tags(project)

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
    project = Project.query.get_or_404(project_id)
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
    utils.persist_dataset_tags(project)
    return jsonify({'message': f'Bulk tags updated for {len(images)} images', 'success': True})

# --- Backup ---
@api_bp.route('/projects/<int:project_id>/backup', methods=['POST'])
def backup_project(project_id):
    import shutil, zipfile
    from datetime import datetime
    project = Project.query.get_or_404(project_id)
    backup_dir = os.path.join(os.getcwd(), 'project_backup')
    os.makedirs(backup_dir, exist_ok=True)

    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    backup_filename = f"backup_{project.id}_{project.name}_{timestamp}.zip"
    backup_path = os.path.join(backup_dir, backup_filename)

    try:
        if os.path.exists(project.root_path):
            with zipfile.ZipFile(backup_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                for root, dirs, files in os.walk(project.root_path):
                    for file in files:
                        file_path = os.path.join(root, file)
                        arcname = os.path.relpath(file_path, project.root_path)
                        zipf.write(file_path, arcname)
            return jsonify({'message': 'Backup successful', 'backup_file': backup_filename}), 200
        else:
            return jsonify({'error': 'Project folder not found'}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@api_bp.route('/projects/<int:project_id>/backups', methods=['GET'])
def get_project_backups(project_id):
    project = Project.query.get_or_404(project_id)
    backup_dir = os.path.join(os.getcwd(), 'project_backup')

    if not os.path.exists(backup_dir):
        return jsonify([])

    backups = []
    prefix = f"backup_{project.id}_"
    for file in os.listdir(backup_dir):
        if file.startswith(prefix) and file.endswith('.zip'):
            file_path = os.path.join(backup_dir, file)
            size = os.path.getsize(file_path)
            created_at = os.path.getctime(file_path)
            backups.append({
                'filename': file,
                'size': size,
                'created_at': created_at
            })

    # Sort by created_at descending
    backups.sort(key=lambda x: x['created_at'], reverse=True)
    return jsonify(backups)

@api_bp.route('/projects/<int:project_id>/restore', methods=['POST'])
def restore_project(project_id):
    import shutil, zipfile
    project = Project.query.get_or_404(project_id)
    data = request.json
    filename = data.get('filename')

    if not filename:
        return jsonify({'error': 'Filename is required'}), 400

    backup_path = os.path.join(os.getcwd(), 'project_backup', filename)

    if not os.path.exists(backup_path):
        return jsonify({'error': 'Backup file not found'}), 404

    try:
        if os.path.exists(project.root_path):
            shutil.rmtree(project.root_path)
        os.makedirs(project.root_path, exist_ok=True)

        with zipfile.ZipFile(backup_path, 'r') as zipf:
            zipf.extractall(project.root_path)

        try:
            utils.scan_and_sync_images(project)
            utils.sync_dataset_tags(project)
        except Exception as scan_err:
            print(f"Error during auto-scanning in restore: {scan_err}")

        return jsonify({'message': 'Restore successful'}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500


def plan_project_merge_impl(project_ids, name, root_path, collision_policy):
    # Validations
    if not project_ids or len(project_ids) < 2:
        raise ValueError("At least two source projects are required.")
    if not name or not name.strip():
        raise ValueError("Merged project name is required.")
    if not root_path or not root_path.strip():
        raise ValueError("Destination folder path is required.")

    allowed_policies = {'rename', 'skip', 'overwrite'}
    if collision_policy not in allowed_policies:
        raise ValueError(f"Invalid collision policy: {collision_policy}")

    # Load projects
    projects = []
    for pid in project_ids:
        p = Project.query.get(pid)
        if not p:
            raise ValueError(f"Project with ID {pid} does not exist.")
        projects.append(p)

    # Build merged class list and class mappings
    merged_classes = []
    class_map = {} # project_id -> { old_class_id: new_class_id }
    for p in projects:
        class_map[p.id] = {}
        p_classes = utils.get_classes(p)
        for old_idx, cls_name in enumerate(p_classes):
            if cls_name not in merged_classes:
                merged_classes.append(cls_name)
            new_idx = merged_classes.index(cls_name)
            class_map[p.id][old_idx] = new_idx

    # Get all source images in deterministic order
    # Order: by the order in project_ids list, then by image.id
    project_order = {pid: idx for idx, pid in enumerate(project_ids)}
    all_source_images = Image.query.filter(Image.project_id.in_(project_ids)).all()
    all_source_images.sort(key=lambda img: (project_order.get(img.project_id, 999), img.id))

    # Group images by lowercase basename to identify collisions
    by_name = {}
    for img in all_source_images:
        import pathlib
        norm_name = pathlib.Path(img.filename).name.lower()
        if norm_name not in by_name:
            by_name[norm_name] = []
        by_name[norm_name].append(img)

    plans = []
    renamed_file_count = 0
    skipped_file_count = 0
    overwritten_file_count = 0
    duplicate_groups = []
    missing_files = []
    warnings = []

    planned_dest_names = set()

    def get_unique_dest_name(filename, project_id, planned_set):
        base, ext = os.path.splitext(filename)
        candidate = f"{base}_proj{project_id}{ext}"
        if candidate.lower() not in planned_set:
            return candidate
        counter = 1
        while f"{base}_proj{project_id}_{counter}{ext}".lower() in planned_set:
            counter += 1
        return f"{base}_proj{project_id}_{counter}{ext}"

    for norm_name, img_list in by_name.items():
        # First check duplicate groups
        if len(img_list) > 1:
            duplicate_groups.append({
                'filename': norm_name,
                'occurrences': [
                    {
                        'project_id': img.project_id,
                        'project_name': Project.query.get(img.project_id).name,
                        'image_id': img.id
                    }
                    for img in img_list
                ]
            })

        import pathlib
        # Process each image / collision
        if len(img_list) == 1:
            img = img_list[0]
            src_project = Project.query.get(img.project_id)
            src_path = utils.resolve_image_path(src_project.root_path, img.filename)
            if not os.path.exists(src_path):
                missing_files.append({
                    'project_id': img.project_id,
                    'project_name': src_project.name,
                    'filename': img.filename
                })

            dest_fn = f"{img.project_id}_{img.id}_{pathlib.Path(img.filename).name}"
            plans.append({
                'action': 'copy',
                'image': img,
                'dest_filename': dest_fn,
                'source_path': src_path,
                'project_id': img.project_id
            })
            planned_dest_names.add(dest_fn.lower())
        else:
            first_img = img_list[0]
            # Collect missing files for all duplicates
            for img in img_list:
                src_proj = Project.query.get(img.project_id)
                src_p = utils.resolve_image_path(src_proj.root_path, img.filename)
                if not os.path.exists(src_p):
                    missing_files.append({
                        'project_id': img.project_id,
                        'project_name': src_proj.name,
                        'filename': img.filename
                    })

            if collision_policy == 'rename':
                # All ones copied with unique names (which they natively have now)
                for img in img_list:
                    src_proj = Project.query.get(img.project_id)
                    dest_fn = f"{img.project_id}_{img.id}_{pathlib.Path(img.filename).name}"
                    if img != first_img:
                        renamed_file_count += 1
                    plans.append({
                        'action': 'copy',
                        'image': img,
                        'dest_filename': dest_fn,
                        'source_path': utils.resolve_image_path(src_proj.root_path, img.filename),
                        'project_id': img.project_id
                    })
                    planned_dest_names.add(dest_fn.lower())

            elif collision_policy == 'skip':
                # First one copied
                src_proj = Project.query.get(first_img.project_id)
                dest_fn = f"{first_img.project_id}_{first_img.id}_{pathlib.Path(first_img.filename).name}"
                plans.append({
                    'action': 'copy',
                    'image': first_img,
                    'dest_filename': dest_fn,
                    'source_path': utils.resolve_image_path(src_proj.root_path, first_img.filename),
                    'project_id': first_img.project_id
                })
                planned_dest_names.add(dest_fn.lower())

                # Others skipped
                for img in img_list[1:]:
                    skipped_file_count += 1
                    plans.append({
                        'action': 'skip',
                        'image': img,
                        'project_id': img.project_id
                    })

            elif collision_policy == 'overwrite':
                # First ones ignored (overwritten)
                for img in img_list[:-1]:
                    overwritten_file_count += 1
                    plans.append({
                        'action': 'overwrite_ignored',
                        'image': img,
                        'project_id': img.project_id
                    })
                # Last one copied
                last_img = img_list[-1]
                src_proj = Project.query.get(last_img.project_id)
                dest_fn = f"{last_img.project_id}_{last_img.id}_{pathlib.Path(last_img.filename).name}"
                plans.append({
                    'action': 'copy',
                    'image': last_img,
                    'dest_filename': dest_fn,
                    'source_path': utils.resolve_image_path(src_proj.root_path, last_img.filename),
                    'project_id': last_img.project_id
                })
                planned_dest_names.add(dest_fn.lower())

    # Warnings
    if os.path.exists(root_path):
        try:
            if os.listdir(root_path):
                warnings.append("Thư mục đích đã tồn tại và không trống. Các file trùng có thể bị ghi đè.")
        except Exception:
            pass

    # Calculate final image count
    final_image_count = sum(1 for p in plans if p['action'] == 'copy')
    total_images = len(all_source_images)
    label_file_count = sum(1 for p in plans if p['action'] == 'copy' and p['image'].is_labeled)

    return {
        'source_project_count': len(projects),
        'total_images': total_images,
        'missing_files': missing_files,
        'merged_classes': merged_classes,
        'class_map': class_map,
        'label_file_count': label_file_count,
        'renamed_file_count': renamed_file_count,
        'skipped_file_count': skipped_file_count,
        'overwritten_file_count': overwritten_file_count,
        'final_image_count': final_image_count,
        'duplicate_groups': duplicate_groups,
        'warnings': warnings,
        'plans': plans,
        'can_merge': len(projects) >= 2 and final_image_count > 0
    }


@api_bp.route('/projects/merge/preflight', methods=['POST'])
def merge_projects_preflight():
    data = request.json or {}
    project_ids = data.get('project_ids', [])
    name = data.get('name', '')
    root_path = data.get('root_path', '')
    collision_policy = data.get('collision_policy', 'rename')

    try:
        plan = plan_project_merge_impl(project_ids, name, root_path, collision_policy)
        res = {
            'source_project_count': plan['source_project_count'],
            'total_images': plan['total_images'],
            'missing_files': plan['missing_files'],
            'merged_classes': plan['merged_classes'],
            'label_file_count': plan['label_file_count'],
            'renamed_file_count': plan['renamed_file_count'],
            'skipped_file_count': plan['skipped_file_count'],
            'overwritten_file_count': plan['overwritten_file_count'],
            'final_image_count': plan['final_image_count'],
            'duplicate_groups': plan['duplicate_groups'],
            'warnings': plan['warnings'],
            'can_merge': plan['can_merge'],
            'collision_policy': collision_policy
        }
        return jsonify(res)
    except ValueError as ve:
        return jsonify({'error': str(ve)}), 400
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@api_bp.route('/projects/merge', methods=['POST'])
def merge_projects():
    data = request.json or {}
    project_ids = data.get('project_ids', [])
    name = data.get('name', '')
    root_path = data.get('root_path', '')
    collision_policy = data.get('collision_policy', 'rename')

    try:
        plan = plan_project_merge_impl(project_ids, name, root_path, collision_policy)
        if not plan['can_merge']:
            return jsonify({'error': 'Cannot execute merge with the given input.'}), 400
    except ValueError as ve:
        return jsonify({'error': str(ve)}), 400
    except Exception as e:
        return jsonify({'error': str(e)}), 500

    dest_path = os.path.abspath(root_path)

    created_dir = False
    copied_files = []

    if not os.path.exists(dest_path):
        try:
            os.makedirs(dest_path, exist_ok=True)
            created_dir = True
        except Exception as e:
            return jsonify({'error': f"Failed to create destination folder: {str(e)}"}), 500

    try:
        # Create DB project
        new_project = Project(
            name=name,
            root_path=dest_path
        )
        db.session.add(new_project)
        db.session.flush()

        # Copy tags
        new_tags_by_name = {}
        for p_item in plan['plans']:
            if p_item['action'] != 'copy':
                continue
            img = p_item['image']
            for tag in img.tags:
                if tag.name not in new_tags_by_name:
                    new_tag = Tag(name=tag.name, color=tag.color, project_id=new_project.id)
                    db.session.add(new_tag)
                    new_tags_by_name[tag.name] = new_tag
        db.session.flush()

        # Copy files and labels
        for p_item in plan['plans']:
            if p_item['action'] != 'copy':
                continue

            img = p_item['image']
            dest_fn = p_item['dest_filename']
            source_img_path = p_item['source_path']
            dest_img_path = utils.resolve_image_path(dest_path, dest_fn)

            # Copy Image File
            if os.path.exists(source_img_path):
                import pathlib
                pathlib.Path(dest_img_path).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy(source_img_path, dest_img_path)
                copied_files.append(dest_img_path)

            # Copy and remap label file
            src_proj = Project.query.get(p_item['project_id'])
            source_lbl_path = utils.resolve_label_path(src_proj.root_path, img.filename)
            dest_lbl_path = utils.resolve_label_path(dest_path, dest_fn)
            is_labeled = False

            if os.path.exists(source_lbl_path):
                labels = []
                with open(source_lbl_path, 'r', encoding='utf-8') as f:
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

                                new_class_id = plan['class_map'][img.project_id].get(class_id)
                                if new_class_id is not None:
                                    labels.append({
                                        'class_id': new_class_id,
                                        'x': x,
                                        'y': y,
                                        'w': w,
                                        'h': h
                                    })
                            except ValueError:
                                pass
                if labels:
                    import pathlib
                    pathlib.Path(dest_lbl_path).parent.mkdir(parents=True, exist_ok=True)
                    with open(dest_lbl_path, 'w', encoding='utf-8') as f:
                        for lbl in labels:
                            f.write(f"{lbl['class_id']} {lbl['x']} {lbl['y']} {lbl['w']} {lbl['h']}\n")
                    copied_files.append(dest_lbl_path)
                    is_labeled = True

            # Insert Image row
            new_img = Image(
                filename=dest_fn,
                project_id=new_project.id,
                is_labeled=is_labeled,
                is_reviewed=img.is_reviewed,
                flag_status=img.flag_status,
                split_type=img.split_type
            )
            db.session.add(new_img)

            # Associate tags
            for tag in img.tags:
                new_img.tags.append(new_tags_by_name[tag.name])

        # Save merged classes and data.yaml
        utils.save_classes(new_project, plan['merged_classes'])
        copied_files.append(os.path.join(dest_path, 'classes.txt'))
        for yaml_name in ['data.yaml', 'data.yml']:
            yaml_path = os.path.join(dest_path, yaml_name)
            if os.path.exists(yaml_path):
                copied_files.append(yaml_path)

        db.session.commit()

        return jsonify({
            'project': new_project.to_dict(),
            'copied_images': plan['final_image_count'],
            'merged_classes': plan['merged_classes'],
            'warnings': plan['warnings'],
            'collision_policy': collision_policy,
            'renamed_file_count': plan['renamed_file_count'],
            'skipped_file_count': plan['skipped_file_count'],
            'overwritten_file_count': plan['overwritten_file_count']
        })

    except Exception as exc:
        db.session.rollback()
        for fpath in copied_files:
            try:
                if os.path.exists(fpath):
                    os.remove(fpath)
            except Exception:
                pass
        if created_dir:
            try:
                shutil.rmtree(dest_path)
            except Exception:
                pass
        return jsonify({'error': f"Failed to execute project merge: {str(exc)}"}), 500
