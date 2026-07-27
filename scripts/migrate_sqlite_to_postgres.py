import argparse
import json
import os
import sys
from pathlib import Path

from sqlalchemy import MetaData, Table, create_engine, func, inspect, select, text


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from database_support import normalize_database_uri
from models import db


def default_sqlite_uri():
    return f"sqlite:///{(REPOSITORY_ROOT / 'yolo_labeling.db').as_posix()}"


def _source_rows(source_engine, table_names):
    reflected = MetaData()
    reflected.reflect(bind=source_engine, only=table_names)
    rows_by_table = {}
    with source_engine.connect() as connection:
        for table_name in table_names:
            table = reflected.tables.get(table_name)
            if table is None:
                continue
            rows_by_table[table_name] = [
                dict(row)
                for row in connection.execute(select(table)).mappings()
            ]
    return rows_by_table


def _primary_key_values(rows_by_table):
    values = {}
    for table in db.metadata.sorted_tables:
        primary_key_columns = list(table.primary_key.columns)
        if len(primary_key_columns) != 1:
            continue
        key_name = primary_key_columns[0].name
        values[table.name] = {
            row[key_name]
            for row in rows_by_table.get(table.name, [])
            if row.get(key_name) is not None
        }
    return values


def _repair_nullable_orphans(rows_by_table):
    primary_keys = _primary_key_values(rows_by_table)
    repaired = []
    for table in db.metadata.sorted_tables:
        rows = rows_by_table.get(table.name, [])
        if not rows:
            continue
        for foreign_key in table.foreign_keys:
            column = foreign_key.parent
            referred_table = foreign_key.column.table.name
            valid_values = primary_keys.get(referred_table, set())
            for row in rows:
                value = row.get(column.name)
                if value is None or value in valid_values:
                    continue
                if not column.nullable:
                    raise RuntimeError(
                        f'Cannot migrate orphaned non-null foreign key '
                        f'{table.name}.{column.name}={value}.'
                    )
                row[column.name] = None
                repaired.append({
                    'table': table.name,
                    'column': column.name,
                    'value': value,
                })
    return repaired


def _assert_target_empty(target_engine, table_names):
    existing = set(inspect(target_engine).get_table_names())
    with target_engine.connect() as connection:
        for table in db.metadata.sorted_tables:
            if table.name not in existing or table.name not in table_names:
                continue
            count = connection.execute(
                select(func.count()).select_from(table)
            ).scalar_one()
            if count:
                raise RuntimeError(
                    f'Target database is not empty: {table.name} has {count} row(s).'
                )


def _reset_postgres_sequences(connection, copied_tables):
    if connection.dialect.name != 'postgresql':
        return
    preparer = connection.dialect.identifier_preparer
    for table in db.metadata.sorted_tables:
        if table.name not in copied_tables:
            continue
        primary_key_columns = list(table.primary_key.columns)
        if len(primary_key_columns) != 1:
            continue
        primary_key = primary_key_columns[0]
        if not isinstance(primary_key.type.python_type, type) or (
            primary_key.type.python_type is not int
        ):
            continue
        quoted_table = preparer.quote(table.name)
        quoted_column = preparer.quote(primary_key.name)
        connection.execute(text(
            "SELECT setval("
            f"pg_get_serial_sequence('{table.name}', '{primary_key.name}'), "
            f"COALESCE((SELECT MAX({quoted_column}) FROM {quoted_table}), 1), "
            f"EXISTS(SELECT 1 FROM {quoted_table})"
            ")"
        ))


def copy_database(source_engine, target_engine):
    source_table_names = set(inspect(source_engine).get_table_names())
    model_table_names = {
        table.name
        for table in db.metadata.sorted_tables
    }
    copied_table_names = source_table_names & model_table_names
    if not copied_table_names:
        raise RuntimeError('Source database contains no ToolIb tables.')

    db.metadata.create_all(bind=target_engine)
    _assert_target_empty(target_engine, copied_table_names)

    rows_by_table = _source_rows(source_engine, copied_table_names)
    repaired = _repair_nullable_orphans(rows_by_table)
    copied_counts = {}

    with target_engine.begin() as connection:
        for table in db.metadata.sorted_tables:
            rows = rows_by_table.get(table.name)
            if not rows:
                copied_counts[table.name] = 0
                continue
            target_columns = set(table.columns.keys())
            payload = [
                {
                    key: value
                    for key, value in row.items()
                    if key in target_columns
                }
                for row in rows
            ]
            connection.execute(table.insert(), payload)
            copied_counts[table.name] = len(payload)
        _reset_postgres_sequences(connection, copied_table_names)

    with target_engine.connect() as connection:
        for table in db.metadata.sorted_tables:
            expected = copied_counts.get(table.name, 0)
            if table.name not in copied_table_names:
                continue
            actual = connection.execute(
                select(func.count()).select_from(table)
            ).scalar_one()
            if actual != expected:
                raise RuntimeError(
                    f'Row-count verification failed for {table.name}: '
                    f'expected {expected}, found {actual}.'
                )

    return {
        'tables': copied_counts,
        'total_rows': sum(copied_counts.values()),
        'repaired_nullable_foreign_keys': repaired,
    }


def build_parser():
    parser = argparse.ArgumentParser(
        description=(
            'Copy the current ToolIb SQLite database into an empty PostgreSQL '
            'database, preserving IDs and verifying row counts.'
        ),
    )
    parser.add_argument(
        '--source-uri',
        default=default_sqlite_uri(),
        help='Source SQLAlchemy URI. Defaults to local yolo_labeling.db.',
    )
    parser.add_argument(
        '--target-uri',
        default=os.environ.get('YOLO_LABELING_DB_URI'),
        help='Empty target SQLAlchemy URI. Defaults to YOLO_LABELING_DB_URI.',
    )
    return parser


def main():
    args = build_parser().parse_args()
    source_uri = normalize_database_uri(args.source_uri)
    target_uri = normalize_database_uri(args.target_uri)
    if not target_uri:
        raise SystemExit(
            '--target-uri or YOLO_LABELING_DB_URI is required.'
        )
    if source_uri == target_uri:
        raise SystemExit('Source and target database URIs must be different.')

    source_engine = create_engine(source_uri)
    target_engine = create_engine(target_uri, pool_pre_ping=True)
    try:
        report = copy_database(source_engine, target_engine)
        print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    finally:
        source_engine.dispose()
        target_engine.dispose()


if __name__ == '__main__':
    main()
