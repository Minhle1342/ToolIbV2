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


MIGRATION_ID = '20260729_phase9_optimizer_contract'
REQUIRED_COLUMNS = {
    'training_jobs': {'effective_config'},
    'training_queue_tasks': {'effective_config'},
}

metadata = MetaData()
schema_migrations = Table(
    'toolib_schema_migrations',
    metadata,
    Column('migration_id', String(100), primary_key=True),
    Column('applied_at', DateTime, nullable=False, server_default=func.now()),
)


def default_database_uri():
    configured = os.environ.get('YOLO_LABELING_DB_URI')
    if configured:
        return normalize_database_uri(configured)
    return f"sqlite:///{REPOSITORY_ROOT / 'yolo_labeling.db'}"


def phase9_schema_errors(engine):
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    errors = []
    missing_tables = sorted(set(REQUIRED_COLUMNS) - existing_tables)
    if missing_tables:
        errors.append(f"missing base tables: {', '.join(missing_tables)}")
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


def phase9_migration_status(engine):
    errors = phase9_schema_errors(engine)
    existing_tables = set(inspect(engine).get_table_names())
    migration_recorded = False
    if schema_migrations.name in existing_tables:
        with engine.connect() as connection:
            migration_recorded = connection.execute(
                select(schema_migrations.c.migration_id).where(
                    schema_migrations.c.migration_id == MIGRATION_ID
                )
            ).scalar_one_or_none() is not None
    return {
        'migration_id': MIGRATION_ID,
        'schema_ready': not errors,
        'migration_recorded': migration_recorded,
        'errors': errors,
    }


def phase9_migration_plan(engine):
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    missing_tables = sorted(set(REQUIRED_COLUMNS) - existing_tables)
    status = phase9_migration_status(engine)
    actions = []
    if not missing_tables:
        for table_name, required_columns in REQUIRED_COLUMNS.items():
            actual_columns = {
                column['name']
                for column in inspector.get_columns(table_name)
            }
            actions.extend(
                f'add column {table_name}.{column_name}'
                for column_name in sorted(required_columns - actual_columns)
            )
        if not status['migration_recorded']:
            actions.append(f'record migration {MIGRATION_ID}')
    return {
        **status,
        'blocked': bool(missing_tables),
        'actions': actions,
    }


def apply_phase9_migration(engine):
    missing_base = sorted(
        set(REQUIRED_COLUMNS) - set(inspect(engine).get_table_names())
    )
    if missing_base:
        raise RuntimeError(
            'Phase 9 migration requires the Phase 6 ToolIbV2 schema. '
            f"Missing tables: {', '.join(missing_base)}"
        )

    schema_migrations.create(bind=engine, checkfirst=True)
    with engine.begin() as connection:
        already_applied = connection.execute(
            select(schema_migrations.c.migration_id).where(
                schema_migrations.c.migration_id == MIGRATION_ID
            )
        ).scalar_one_or_none()

    ensure_runtime_columns(engine)
    errors = phase9_schema_errors(engine)
    if errors:
        raise RuntimeError(
            'Phase 9 migration incomplete: ' + '; '.join(errors)
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
        description='Apply or verify the ToolIbV2 optimizer contract schema.',
    )
    parser.add_argument(
        '--database-uri',
        default=None,
        help='SQLAlchemy database URI. Defaults to YOLO_LABELING_DB_URI/local SQLite.',
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        '--check',
        action='store_true',
        help='Legacy schema-only verification without changing the database.',
    )
    mode.add_argument(
        '--status',
        action='store_true',
        help='Show schema and migration-ledger readiness without changing the database.',
    )
    mode.add_argument(
        '--dry-run',
        action='store_true',
        help='Show the additive actions Phase 9 would apply without changing the database.',
    )
    return parser


def main():
    args = build_parser().parse_args()
    engine = create_engine(
        normalize_database_uri(args.database_uri or default_database_uri())
    )
    try:
        if args.status:
            status = phase9_migration_status(engine)
            schema_label = 'ready' if status['schema_ready'] else 'not-ready'
            ledger_label = (
                'recorded' if status['migration_recorded'] else 'missing'
            )
            print(
                f'Phase 9 status: schema={schema_label}, '
                f'ledger={ledger_label}, migration={MIGRATION_ID}.'
            )
            for error in status['errors']:
                print(f'- {error}')
            if not (status['schema_ready'] and status['migration_recorded']):
                raise SystemExit(1)
            return
        if args.dry_run:
            plan = phase9_migration_plan(engine)
            if plan['blocked']:
                print('Phase 9 dry-run blocked:')
                for error in plan['errors']:
                    print(f'- {error}')
                raise SystemExit(1)
            if plan['actions']:
                print('Phase 9 dry-run actions:')
                for action in plan['actions']:
                    print(f'- {action}')
            else:
                print(f'Phase 9 dry-run: no changes required ({MIGRATION_ID}).')
            return
        if args.check:
            errors = phase9_schema_errors(engine)
            if errors:
                raise SystemExit(
                    'Phase 9 schema is not ready: ' + '; '.join(errors)
                )
            print(f'Phase 9 schema ready ({MIGRATION_ID}).')
            return
        changed = apply_phase9_migration(engine)
        outcome = 'applied' if changed else 'already applied'
        print(f'Phase 9 migration {outcome}: {MIGRATION_ID}.')
    finally:
        engine.dispose()


if __name__ == '__main__':
    main()
