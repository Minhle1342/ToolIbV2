from sqlalchemy import create_engine, inspect, select, text

from scripts.migrate_phase6_finetune import (
    MIGRATION_ID,
    REQUIRED_COLUMNS,
    apply_phase6_migration,
    schema_migrations,
)


def test_phase6_migration_adds_artifact_table_columns_and_is_idempotent(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'phase6.db'}")
    legacy_tables = (
        'projects',
        'ai_models',
        'training_datasets',
        'training_jobs',
        'training_workers',
        'training_batches',
        'training_queue_tasks',
    )
    try:
        with engine.begin() as connection:
            for table_name in legacy_tables:
                connection.execute(text(
                    f'CREATE TABLE {table_name} '
                    '(id INTEGER PRIMARY KEY)'
                ))

        assert 'model_artifacts' not in inspect(engine).get_table_names()
        assert 'finetune_parameter_sets' not in inspect(engine).get_table_names()
        assert apply_phase6_migration(engine) is True

        inspector = inspect(engine)
        assert 'model_artifacts' in inspector.get_table_names()
        assert 'finetune_parameter_sets' in inspector.get_table_names()
        for table_name, expected_columns in REQUIRED_COLUMNS.items():
            actual_columns = {
                column['name']
                for column in inspector.get_columns(table_name)
            }
            assert expected_columns.issubset(actual_columns)

        with engine.begin() as connection:
            applied = connection.execute(
                select(schema_migrations.c.migration_id)
            ).scalars().all()
        assert applied == [MIGRATION_ID]
        assert apply_phase6_migration(engine) is False
    finally:
        engine.dispose()
