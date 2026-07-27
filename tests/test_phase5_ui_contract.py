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
        'finetunePhase6Panel',
        'finetuneParentFile',
        'finetuneParentModel',
        'finetuneProject',
        'finetuneParameterSetList',
        'finetuneParameterSetSelectionSummary',
        'finetuneParameterSetModal',
        'openFinetuneParameterSetEditor(',
        'saveFinetuneParameterSet()',
        'cloneFinetuneParameterSet(',
        'archiveFinetuneParameterSet(',
        'restoreFinetuneParameterSet(',
        'deleteFinetuneParameterSet(',
        'uploadFinetuneParentModel()',
        'async function createFinetuneExperiment()',
        '/api/finetune-models',
        '/api/finetune-parameter-sets',
        '/api/finetune-experiments',
        'parameter_set_ids: parameterSetIds',
        'shared dataset #',
        'Phase 6 ${supportsFinetune ? "ready" : "not supported"}',
    )
    for marker in required_contract:
        assert marker in template


def test_colab_manager_uses_database_parameter_sets_not_candidate_counts():
    template = (
        REPOSITORY_ROOT / 'templates' / 'colab_manager.html'
    ).read_text(encoding='utf-8')

    assert 'finetuneSelectedParameterSetIds' in template
    assert 'finetuneCandidateCount' not in template
    assert 'candidate_count:' not in template


def test_run_script_starts_and_stops_dedicated_scheduler_process():
    run_script = (REPOSITORY_ROOT / 'run.ps1').read_text(encoding='utf-8')

    database_bootstrap = (
        '& $PythonPath -c "from app import create_app; create_app()"'
    )
    assert database_bootstrap in run_script
    scheduler_start = '$schedulerProcess = Start-Process'
    assert run_script.index(database_bootstrap) < run_script.index(scheduler_start)
    assert 'Scheduler va Flask chua duoc khoi chay.' in run_script
    assert 'Start-Process' in run_script
    assert 'training_scheduler.py' in run_script
    assert 'try {' in run_script
    assert '} finally {' in run_script
    assert 'Stop-Process -Id $schedulerProcess.Id' in run_script
