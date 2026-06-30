from datetime import datetime
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

image_tags = db.Table('image_tags',
    db.Column('image_id', db.Integer, db.ForeignKey('images.id'), primary_key=True),
    db.Column('tag_id', db.Integer, db.ForeignKey('tags.id'), primary_key=True)
)

class Tag(db.Model):
    __tablename__ = 'tags'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False)
    project_id = db.Column(db.Integer, db.ForeignKey('projects.id'), nullable=False)
    color = db.Column(db.String(20), default='#3b82f6')

    # Ensure unique tag names within a project
    __table_args__ = (
        db.UniqueConstraint('project_id', 'name', name='unique_project_tag'),
    )

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'project_id': self.project_id,
            'color': self.color
        }

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
    is_reviewed = db.Column(db.Boolean, default=False)
    flag_status = db.Column(db.String(20), default='Normal') # Normal, Review, Error
    split_type = db.Column(db.String(20), default='train') # train, val, test
    
    # Unique constraint to prevent duplicate images in a project
    __table_args__ = (
        db.UniqueConstraint('project_id', 'filename', name='unique_project_image'),
    )

    # Relationship for tags
    tags = db.relationship('Tag', secondary=image_tags, backref=db.backref('images_list', lazy='dynamic'))

    def to_dict(self):
        return {
            'id': self.id,
            'filename': self.filename,
            'project_id': self.project_id,
            'view_id': self.view_id,
            'is_labeled': self.is_labeled,
            'is_reviewed': self.is_reviewed,
            'flag_status': self.flag_status,
            'split_type': self.split_type,
            'tags': [tag.to_dict() for tag in self.tags]
        }

class AIModel(db.Model):
    __tablename__ = 'ai_models'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.String(500), nullable=True)
    filename = db.Column(db.String(200), nullable=False, unique=True)
    is_active = db.Column(db.Boolean, default=False)
    model_type = db.Column(db.String(50), default='detection') # 'detection' or 'classification'
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'filename': self.filename,
            'is_active': self.is_active,
            'model_type': self.model_type,
            'created_at': self.created_at.isoformat()
        }
