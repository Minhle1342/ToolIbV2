from sqlalchemy import create_engine, inspect, text

from scripts.migrate_phase8_object_transport import (
    MIGRATION_ID,
    apply_phase8_migration,
    phase8_schema_errors,
)


def test_phase8_migration_is_additive_and_idempotent(tmp_path):
    database_path = tmp_path / 'phase8.db'
    engine = create_engine(f'sqlite:///{database_path}')
    try:
        with engine.begin() as connection:
            connection.execute(text(
                'CREATE TABLE training_datasets (id INTEGER PRIMARY KEY)'
            ))
            connection.execute(text(
                'CREATE TABLE model_artifacts (id INTEGER PRIMARY KEY)'
            ))

        assert apply_phase8_migration(engine) is True
        assert apply_phase8_migration(engine) is False
        assert phase8_schema_errors(engine) == []

        inspector = inspect(engine)
        dataset_columns = {
            column['name']
            for column in inspector.get_columns('training_datasets')
        }
        assert {
            'storage_backend',
            'object_key',
            'object_uploaded_at',
            'object_verified_at',
        } <= dataset_columns
        artifact_columns = {
            column['name']
            for column in inspector.get_columns('model_artifacts')
        }
        assert {
            'storage_backend',
            'object_key',
            'object_verified_at',
        } <= artifact_columns
        with engine.connect() as connection:
            applied = connection.execute(text(
                'SELECT migration_id FROM toolib_schema_migrations'
            )).scalars().all()
        assert applied == [MIGRATION_ID]
    finally:
        engine.dispose()
