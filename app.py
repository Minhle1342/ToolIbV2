import os
# pyrefly: ignore [missing-import]
from flask import Flask, abort, current_app, redirect, render_template, request
from flask_socketio import SocketIO, emit, join_room, leave_room
from werkzeug.middleware.proxy_fix import ProxyFix
from models import Project, db, slugify_project_name
from routes import api_bp

socketio = SocketIO(cors_allowed_origins="*")
LOCAL_HTTP_HOSTS = {"localhost", "127.0.0.1", "::1"}


def get_default_database_uri():
    basedir = os.path.abspath(os.path.dirname(__file__))
    return os.environ.get(
        'YOLO_LABELING_DB_URI',
        'sqlite:///' + os.path.join(basedir, 'yolo_labeling.db')
    )


def should_redirect_to_https():
    if not current_app.config.get('FORCE_HTTPS_REDIRECTS', True):
        return False
    if request.method not in ('GET', 'HEAD'):
        return False
    if request.scheme != 'http':
        return False

    host = request.host or ''
    if host.startswith('['):
        host = host[1:].split(']', 1)[0]
    elif ':' in host:
        host = host.rsplit(':', 1)[0]
    host = host.lower()

    return host not in LOCAL_HTTP_HOSTS


def build_https_url():
    return request.url.replace('http://', 'https://', 1)

def resolve_project(identifier):
    if identifier.isdigit():
        project = Project.query.get(int(identifier))
        if project:
            return project

    for project in Project.query.all():
        if slugify_project_name(project.name) == identifier:
            return project

    abort(404)

def create_app(config_overrides=None):
    app = Flask(__name__)
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
    
    # Configuration
    app.config.update({
        'SQLALCHEMY_DATABASE_URI': get_default_database_uri(),
        'SQLALCHEMY_TRACK_MODIFICATIONS': False,
        'PREFERRED_URL_SCHEME': 'https',
        'FORCE_HTTPS_REDIRECTS': True,
    })
    
    # Increase maximum upload limit to 10GB for large datasets
    app.config['MAX_CONTENT_LENGTH'] = 10 * 1024 * 1024 * 1024
    app.config['MAX_FORM_PARTS'] = 100000  # Allow large number of files

    if config_overrides:
        app.config.update(config_overrides)
    
    # Initialize DB
    db.init_app(app)
    
    # Register Blueprints
    app.register_blueprint(api_bp, url_prefix='/api')

    @app.before_request
    def redirect_http_to_https():
        if should_redirect_to_https():
            return redirect(build_https_url(), code=308)
    
    # Basic Frontend Routes
    @app.route('/')
    def index():
        return render_template('dashboard.html')

    @app.route('/project/<project_identifier>/tags')
    def tag_manager(project_identifier):
        project = resolve_project(project_identifier)
        return render_template(
            'tag_manager.html',
            project_id=project.id,
            project_slug=slugify_project_name(project.name)
        )

    @app.route('/project/<project_identifier>/guide')
    def project_guide(project_identifier):
        project = resolve_project(project_identifier)
        project_slug = slugify_project_name(project.name)
        workspace_url = f'/project/{project_slug}/'
        if request.query_string:
            workspace_url = f"{workspace_url}?{request.query_string.decode('utf-8')}"
        return render_template(
            'guide.html',
            project_id=project.id,
            project_slug=project_slug,
            project_name=project.name,
            workspace_url=workspace_url
        )

    @app.route('/project/<project_identifier>/')
    @app.route('/project/<project_identifier>/<path:filename>')
    def workspace(project_identifier, filename=None):
        project = resolve_project(project_identifier)
        return render_template(
            'workspace.html',
            project_id=project.id,
            project_slug=slugify_project_name(project.name),
            active_filename=filename
        )
    
    @app.route('/export')
    def export_page():
        return render_template('export.html')
    
    @app.route('/progress')
    def progress_page():
        return render_template('progress.html')

    @app.route('/models-experiment')
    def models_experiment_page():
        return render_template('models_experiment.html')

    @app.route('/classification-datasets')
    def classification_datasets_page():
        return render_template('classification_dataset_manager.html')
    
    
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


@socketio.on('collab_call_user')
def handle_collab_call_user(data):
    from flask import request
    target_sid = data.get('target_sid')
    sender_sid = request.sid
    sender_info = active_users.get(sender_sid)
    if sender_info and target_sid:
        emit('collab_incoming_call', {
            'caller_sid': sender_sid,
            'caller_name': sender_info.get('user_name', 'Someone')
        }, room=target_sid)


@socketio.on('collab_cancel_call')
def handle_collab_cancel_call(data):
    target_sid = data.get('target_sid')
    if target_sid:
        emit('collab_call_cancelled', room=target_sid)


@socketio.on('collab_accept_call')
def handle_collab_accept_call(data):
    from flask import request
    target_sid = data.get('target_sid')
    sender_sid = request.sid
    if target_sid:
        emit('collab_call_accepted', {
            'target_sid': sender_sid
        }, room=target_sid)


@socketio.on('collab_reject_call')
def handle_collab_reject_call(data):
    from flask import request
    target_sid = data.get('target_sid')
    sender_sid = request.sid
    if target_sid:
        emit('collab_call_rejected', {
            'target_sid': sender_sid
        }, room=target_sid)


@socketio.on('collab_wertc_signal')
def handle_collab_wertc_signal(data):
    from flask import request
    target_sid = data.get('target_sid')
    signal = data.get('signal')
    sender_sid = request.sid
    if target_sid and signal:
        emit('collab_wertc_signal', {
            'sender_sid': sender_sid,
            'signal': signal
        }, room=target_sid)


@socketio.on('collab_hangup')
def handle_collab_hangup(data):
    target_sid = data.get('target_sid')
    if target_sid:
        emit('collab_call_hungup', room=target_sid)



def check_and_generate_certificates():
    import os
    import socket
    import ipaddress
    import datetime
    from cryptography import x509
    from cryptography.x509.oid import NameOID
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives import serialization

    basedir = os.path.abspath(os.path.dirname(__file__))
    key_path = os.path.join(basedir, "key.pem")
    cert_path = os.path.join(basedir, "cert.pem")
    
    if os.path.exists(key_path) and os.path.exists(cert_path):
        return key_path, cert_path

    # Helper to get local IP
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('10.254.254.254', 1))
        local_ip = s.getsockname()[0]
    except Exception:
        local_ip = '127.0.0.1'
    finally:
        s.close()

    print(f"[SSL] Generating self-signed certificate for host IP: {local_ip}...")
    # Generate private key
    key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
    )
    
    # Subject & Issuer
    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, "VN"),
        x509.NameAttribute(NameOID.STATE_OR_PROVINCE_NAME, "Hanoi"),
        x509.NameAttribute(NameOID.LOCALITY_NAME, "Hanoi"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "YOLO Labeling Hub"),
        x509.NameAttribute(NameOID.COMMON_NAME, local_ip),
    ])
    
    # Set up SANs (Subject Alternative Names)
    sans = [
        x509.DNSName("localhost"),
        x509.IPAddress(ipaddress.IPv4Address("127.0.0.1")),
    ]
    
    if local_ip != "127.0.0.1":
        try:
            sans.append(x509.IPAddress(ipaddress.IPv4Address(local_ip)))
        except Exception:
            pass

    cert = x509.CertificateBuilder().subject_name(
        subject
    ).issuer_name(
        issuer
    ).public_key(
        key.public_key()
    ).serial_number(
        x509.random_serial_number()
    ).not_valid_before(
        datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=1)
    ).not_valid_after(
        datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=3650)
    ).add_extension(
        x509.SubjectAlternativeName(sans),
        critical=False,
    ).sign(key, hashes.SHA256())
    
    # Write files
    with open(key_path, "wb") as f:
        f.write(key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        ))
        
    with open(cert_path, "wb") as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))
        
    print(f"[SSL] Certificate generated successfully: cert.pem, key.pem")
    return key_path, cert_path


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
            
    # Check/generate certs and run Socket.IO over HTTPS
    key_path, cert_path = check_and_generate_certificates()
    socketio.run(app, debug=True, host='0.0.0.0', port=5000, keyfile=key_path, certfile=cert_path)

