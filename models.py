from datetime import datetime
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

class Project(db.Model):
    __tablename__ = 'projects'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    root_path = db.Column(db.String(500), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    views = db.relationship('View', backref='project', lazy=True, cascade="all, delete-orphan")
    images = db.relationship('Image', backref='project', lazy=True, cascade="all, delete-orphan")

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'root_path': self.root_path,
            'created_at': self.created_at.isoformat()
        }

class View(db.Model):
    __tablename__ = 'views'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    project_id = db.Column(db.Integer, db.ForeignKey('projects.id'), nullable=False)
    
    # Relationships
    images = db.relationship('Image', backref='view', lazy=True)

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'project_id': self.project_id
        }

class Image(db.Model):
    __tablename__ = 'images'
    
    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(200), nullable=False)
    project_id = db.Column(db.Integer, db.ForeignKey('projects.id'), nullable=False)
    view_id = db.Column(db.Integer, db.ForeignKey('views.id'), nullable=True)
    is_labeled = db.Column(db.Boolean, default=False)
    flag_status = db.Column(db.String(20), default='Normal') # Normal, Review, Error
    split_type = db.Column(db.String(20), default='train') # train, val, test
    
    # Unique constraint to prevent duplicate images in a project
    __table_args__ = (
        db.UniqueConstraint('project_id', 'filename', name='unique_project_image'),
    )

    def to_dict(self):
        return {
            'id': self.id,
            'filename': self.filename,
            'project_id': self.project_id,
            'view_id': self.view_id,
            'is_labeled': self.is_labeled,
            'flag_status': self.flag_status,
            'split_type': self.split_type
        }
