from sqlalchemy import create_engine, inspect, select

from models import db
from scripts.migrate_phase5_control_plane import (
    MIGRATION_ID,
    PHASE5_TABLE_NAMES,
    PHASE5_TABLES,
    apply_phase5_migration,
    schema_migrations,
)


def test_phase5_migration_is_additive_recorded_and_idempotent(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'migration.db'}")
    try:
        db.metadata.create_all(bind=engine)
        db.metadata.drop_all(bind=engine, tables=list(reversed(PHASE5_TABLES)))

        assert not set(PHASE5_TABLE_NAMES).intersection(
            inspect(engine).get_table_names()
        )
        assert apply_phase5_migration(engine) is True
        assert set(PHASE5_TABLE_NAMES).issubset(
            inspect(engine).get_table_names()
        )

        with engine.begin() as connection:
            applied = connection.execute(
                select(schema_migrations.c.migration_id)
            ).scalars().all()
        assert applied == [MIGRATION_ID]
        assert apply_phase5_migration(engine) is False
    finally:
        engine.dispose()
