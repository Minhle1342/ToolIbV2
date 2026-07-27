from sqlalchemy import event, inspect, text
from sqlalchemy.exc import SQLAlchemyError


RUNTIME_COLUMNS = (
    (
        'ai_models',
        'model_type',
        "model_type VARCHAR(50) DEFAULT 'detection'",
    ),
    (
        'ai_models',
        'activation_ready',
        'activation_ready BOOLEAN NOT NULL DEFAULT TRUE',
    ),
    (
        'ai_models',
        'parent_model_id',
        'parent_model_id INTEGER',
    ),
    (
        'ai_models',
        'source_project_id',
        'source_project_id INTEGER',
    ),
    (
        'ai_models',
        'training_dataset_id',
        'training_dataset_id INTEGER',
    ),
    (
        'ai_models',
        'source_kind',
        "source_kind VARCHAR(40) NOT NULL DEFAULT 'manual_onnx'",
    ),
    (
        'ai_models',
        'finetune_status',
        "finetune_status VARCHAR(30) NOT NULL DEFAULT 'unavailable'",
    ),
    (
        'ai_models',
        'class_names',
        'class_names JSON',
    ),
    (
        'ai_models',
        'validation_error',
        'validation_error TEXT',
    ),
    (
        'ai_models',
        'validated_at',
        'validated_at TIMESTAMP',
    ),
    (
        'training_jobs',
        'training_dataset_id',
        'training_dataset_id INTEGER',
    ),
    (
        'training_jobs',
        'dataset_id',
        'dataset_id VARCHAR(36)',
    ),
    (
        'training_jobs',
        'training_mode',
        "training_mode VARCHAR(30) NOT NULL DEFAULT 'fresh'",
    ),
    (
        'training_jobs',
        'parent_model_id',
        'parent_model_id INTEGER',
    ),
    (
        'training_jobs',
        'metrics',
        'metrics JSON',
    ),
    (
        'training_batches',
        'experiment_type',
        "experiment_type VARCHAR(30) NOT NULL DEFAULT 'fresh'",
    ),
    (
        'training_batches',
        'parent_model_id',
        'parent_model_id INTEGER',
    ),
    (
        'training_batches',
        'training_dataset_id',
        'training_dataset_id INTEGER',
    ),
    (
        'training_batches',
        'preset_version',
        'preset_version VARCHAR(50)',
    ),
    (
        'training_batches',
        'ranking_metric',
        "ranking_metric VARCHAR(80) DEFAULT 'metrics/mAP50-95(B)'",
    ),
    (
        'training_queue_tasks',
        'parent_model_id',
        'parent_model_id INTEGER',
    ),
    (
        'training_queue_tasks',
        'parameter_set_id',
        'parameter_set_id INTEGER',
    ),
    (
        'training_queue_tasks',
        'parameter_set_snapshot',
        'parameter_set_snapshot JSON',
    ),
    (
        'training_queue_tasks',
        'candidate_name',
        'candidate_name VARCHAR(100)',
    ),
    (
        'training_queue_tasks',
        'config_hash',
        'config_hash VARCHAR(64)',
    ),
    (
        'training_queue_tasks',
        'metrics',
        'metrics JSON',
    ),
    (
        'training_workers',
        'remote_active_job_id',
        'remote_active_job_id VARCHAR(36)',
    ),
)

RUNTIME_INDEXES = (
    (
        'ai_models',
        'ix_ai_models_parent_model_id',
        'parent_model_id',
    ),
    (
        'ai_models',
        'ix_ai_models_source_project_id',
        'source_project_id',
    ),
    (
        'ai_models',
        'ix_ai_models_training_dataset_id',
        'training_dataset_id',
    ),
    (
        'ai_models',
        'ix_ai_models_source_kind',
        'source_kind',
    ),
    (
        'ai_models',
        'ix_ai_models_finetune_status',
        'finetune_status',
    ),
    (
        'training_jobs',
        'ix_training_jobs_training_mode',
        'training_mode',
    ),
    (
        'training_jobs',
        'ix_training_jobs_parent_model_id',
        'parent_model_id',
    ),
    (
        'training_batches',
        'ix_training_batches_experiment_type',
        'experiment_type',
    ),
    (
        'training_batches',
        'ix_training_batches_parent_model_id',
        'parent_model_id',
    ),
    (
        'training_batches',
        'ix_training_batches_training_dataset_id',
        'training_dataset_id',
    ),
    (
        'training_queue_tasks',
        'ix_training_queue_tasks_parent_model_id',
        'parent_model_id',
    ),
    (
        'training_queue_tasks',
        'ix_training_queue_tasks_parameter_set_id',
        'parameter_set_id',
    ),
    (
        'training_queue_tasks',
        'ix_training_queue_tasks_config_hash',
        'config_hash',
    ),
    (
        'training_workers',
        'ix_training_workers_remote_active_job_id',
        'remote_active_job_id',
    ),
)


def normalize_database_uri(value):
    uri = str(value or '').strip()
    if uri.startswith('postgres://'):
        return 'postgresql+psycopg://' + uri[len('postgres://'):]
    if uri.startswith('postgresql://'):
        return 'postgresql+psycopg://' + uri[len('postgresql://'):]
    return uri


def engine_options_for_uri(database_uri):
    normalized = normalize_database_uri(database_uri)
    if normalized.startswith('postgresql+'):
        return {
            'pool_pre_ping': True,
            'pool_recycle': 300,
        }
    if normalized.startswith('sqlite:'):
        return {
            'connect_args': {
                'timeout': 30,
            },
        }
    return {'pool_pre_ping': True}


def _enable_sqlite_foreign_keys(dbapi_connection, _connection_record):
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute('PRAGMA foreign_keys=ON')
    finally:
        cursor.close()


def configure_database_engine(engine):
    if engine.dialect.name != 'sqlite':
        return
    if not event.contains(engine, 'connect', _enable_sqlite_foreign_keys):
        event.listen(engine, 'connect', _enable_sqlite_foreign_keys)
    with engine.connect() as connection:
        connection.execute(text('PRAGMA foreign_keys=ON'))


def _column_names(engine, table_name):
    inspector = inspect(engine)
    if table_name not in inspector.get_table_names():
        return set()
    return {
        column['name']
        for column in inspector.get_columns(table_name)
    }


def ensure_runtime_columns(engine):
    for table_name, column_name, column_ddl in RUNTIME_COLUMNS:
        if column_name in _column_names(engine, table_name):
            continue
        try:
            with engine.begin() as connection:
                connection.execute(text(
                    f'ALTER TABLE {table_name} ADD COLUMN {column_ddl}'
                ))
        except SQLAlchemyError:
            # A second startup process may have added the same column after
            # this process inspected the schema.
            if column_name not in _column_names(engine, table_name):
                raise

    for table_name, index_name, column_name in RUNTIME_INDEXES:
        if column_name not in _column_names(engine, table_name):
            continue
        with engine.begin() as connection:
            connection.execute(text(
                f'CREATE INDEX IF NOT EXISTS {index_name} '
                f'ON {table_name} ({column_name})'
            ))


def repair_orphaned_training_references(engine):
    tables = set(inspect(engine).get_table_names())
    if not {'training_queue_tasks', 'training_jobs'}.issubset(tables):
        return 0

    with engine.begin() as connection:
        result = connection.execute(text(
            'UPDATE training_queue_tasks '
            'SET training_job_id = NULL '
            'WHERE training_job_id IS NOT NULL '
            'AND NOT EXISTS ('
            'SELECT 1 FROM training_jobs '
            'WHERE training_jobs.id = training_queue_tasks.training_job_id'
            ')'
        ))
    return max(int(result.rowcount or 0), 0)
