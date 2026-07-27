import os
import subprocess
import sys
from pathlib import Path

from cryptography.fernet import Fernet
from sqlalchemy import create_engine, inspect


REQUIRED_TABLES = {
    'projects',
    'training_workers',
    'training_batches',
    'training_queue_tasks',
    'training_job_attempts',
    'training_job_events',
}
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def test_preinitialized_sqlite_supports_concurrent_app_process_startup(tmp_path):
    database_path = tmp_path / 'fresh-startup.db'
    database_uri = f'sqlite:///{database_path.as_posix()}'
    environment = os.environ.copy()
    environment.update({
        'YOLO_LABELING_DB_URI': database_uri,
        'TOOLIB_WORKER_CREDENTIAL_KEY': Fernet.generate_key().decode('ascii'),
    })
    bootstrap_command = [
        sys.executable,
        '-c',
        'from app import create_app; create_app()',
    ]

    bootstrap = subprocess.run(
        bootstrap_command,
        cwd=str(REPOSITORY_ROOT),
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert bootstrap.returncode == 0, bootstrap.stderr

    processes = [
        subprocess.Popen(
            bootstrap_command,
            cwd=str(REPOSITORY_ROOT),
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for _ in range(2)
    ]
    results = [process.communicate(timeout=30) for process in processes]

    for process, (_stdout, stderr) in zip(processes, results):
        assert process.returncode == 0, stderr

    engine = create_engine(database_uri)
    try:
        assert REQUIRED_TABLES.issubset(inspect(engine).get_table_names())
    finally:
        engine.dispose()
