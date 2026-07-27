from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def test_colab_manager_exposes_phase5_worker_batch_and_reconnect_controls():
    template = (
        REPOSITORY_ROOT / 'templates' / 'colab_manager.html'
    ).read_text(encoding='utf-8')

    required_contract = (
        'trainingWorkerRegisterBtn',
        'trainingBatchProjects',
        'trainingBatchCreateBtn',
        'trainingBatchList',
        'registerCurrentColabWorker()',
        'async function reconnectTrainingWorker(',
        'async function createAutomatedTrainingBatch()',
        'async function dispatchTrainingControlPlane(',
        '/api/training-control-plane/status',
        'Await reconnect',
        'latestAttempt',
        'latestEvent',
    )
    for marker in required_contract:
        assert marker in template


def test_run_script_starts_and_stops_dedicated_scheduler_process():
    run_script = (REPOSITORY_ROOT / 'run.ps1').read_text(encoding='utf-8')

    assert 'Start-Process' in run_script
    assert 'training_scheduler.py' in run_script
    assert 'try {' in run_script
    assert '} finally {' in run_script
    assert 'Stop-Process -Id $schedulerProcess.Id' in run_script
