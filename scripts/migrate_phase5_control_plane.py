import argparse
import os
import sys
from pathlib import Path

from sqlalchemy import (
    Column,
    DateTime,
    MetaData,
    String,
    Table,
    create_engine,
    inspect,
    select,
)
from sqlalchemy.sql import func

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from models import (
    db,
    TrainingBatch,
    TrainingJobAttempt,
    TrainingJobEvent,
    TrainingQueueTask,
    TrainingWorker,
)


MIGRATION_ID = '20260727_phase5_training_control_plane'
PHASE5_TABLES = (
    TrainingWorker.__table__,
    TrainingBatch.__table__,
    TrainingQueueTask.__table__,
    TrainingJobAttempt.__table__,
    TrainingJobEvent.__table__,
)
PHASE5_TABLE_NAMES = tuple(table.name for table in PHASE5_TABLES)
REQUIRED_BASE_TABLES = {
    'projects',
    'training_datasets',
    'training_jobs',
    'ai_models',
}

migration_metadata = MetaData()
schema_migrations = Table(
    'toolib_schema_migrations',
    migration_metadata,
    Column('migration_id', String(100), primary_key=True),
    Column('applied_at', DateTime, nullable=False, server_default=func.now()),
)


def default_database_uri():
    configured = os.environ.get('YOLO_LABELING_DB_URI')
    if configured:
        return configured
    return f"sqlite:///{REPOSITORY_ROOT / 'yolo_labeling.db'}"


def missing_phase5_tables(engine):
    existing = set(inspect(engine).get_table_names())
    return sorted(set(PHASE5_TABLE_NAMES) - existing)


def apply_phase5_migration(engine):
    existing = set(inspect(engine).get_table_names())
    missing_base = sorted(REQUIRED_BASE_TABLES - existing)
    if missing_base:
        raise RuntimeError(
            'Phase 5 migration requires the existing ToolIbV2 schema. '
            f"Missing base tables: {', '.join(missing_base)}"
        )

    schema_migrations.create(bind=engine, checkfirst=True)
    with engine.begin() as connection:
        already_applied = connection.execute(
            select(schema_migrations.c.migration_id).where(
                schema_migrations.c.migration_id == MIGRATION_ID
            )
        ).scalar_one_or_none()
    if already_applied and not missing_phase5_tables(engine):
        return False

    db.metadata.create_all(
        bind=engine,
        tables=list(PHASE5_TABLES),
        checkfirst=True,
    )
    remaining = missing_phase5_tables(engine)
    if remaining:
        raise RuntimeError(
            f"Phase 5 migration incomplete. Missing tables: {', '.join(remaining)}"
        )

    with engine.begin() as connection:
        existing_record = connection.execute(
            select(schema_migrations.c.migration_id).where(
                schema_migrations.c.migration_id == MIGRATION_ID
            )
        ).scalar_one_or_none()
        if existing_record is None:
            connection.execute(
                schema_migrations.insert().values(migration_id=MIGRATION_ID)
            )
    return True


def build_parser():
    parser = argparse.ArgumentParser(
        description='Apply or verify the additive ToolIbV2 Phase 5 schema.',
    )
    parser.add_argument(
        '--database-uri',
        default=None,
        help='SQLAlchemy database URI. Defaults to YOLO_LABELING_DB_URI/local SQLite.',
    )
    parser.add_argument(
        '--check',
        action='store_true',
        help='Verify the Phase 5 tables without changing the database.',
    )
    return parser


def main():
    args = build_parser().parse_args()
    engine = create_engine(args.database_uri or default_database_uri())
    try:
        if args.check:
            missing = missing_phase5_tables(engine)
            if missing:
                raise SystemExit(
                    f"Phase 5 schema is not ready. Missing: {', '.join(missing)}"
                )
            print(f'Phase 5 schema ready ({MIGRATION_ID}).')
            return

        changed = apply_phase5_migration(engine)
        outcome = 'applied' if changed else 'already applied'
        print(f'Phase 5 migration {outcome}: {MIGRATION_ID}.')
    finally:
        engine.dispose()


if __name__ == '__main__':
    main()
