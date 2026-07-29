from sqlalchemy import create_engine, inspect, text

from scripts.migrate_phase9_optimizer_contract import (
    MIGRATION_ID,
    apply_phase9_migration,
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
