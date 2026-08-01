from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def test_colab_manager_exposes_phase5_worker_batch_and_reconnect_controls():
    template = (
        REPOSITORY_ROOT / 'templates' / 'colab_manager.html'
    ).read_text(encoding='utf-8')

    required_contract = (
        'trainingWorkerRegisterBtn',
        'colabRemoteEndpoint',
        'colabRemoteToken',
        'trainingBatchProjects',
        'trainingBatchCreateBtn',
        'trainingBatchList',
        'registerCurrentColabWorker()',
        'async function reconnectTrainingWorker(',
        'async function createAutomatedTrainingBatch()',
        'async function createUnifiedTrainingExperiment()',
        'async function dispatchTrainingControlPlane(',
        '/api/training-control-plane/status',
        'Chờ kết nối lại',
        'latestAttempt',
        'latestEvent',
        'finetunePhase6Panel',
        'finetuneParentFile',
        'finetuneParentModel',
        'trainingProjects = projects',
        'function hydrateTrainingProjectClasses(projects)',
        '/api/projects/${project.id}/classes',
        'function renderFinetuneParentModels()',
        'canonicalFinetuneClassNames',
        'sameFinetuneClassNames',
        'class_names',
        'trainingExperimentMode',
        'finetuneOnlyFields',
        'finetuneParameterSetList',
        'finetuneParameterSetSelectionSummary',
        'finetuneParameterSetModal',
        'openFinetuneParameterSetEditor(',
        'finetuneParameterPrimaryGroups',
        'updateFinetuneParameterDependencies',
        'auto optimizer · lr0 delegated',
        'task.requested_config || task.request || {}',
        'task.effective_config.optimizer_class',
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
        'cải thiện model ${supportsFinetune ? "được hỗ trợ" : "chưa hỗ trợ"}',
        'legacyRemoteColabPanel',
        'legacyCodeGeneratorPanel',
        'toggleLegacyCodeGenerator()',
    )
    for marker in required_contract:
        assert marker in template


def test_colab_manager_primary_flow_is_sequential_and_non_technical():
    template = (
        REPOSITORY_ROOT / 'templates' / 'colab_manager.html'
    ).read_text(encoding='utf-8')

    ordered_steps = (
        'id="trainingModelStep"',
        'id="trainingDatasetStep"',
        'id="finetunePhase6Panel"',
        'id="trainingReviewCard"',
        'id="trainingProgressStep"',
    )
    positions = [template.index(marker) for marker in ordered_steps]
    assert positions == sorted(positions)
    assert template.index('id="trainingResourceBanner"') < template.index(
        'id="trainingModelStep"'
    )
    assert template.index('id="trainingWorkerSetupPanel"') > template.index(
        'id="trainingProgressStep"'
    )

    for marker in (
        'id="nonTechnicalTrainingFlow"',
        'Huấn luyện mô hình YOLO',
        'Tài nguyên huấn luyện',
        'Đăng ký Colab',
        'Thiết lập máy huấn luyện',
        'Bắt đầu huấn luyện model mới',
        'Dữ liệu dùng để học (%)',
        'hệ thống tự chọn cách học',
        'function renderTrainingReview()',
        'function renderTrainingResourceStatus()',
        'function openTrainingWorkerSetup()',
        'function trainingStatusLabel(status)',
        'function friendlyParameterSetName(parameterSet)',
        'Công cụ cũ dành cho kỹ thuật',
    ):
        assert marker in template

    for leaked_label in (
        'Phase 5 · Multi-worker Training Control Plane',
        'Phase 6 ${supportsFinetune',
        'Đang xác thực parent bằng Phase 6 worker',
        'Scheduler & batches',
        'Queue fresh training jobs',
        'Queue fine-tune jobs',
        'Đang tải catalog...',
    ):
        assert leaked_label not in template

    assert (
        'id="legacyRemoteColabPanel" class="hidden '
        in template
    )


def test_colab_manager_uses_database_parameter_sets_not_candidate_counts():
    template = (
        REPOSITORY_ROOT / 'templates' / 'colab_manager.html'
    ).read_text(encoding='utf-8')

    assert 'finetuneSelectedParameterSetIds' in template
    assert 'finetuneCandidateCount' not in template
    assert 'candidate_count:' not in template
    assert 'parameter_set_id: parameterSetId' in template
    assert 'training_mode: "fresh"' in template


def test_colab_manager_primary_training_ui_only_lists_supported_detection_models():
    template = (
        REPOSITORY_ROOT / 'templates' / 'colab_manager.html'
    ).read_text(encoding='utf-8')

    assert 'id="trainingModelCatalogSummary"' in template
    assert 'localTrainingApiFetch("/api/training-model-catalog")' in template
    assert 'function applyTrainingModelCatalog(catalog)' in template
    assert 'function populateTrainingModelFamilies(' in template
    assert 'model => model.family === family' in template
    assert 'trainingModelAllowedCheckpoints.has(state.model_version)' in template
    assert 'YOLO_CHECKPOINTS_MAP' not in template
    assert 'COLAB_REMOTE_ALLOWED_MODELS' not in template
    assert '<option value="segment">' not in template
    assert '<option value="classify">' not in template
    assert '<option value="pose">' not in template
    assert 'id="task_type" type="hidden" value="detect"' in template


def test_colab_manager_remote_training_accepts_image_sizes_through_1024():
    template = (
        REPOSITORY_ROOT / 'templates' / 'colab_manager.html'
    ).read_text(encoding='utf-8')

    assert '<option value="768">768 px</option>' in template
    assert '<option value="1024">1024 px (High Res)</option>' in template
    assert 'new Set([320, 416, 512, 640, 768, 1024])' in template
    assert '320, 416, 512, 640, 768, 1024.' in template
    assert '1280' not in template


def test_finetune_submit_has_immediate_feedback_and_idempotency_guard():
    template = (
        REPOSITORY_ROOT / 'templates' / 'colab_manager.html'
    ).read_text(encoding='utf-8')

    for marker in (
        'id="finetuneExperimentSubmitStatus"',
        'aria-live="polite"',
        'let finetuneExperimentSubmitting = false;',
        'let finetunePendingSubmission = null;',
        'if (finetuneExperimentSubmitting)',
        'finetuneExperimentSubmitting = true;',
        'window.crypto.randomUUID()',
        '"Idempotency-Key":',
        'requestBody.idempotency_key',
        'button.setAttribute("aria-busy", "true")',
        'fa-spinner fa-spin',
        'không cần bấm lại',
        'experiment.idempotent_replay',
        'scrollIntoView({',
        'card.id = `training-batch-${batch.id}`',
    ):
        assert marker in template


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


def test_colab_manager_exposes_phase_c_parameter_editor_without_legacy_drift():
    template = (
        REPOSITORY_ROOT / 'templates' / 'colab_manager.html'
    ).read_text(encoding='utf-8')

    for marker in (
        'id="finetuneParameterPrimaryGroups"',
        'id="finetuneParameterAdvancedGroups"',
        'finetuneConfig?.parameter_catalog',
        'function renderFinetuneParameterEditor()',
        'function createFinetuneParameterControl(field)',
        '["boolean", "enum", "boolean_or_enum"]',
        'field.options || []',
        'field.ui?.visible_when',
        'field.ui?.exclude_values',
        'renderFinetuneParameterEditor();',
        'Công cụ cũ dành cho kỹ thuật',
    ):
        assert marker in template


def test_colab_manager_displays_requested_and_effective_phase_c_arguments():
    template = (
        REPOSITORY_ROOT / 'templates' / 'colab_manager.html'
    ).read_text(encoding='utf-8')

    for marker in (
        'function summarizeTrainingParameters(values)',
        'field.ui?.summary',
        'requestedParameters = summarizeTrainingParameters(',
        'task.effective_config.training_arguments',
        'Runtime ${summarizeTrainingParameters(',
    ):
        assert marker in template
