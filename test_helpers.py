import os
import tempfile

from app import create_app


REPO_ROOT = os.path.abspath(os.path.dirname(__file__))
PRODUCTION_DB_PATH = os.path.abspath(os.path.join(REPO_ROOT, 'yolo_labeling.db'))


def build_sqlite_uri(db_path):
    return 'sqlite:///' + os.path.abspath(db_path)


def create_isolated_test_app(db_path, **config_overrides):
    config = {
        'TESTING': True,
        'SQLALCHEMY_DATABASE_URI': build_sqlite_uri(db_path),
        'FORCE_HTTPS_REDIRECTS': False,
    }
    config.update(config_overrides)
    return create_app(config_overrides=config)


def assert_safe_test_database(app, expected_root=None):
    db_uri = app.config.get('SQLALCHEMY_DATABASE_URI', '')
    if not app.config.get('TESTING'):
        raise RuntimeError('Refusing destructive test setup because TESTING is not enabled.')
    if not db_uri.startswith('sqlite:///'):
        raise RuntimeError(f'Refusing destructive test setup on non-SQLite database: {db_uri}')

    db_path = os.path.abspath(db_uri.replace('sqlite:///', '', 1))
    if os.path.normcase(db_path) == os.path.normcase(PRODUCTION_DB_PATH):
        raise RuntimeError('Refusing destructive test setup against production database yolo_labeling.db.')

    safe_root = os.path.abspath(expected_root or tempfile.gettempdir())
    try:
        common_root = os.path.commonpath([db_path, safe_root])
    except ValueError:
        common_root = ''
    if os.path.normcase(common_root) != os.path.normcase(safe_root):
        raise RuntimeError(
            f'Refusing destructive test setup outside isolated temp root: db_path={db_path}, expected_root={safe_root}'
        )

    return db_path
