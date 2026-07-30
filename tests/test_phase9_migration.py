from sqlalchemy import create_engine, inspect, text

from scripts.migrate_phase9_optimizer_contract import (
    MIGRATION_ID,
    apply_phase9_migration,
    phase9_migration_plan,
    phase9_migration_status,
    phase9_schema_errors,
)


def test_phase9_migration_is_additive_and_idempotent(tmp_path):
    database_path = tmp_path / 'phase9.db'
    engine = create_engine(f'sqlite:///{database_path}')
    try:
        with engine.begin() as connection:
            connection.execute(text(
                'CREATE TABLE training_jobs (id INTEGER PRIMARY KEY)'
            ))
            connection.execute(text(
                'CREATE TABLE training_queue_tasks (id INTEGER PRIMARY KEY)'
            ))

        assert apply_phase9_migration(engine) is True
        assert apply_phase9_migration(engine) is False
        assert phase9_schema_errors(engine) == []

        inspector = inspect(engine)
        for table_name in ('training_jobs', 'training_queue_tasks'):
            columns = {
                column['name']
                for column in inspector.get_columns(table_name)
            }
            assert 'effective_config' in columns
        with engine.connect() as connection:
            applied = connection.execute(text(
                'SELECT migration_id FROM toolib_schema_migrations'
            )).scalars().all()
        assert applied == [MIGRATION_ID]
    finally:
        engine.dispose()


def test_phase9_status_and_dry_run_are_read_only(tmp_path):
    database_path = tmp_path / 'phase9-status.db'
    engine = create_engine(f'sqlite:///{database_path}')
    try:
        with engine.begin() as connection:
            connection.execute(text(
                'CREATE TABLE training_jobs (id INTEGER PRIMARY KEY)'
            ))
            connection.execute(text(
                'CREATE TABLE training_queue_tasks (id INTEGER PRIMARY KEY)'
            ))

        status = phase9_migration_status(engine)
        plan = phase9_migration_plan(engine)

        assert status == {
            'migration_id': MIGRATION_ID,
            'schema_ready': False,
            'migration_recorded': False,
            'errors': [
                'training_jobs missing columns: effective_config',
                'training_queue_tasks missing columns: effective_config',
            ],
        }
        assert plan['blocked'] is False
        assert plan['actions'] == [
            'add column training_jobs.effective_config',
            'add column training_queue_tasks.effective_config',
            f'record migration {MIGRATION_ID}',
        ]
        assert 'toolib_schema_migrations' not in inspect(engine).get_table_names()

        apply_phase9_migration(engine)
        assert phase9_migration_status(engine) == {
            'migration_id': MIGRATION_ID,
            'schema_ready': True,
            'migration_recorded': True,
            'errors': [],
        }
        assert phase9_migration_plan(engine)['actions'] == []
    finally:
        engine.dispose()
