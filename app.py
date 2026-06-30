import os
# pyrefly: ignore [missing-import]
from flask import Flask, render_template
from flask_socketio import SocketIO, emit, join_room, leave_room
from models import db
from routes import api_bp

socketio = SocketIO(cors_allowed_origins="*")

def create_app():
    app = Flask(__name__)
    
    # Configuration
    basedir = os.path.abspath(os.path.dirname(__file__))
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(basedir, 'yolo_labeling.db')
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    
    # Increase maximum upload limit to 10GB for large datasets
    app.config['MAX_CONTENT_LENGTH'] = 10 * 1024 * 1024 * 1024
    app.config['MAX_FORM_PARTS'] = 100000  # Allow large number of files
    
    # Initialize DB
    db.init_app(app)
    
    # Register Blueprints
    app.register_blueprint(api_bp, url_prefix='/api')
    
    # Basic Frontend Routes
    @app.route('/')
    def index():
        return render_template('dashboard.html')

    @app.route('/project/<int:project_id>')
    @app.route('/project/<int:project_id>/<path:filename>')
    def workspace(project_id, filename=None):
        return render_template('workspace.html', project_id=project_id, active_filename=filename)
    
    @app.route('/project/<int:project_id>/tags')
    def tag_manager(project_id):
        return render_template('tag_manager.html', project_id=project_id)
    
    @app.route('/export')
    def export_page():
        return render_template('export.html')
    
    @app.route('/progress')
    def progress_page():
        return render_template('progress.html')

    @app.route('/models-experiment')
    def models_experiment_page():
        return render_template('models_experiment.html')
    
    
    # Initialize SocketIO
    socketio.init_app(app)
    
    return app

# SocketIO Events
active_users = {} # Store user state: {sid: {project_id, user_name, image_id, x, y, color}}

@socketio.on('connect')
def handle_connect():
    pass

@socketio.on('disconnect')
def handle_disconnect():
    from flask import request
    sid = request.sid
    if sid in active_users:
        user_info = active_users[sid]
        project_id = user_info.get('project_id')
        if project_id:
            room = f"project_{project_id}"
            leave_room(room)
            del active_users[sid]
            # Notify others in the room
            emit('user_disconnected', {'sid': sid}, room=room)

@socketio.on('join_project')
def handle_join_project(data):
    from flask import request
    project_id = data.get('project_id')
    user_name = data.get('user_name', 'Anonymous')
    color = data.get('color', '#FF0000')
    
    if project_id:
        room = f"project_{project_id}"
        join_room(room)
        
        sid = request.sid
        active_users[sid] = {
            'project_id': project_id,
            'user_name': user_name,
            'color': color,
            'image_id': None,
            'x': 0,
            'y': 0,
            'active_box_id': None
        }
        
        # Send current users to the new user
        current_users = {k: v for k, v in active_users.items() if v['project_id'] == project_id and k != sid}
        emit('init_users', current_users)
        
        # Notify others
        emit('user_joined', {'sid': sid, 'user_info': active_users[sid]}, room=room, include_self=False)

@socketio.on('update_state')
def handle_update_state(data):
    from flask import request
    sid = request.sid
    if sid in active_users:
        user_info = active_users[sid]
        
        if 'image_id' in data:
            user_info['image_id'] = data['image_id']
        if 'x' in data:
            user_info['x'] = data['x']
        if 'y' in data:
            user_info['y'] = data['y']
        if 'active_box_id' in data:
            user_info['active_box_id'] = data['active_box_id']
            
        project_id = user_info['project_id']
        room = f"project_{project_id}"
        
        emit('state_updated', {
            'sid': sid,
            'image_id': user_info['image_id'],
            'x': user_info['x'],
            'y': user_info['y'],
            'active_box_id': user_info.get('active_box_id')
        }, room=room, include_self=False)

@socketio.on('box_created')
def handle_box_created(data):
    from flask import request
    sid = request.sid
    if sid in active_users:
        project_id = active_users[sid]['project_id']
        room = f"project_{project_id}"
        emit('box_created', {**data, 'sid': sid}, room=room, include_self=False)

@socketio.on('box_updated')
def handle_box_updated(data):
    from flask import request
    sid = request.sid
    if sid in active_users:
        project_id = active_users[sid]['project_id']
        room = f"project_{project_id}"
        emit('box_updated', {**data, 'sid': sid}, room=room, include_self=False)

@socketio.on('box_deleted')
def handle_box_deleted(data):
    from flask import request
    sid = request.sid
    if sid in active_users:
        project_id = active_users[sid]['project_id']
        room = f"project_{project_id}"
        emit('box_deleted', {**data, 'sid': sid}, room=room, include_self=False)

@socketio.on('box_lock')
def handle_box_lock(data):
    from flask import request
    sid = request.sid
    if sid in active_users:
        project_id = active_users[sid]['project_id']
        room = f"project_{project_id}"
        emit('box_lock', {**data, 'sid': sid}, room=room, include_self=False)

@socketio.on('box_unlock')
def handle_box_unlock(data):
    from flask import request
    sid = request.sid
    if sid in active_users:
        project_id = active_users[sid]['project_id']
        room = f"project_{project_id}"
        emit('box_unlock', {**data, 'sid': sid}, room=room, include_self=False)


@socketio.on('request_sync')
def handle_request_sync(data):
    from flask import request
    sid = request.sid
    if sid in active_users:
        project_id = active_users[sid]['project_id']
        room = f"project_{project_id}"
        emit('sync_requested', {'image_id': data.get('image_id'), 'requester_sid': sid}, room=room, include_self=False)

@socketio.on('sync_response')
def handle_sync_response(data):
    target_sid = data.get('target_sid')
    if target_sid:
        emit('sync_received', data, to=target_sid)

@socketio.on('notify_annotations_changed')
def handle_annotations_changed(data):
    project_id = data.get('project_id')
    image_id = data.get('image_id')
    user_name = data.get('user_name', 'Someone')
    is_labeled = data.get('is_labeled')
    classes = data.get('classes')
    
    if project_id and image_id:
        room = f"project_{project_id}"
        emit('annotations_changed', {
            'image_id': image_id,
            'user_name': user_name,
            'is_labeled': is_labeled,
            'classes': classes
        }, room=room, include_self=False)

@socketio.on('notify_classes_changed')
def handle_classes_changed(data):
    project_id = data.get('project_id')
    user_name = data.get('user_name', 'Someone')
    
    if project_id:
        room = f"project_{project_id}"
        emit('classes_changed', {
            'user_name': user_name
        }, room=room, include_self=False)

@socketio.on('notify_tags_changed')
def handle_tags_changed(data):
    project_id = data.get('project_id')
    user_name = data.get('user_name', 'Someone')
    
    if project_id:
        room = f"project_{project_id}"
        emit('tags_changed', {
            'user_name': user_name
        }, room=room, include_self=False)

@socketio.on('send_direct_message')
def handle_send_direct_message(data):
    from flask import request
    target_sid = data.get('target_sid')
    message = data.get('message')
    
    sender_sid = request.sid
    sender_info = active_users.get(sender_sid)
    
    if sender_info and target_sid and message:
        emit('receive_direct_message', {
            'sender_sid': sender_sid,
            'sender_name': sender_info.get('user_name', 'Someone'),
            'message': message
        }, room=target_sid)


if __name__ == '__main__':
    app = create_app()
    with app.app_context():
        db.create_all()  # Create tables if they don't exist
        
        # Safely upgrade existing db to add model_type if it doesn't exist
        try:
            from sqlalchemy import text
            with db.engine.connect() as conn:
                conn.execute(text("ALTER TABLE ai_models ADD COLUMN model_type VARCHAR(50) DEFAULT 'detection'"))
                conn.commit()
        except Exception:
            pass # Column already exists
    socketio.run(app, debug=True, host='0.0.0.0', port=5000)

