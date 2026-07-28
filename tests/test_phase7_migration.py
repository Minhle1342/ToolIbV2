from sqlalchemy import create_engine, inspect, text

from scripts.migrate_phase7_resumable_training import (
    MIGRATION_ID,
    apply_phase7_migration,
    phase7_schema_errors,
)


def test_phase7_migration_is_additive_and_idempotent(tmp_path):
    database_path = tmp_path / 'phase7.db'
    engine = create_engine(f'sqlite:///{database_path}')
    try:
        with engine.begin() as connection:
            connection.execute(text(
                'CREATE TABLE ai_models (id INTEGER PRIMARY KEY)'
            ))
            connection.execute(text(
                'CREATE TABLE projects (id INTEGER PRIMARY KEY)'
            ))
            connection.execute(text(
                'CREATE TABLE training_batches (id INTEGER PRIMARY KEY)'
            ))
            connection.execute(text(
                'CREATE TABLE training_datasets (id INTEGER PRIMARY KEY)'
            ))
            connection.execute(text(
                'CREATE TABLE training_jobs (id INTEGER PRIMARY KEY)'
            ))
            connection.execute(text(
                'CREATE TABLE training_workers (id INTEGER PRIMARY KEY)'
            ))
            connection.execute(text(
                'CREATE TABLE training_queue_tasks (id INTEGER PRIMARY KEY)'
            ))
            connection.execute(text(
                'CREATE TABLE training_job_attempts (id INTEGER PRIMARY KEY)'
            ))

        assert apply_phase7_migration(engine) is True
        assert apply_phase7_migration(engine) is False
        assert phase7_schema_errors(engine) == []

        inspector = inspect(engine)
        assert 'training_checkpoints' in inspector.get_table_names()
        task_columns = {
            column['name']
            for column in inspector.get_columns('training_queue_tasks')
        }
        assert {
            'recovery_generation',
            'resume_count',
            'max_resume_count',
            'checkpoint_interval',
            'worker_lost_at',
            'recovery_deadline_at',
        } <= task_columns
        attempt_columns = {
            column['name']
            for column in inspector.get_columns('training_job_attempts')
        }
        assert {
            'training_job_id',
            'attempt_kind',
            'generation',
            'resume_checkpoint_id',
            'resumed_from_epoch',
        } <= attempt_columns
        with engine.connect() as connection:
            applied = connection.execute(text(
                'SELECT migration_id FROM toolib_schema_migrations'
            )).scalars().all()
        assert applied == [MIGRATION_ID]
    finally:
        engine.dispose()
