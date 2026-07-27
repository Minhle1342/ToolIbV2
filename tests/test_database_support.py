from sqlalchemy import create_engine, select

from database_support import (
    configure_database_engine,
    normalize_database_uri,
)
from models import Project, db
from scripts.migrate_sqlite_to_postgres import copy_database


def test_postgres_uri_uses_psycopg_driver():
    assert normalize_database_uri(
        'postgres://user:pass@localhost/toolib'
    ) == 'postgresql+psycopg://user:pass@localhost/toolib'
    assert normalize_database_uri(
        'postgresql://user:pass@localhost/toolib'
    ) == 'postgresql+psycopg://user:pass@localhost/toolib'


def test_sqlite_foreign_keys_are_enabled(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'foreign-keys.db'}")
    try:
        configure_database_engine(engine)
        with engine.connect() as connection:
            enabled = connection.exec_driver_sql(
                'PRAGMA foreign_keys'
            ).scalar_one()
        assert enabled == 1
    finally:
        engine.dispose()


def test_database_copy_preserves_rows_and_ids(tmp_path):
    source_engine = create_engine(f"sqlite:///{tmp_path / 'source.db'}")
    target_engine = create_engine(f"sqlite:///{tmp_path / 'target.db'}")
    try:
        db.metadata.create_all(bind=source_engine)
        with source_engine.begin() as connection:
            connection.execute(Project.__table__.insert().values(
                id=17,
                name='Migrated project',
                root_path='C:/datasets/migrated',
            ))

        report = copy_database(source_engine, target_engine)

        assert report['tables']['projects'] == 1
        with target_engine.connect() as connection:
            project = connection.execute(
                select(Project.__table__)
            ).mappings().one()
        assert project['id'] == 17
        assert project['name'] == 'Migrated project'
    finally:
        source_engine.dispose()
        target_engine.dispose()
