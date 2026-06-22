import os
# pyrefly: ignore [missing-import]
from flask import Flask, render_template
from models import db
from routes import api_bp

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
    def workspace(project_id):
        return render_template('workspace.html', project_id=project_id)
    
    @app.route('/export')
    def export_page():
        return render_template('export.html')
    
    @app.route('/progress')
    def progress_page():
        return render_template('progress.html')

    @app.route('/models-experiment')
    def models_experiment_page():
        return render_template('models_experiment.html')
    
    return app

if __name__ == '__main__':
    app = create_app()
    with app.app_context():
        db.create_all()  # Create tables if they don't exist
    app.run(debug=True, host='0.0.0.0', port=5000, threaded=True)
