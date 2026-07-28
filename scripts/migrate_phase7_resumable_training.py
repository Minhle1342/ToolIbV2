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

from database_support import ensure_runtime_columns, normalize_database_uri
from models import TrainingCheckpoint, db


MIGRATION_ID = '20260728_phase7_resumable_training'
REQUIRED_TABLES = {
    'ai_models',
    'projects',
    'training_batches',
    'training_datasets',
    'training_job_attempts',
    'training_jobs',
    'training_queue_tasks',
    'training_workers',
}
REQUIRED_COLUMNS = {
    'training_queue_tasks': {
        'recovery_generation',
        'resume_count',
        'max_resume_count',
        'checkpoint_interval',
        'worker_lost_at',
        'recovery_deadline_at',
    },
    'training_job_attempts': {
        'training_job_id',
        'attempt_kind',
        'generation',
        'resume_checkpoint_id',
        'resumed_from_epoch',
    },
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
        return normalize_database_uri(configured)
    return f"sqlite:///{REPOSITORY_ROOT / 'yolo_labeling.db'}"


def phase7_schema_errors(engine):
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    errors = []
    missing_tables = sorted(REQUIRED_TABLES - existing_tables)
    if missing_tables:
        errors.append(f"missing base tables: {', '.join(missing_tables)}")
    if TrainingCheckpoint.__tablename__ not in existing_tables:
        errors.append(f'missing table: {TrainingCheckpoint.__tablename__}')
    for table_name, required_columns in REQUIRED_COLUMNS.items():
        if table_name not in existing_tables:
            continue
        actual_columns = {
            column['name']
            for column in inspector.get_columns(table_name)
        }
        missing_columns = sorted(required_columns - actual_columns)
        if missing_columns:
            errors.append(
                f"{table_name} missing columns: {', '.join(missing_columns)}"
            )
    return errors


def apply_phase7_migration(engine):
    existing_tables = set(inspect(engine).get_table_names())
    missing_base = sorted(REQUIRED_TABLES - existing_tables)
    if missing_base:
        raise RuntimeError(
            'Phase 7 migration requires the Phase 6 ToolIbV2 schema. '
            f"Missing tables: {', '.join(missing_base)}"
        )

    schema_migrations.create(bind=engine, checkfirst=True)
    with engine.begin() as connection:
        already_applied = connection.execute(
            select(schema_migrations.c.migration_id).where(
                schema_migrations.c.migration_id == MIGRATION_ID
            )
        ).scalar_one_or_none()

    db.metadata.create_all(
        bind=engine,
        tables=[TrainingCheckpoint.__table__],
        checkfirst=True,
    )
    ensure_runtime_columns(engine)
    errors = phase7_schema_errors(engine)
    if errors:
        raise RuntimeError(
            'Phase 7 migration incomplete: ' + '; '.join(errors)
        )

    if already_applied:
        return False
    with engine.begin() as connection:
        connection.execute(
            schema_migrations.insert().values(migration_id=MIGRATION_ID)
        )
    return True


def build_parser():
    parser = argparse.ArgumentParser(
        description='Apply or verify the additive ToolIbV2 Phase 7 schema.',
    )
    parser.add_argument(
        '--database-uri',
        default=None,
        help='SQLAlchemy database URI. Defaults to YOLO_LABELING_DB_URI/local SQLite.',
    )
    parser.add_argument(
        '--check',
        action='store_true',
        help='Verify Phase 7 without changing the database.',
    )
    return parser


def main():
    args = build_parser().parse_args()
    engine = create_engine(
        normalize_database_uri(args.database_uri or default_database_uri())
    )
    try:
        if args.check:
            errors = phase7_schema_errors(engine)
            if errors:
                raise SystemExit(
                    'Phase 7 schema is not ready: ' + '; '.join(errors)
                )
            print(f'Phase 7 schema ready ({MIGRATION_ID}).')
            return

        changed = apply_phase7_migration(engine)
        outcome = 'applied' if changed else 'already applied'
        print(f'Phase 7 migration {outcome}: {MIGRATION_ID}.')
    finally:
        engine.dispose()


if __name__ == '__main__':
    main()
