from datetime import datetime
import re
import unicodedata
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

def slugify_project_name(name):
    normalized = unicodedata.normalize('NFKD', name or '').encode('ascii', 'ignore').decode('ascii')
    slug = re.sub(r'[^a-zA-Z0-9]+', '-', normalized).strip('-').lower()
    return slug or 'project'

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
            'slug': slugify_project_name(self.name),
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
    filename = db.Column(db.String(500), nullable=False)
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
    activation_ready = db.Column(db.Boolean, nullable=False, default=True)
    model_type = db.Column(db.String(50), default='detection') # 'detection' or 'classification'
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'filename': self.filename,
            'is_active': self.is_active,
            'activation_ready': self.activation_ready,
            'model_type': self.model_type,
            'created_at': self.created_at.isoformat()
        }


class TrainingDataset(db.Model):
    __tablename__ = 'training_datasets'

    id = db.Column(db.Integer, primary_key=True)
    dataset_id = db.Column(db.String(36), nullable=False, unique=True, index=True)
    project_id = db.Column(
        db.Integer,
        db.ForeignKey('projects.id', ondelete='SET NULL'),
        nullable=True,
        index=True
    )
    status = db.Column(db.String(20), nullable=False, default='exporting', index=True)
    archive_path = db.Column(db.String(1000), nullable=True)
    archive_sha256 = db.Column(db.String(64), nullable=True)
    archive_size = db.Column(db.Integer, nullable=True)
    train_count = db.Column(db.Integer, nullable=False, default=0)
    val_count = db.Column(db.Integer, nullable=False, default=0)
    test_count = db.Column(db.Integer, nullable=False, default=0)
    total_count = db.Column(db.Integer, nullable=False, default=0)
    class_names = db.Column(db.JSON, nullable=True)
    split_config = db.Column(db.JSON, nullable=True)
    remote_api_url = db.Column(db.String(500), nullable=True)
    remote_drive_path = db.Column(db.String(1000), nullable=True)
    error = db.Column(db.Text, nullable=True)
    uploaded_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'dataset_id': self.dataset_id,
            'project_id': self.project_id,
            'status': self.status,
            'archive_sha256': self.archive_sha256,
            'archive_size': self.archive_size,
            'train_count': self.train_count,
            'val_count': self.val_count,
            'test_count': self.test_count,
            'total_count': self.total_count,
            'class_names': self.class_names,
            'splits': self.split_config,
            'remote_api_url': self.remote_api_url,
            'remote_drive_path': self.remote_drive_path,
            'error': self.error,
            'uploaded_at': self.uploaded_at.isoformat() if self.uploaded_at else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


class TrainingJob(db.Model):
    __tablename__ = 'training_jobs'

    id = db.Column(db.Integer, primary_key=True)
    remote_job_id = db.Column(db.String(36), nullable=False, unique=True, index=True)
    project_id = db.Column(
        db.Integer,
        db.ForeignKey('projects.id', ondelete='SET NULL'),
        nullable=True,
        index=True
    )
    imported_model_id = db.Column(
        db.Integer,
        db.ForeignKey('ai_models.id', ondelete='SET NULL'),
        nullable=True,
        index=True
    )
    training_dataset_id = db.Column(
        db.Integer,
        db.ForeignKey('training_datasets.id', ondelete='SET NULL'),
        nullable=True,
        index=True
    )
    dataset_id = db.Column(db.String(36), nullable=True, index=True)
    remote_api_url = db.Column(db.String(500), nullable=False)
    status = db.Column(db.String(20), nullable=False, default='queued', index=True)
    connection_status = db.Column(db.String(20), nullable=False, default='synced')
    model = db.Column(db.String(100), nullable=True)
    epochs = db.Column(db.Integer, nullable=True)
    batch = db.Column(db.Integer, nullable=True)
    imgsz = db.Column(db.Integer, nullable=True)
    current_epoch = db.Column(db.Integer, nullable=False, default=0)
    total_epochs = db.Column(db.Integer, nullable=False, default=0)
    message = db.Column(db.Text, nullable=True)
    error = db.Column(db.Text, nullable=True)
    last_sync_error = db.Column(db.Text, nullable=True)
    request_payload = db.Column(db.JSON, nullable=True)
    artifacts = db.Column(db.JSON, nullable=True)
    remote_created_at = db.Column(db.DateTime, nullable=True)
    started_at = db.Column(db.DateTime, nullable=True)
    finished_at = db.Column(db.DateTime, nullable=True)
    last_synced_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'remote_job_id': self.remote_job_id,
            'project_id': self.project_id,
            'imported_model_id': self.imported_model_id,
            'training_dataset_id': self.training_dataset_id,
            'dataset_id': self.dataset_id,
            'remote_api_url': self.remote_api_url,
            'status': self.status,
            'connection_status': self.connection_status,
            'model': self.model,
            'epochs': self.epochs,
            'batch': self.batch,
            'imgsz': self.imgsz,
            'current_epoch': self.current_epoch,
            'total_epochs': self.total_epochs,
            'message': self.message,
            'error': self.error,
            'last_sync_error': self.last_sync_error,
            'request': self.request_payload,
            'artifacts': self.artifacts,
            'remote_created_at': self.remote_created_at.isoformat() if self.remote_created_at else None,
            'started_at': self.started_at.isoformat() if self.started_at else None,
            'finished_at': self.finished_at.isoformat() if self.finished_at else None,
            'last_synced_at': self.last_synced_at.isoformat() if self.last_synced_at else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }
