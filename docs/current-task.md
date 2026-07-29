# Current Task Handoff - Phase C2 Training Parameter Catalog

Updated: 2026-07-29, Asia/Bangkok

Repository: `C:\Users\Minh\OneDrive\Desktop\lb\ToolIbV2`

No commit was created. The worktree remains heavily dirty and contains
unrelated user changes. Phase C2 is implemented and locally validated. Live
browser/Colab acceptance is still pending because Flask, the scheduler, and
Colab workers are not running.

## 1. Muc tieu cuoi cung

Cho phep Fresh training va Fine-tune dieu khien mot training contract YOLO
detection co the mo rong ma khong lap hard-code giua backend, UI va Colab
worker.

Phase C2 dat mot catalog duy nhat lam source of truth, tang contract tu 31 len
39 fields, generate worker/notebook tu catalog, va giu requested/effective
config, immutable snapshot, retry/resume, optimizer auto/explicit, Phase A
model catalog va unified Fresh/Fine-tune.

## 2. Yeu cau va pham vi da xac nhan

- Them 8 controls Phase C2:
  - `multi_scale`, `fraction`;
  - `box`, `cls`, `dfl`, `nbs`;
  - `compile`, `channels_last`.
- Giu 31 fields Phase C1, tong cong 39 fields.
- Backend, UI va worker khong duoc co danh sach tham so doc lap lam source of
  truth.
- Preset cu thieu C1/C2 fields normalize bang defaults tu catalog.
- Fresh legacy khong dung Parameter Set van giu worker defaults cu.
- Parameterized Fresh/Fine-tune chi dispatch sang worker dung contract va dung
  parameter catalog hash.
- Requested config va runtime effective arguments van tach biet.
- Khong rename/drop `FineTuneParameterSet`.
- Khong mo rong model scales `n/m/l/x`.
- Khong them random scratch mode.
- Khong sua notebook cell bang tay.
- Khong chay migration hoac commit khi chua duoc yeu cau.

## 3. Quyet dinh ky thuat da chot va ly do

### Catalog duy nhat

- Catalog: `config/training_parameter_catalog.json`.
- Loader/validator: `training_parameter_catalog.py`.
- Catalog version: `phase-c2-training-v1`.
- Contract version: `3`.
- Catalog hash:
  `b201f355fffc6e3dc17ac540e7d22a1db2da9cd8c202e5cc53d9c61394a9f752`.
- Catalog ghi ro type, default, worker default, min/max, enum options, forward
  mode, effective reporting va UI metadata cho tung field.
- Backend exports full schema qua `/api/finetune/config` trong
  `parameter_catalog`; UI render editor tu schema nay.
- `scripts/sync_phase6_notebook.py` generate Pydantic fields, forward lists,
  effective field lists, catalog version/hash vao worker, sau do sync worker
  source vao notebook.

### Ultralytics 8.4.110 semantics

- `multi_scale=0.0`, numeric range `[0, 1]`; day la range fraction cua `imgsz`,
  khong phai boolean.
- `fraction=1.0`, range `(0, 1]`.
- `box=7.5`, `cls=0.5`, `dfl=1.5`.
- `nbs=64`, range system ho tro `1..4096`.
- `compile=false`; UI cho chon:
  `default`, `reduce-overhead`, `max-autotune-no-cudagraphs`.
- `channels_last=false`.
- Loss gains duoc system gioi han `0..100` de chan payload vo ly truoc worker.

### Backward compatibility

- Parameter Set defaults la `epochs=50`, `batch=8` nhu truoc.
- Catalog co `worker_default` rieng cho legacy direct worker request:
  `epochs=1`, `batch=4`; do do khong tu doi Fresh legacy behavior.
- Legacy `cache=true/false/null` normalize thanh `ram/off/off`.
- Preset cu thieu `optimizer_mode` van normalize thanh auto, `optimizer=auto`,
  `lr0=null`.
- Auto optimizer khong forward `lr0`; explicit optimizer bat buoc named
  optimizer va `lr0`.
- Phase C2 khong can DB migration vi parameters/snapshots/effective config la
  JSON columns da co.

### Worker compatibility va drift protection

- Worker health advertise:
  - `training_parameter_contract_version: 3`;
  - `training_parameter_catalog_version: phase-c2-training-v1`;
  - exact parameter catalog hash;
  - optimizer contract v1, model catalog hash va Ultralytics pin nhu truoc.
- Parameterized task reject worker contract v2, worker v3 thieu hash, hoac
  worker co hash khac.
- Fresh legacy khong apply Parameter Set khong bi ep qua parameter catalog gate.
- Worker generic-forward fields tu generated tuples; khong con hand-written
  `train_kwargs` map cho tung parameter.
- Runtime capture `trainer.args` theo generated effective-field tuple, gom ca 8
  fields C2.

## 4. Nhung viec da hoan thanh

- Tao va validate catalog 39 fields co version/hash.
- Backend constants/defaults/options duoc derive tu catalog.
- Backend generic validation cho integer, number, nullable number, boolean,
  enum va boolean-or-enum.
- Backend giu optimizer auto/explicit cross-field contract.
- `/api/finetune/config` tra full parameter schema va hash.
- UI bo static input map; editor tao controls/groups/options/dependencies tu
  API catalog.
- UI optimizer/lr0 visibility duoc dieu khien boi catalog `visible_when`.
- UI Requested/Runtime summary lay danh sach field tu catalog `ui.summary`.
- Worker Pydantic parameter base class duoc generate tu catalog.
- Worker generic-forward all always/Parameter Set fields va special-case dung
  cho cache, close_mosaic va explicit lr0.
- Worker capture C2 runtime arguments vao
  `effective_config.training_arguments`.
- Scheduler gate contract v3 + exact catalog hash.
- Notebook regenerated tu worker source.
- Them catalog loader/drift tests, C2 validation/default/snapshot tests,
  generated worker contract tests, requested/effective tests va resume snapshot
  regression.

## 5. Cac file da tao hoac sua

### Tao moi trong Phase C2

- `config/training_parameter_catalog.json`
- `training_parameter_catalog.py`
- `tests/test_training_parameter_catalog.py`

### Sua trong Phase C2

- `training_control_plane.py`
- `templates/colab_manager.html`
- `notebooks/colab_worker_phase6.py`
- `notebooks/Colab_FastAPI_PoC.ipynb` (generated)
- `scripts/sync_phase6_notebook.py`
- `tests/test_training_control_plane.py`
- `tests/test_colab_phase4_contract.py`
- `tests/test_phase5_ui_contract.py`
- `docs/current-task.md`

### Phase A/B/C1 files phai giu

- `config/training_model_catalog.json`
- `training_model_catalog.py`
- `models.py`
- `database_support.py`
- `scripts/migrate_phase9_optimizer_contract.py`
- `tests/test_phase9_migration.py`

### Dirty changes ngoai Phase C2 phai giu nguyen

- `docs/colab_fastapi_poc_runbook.md`
- `inference.py`
- `routes.py` co catalog va unrelated hunks
- `static/js/api.js`
- `static/js/collaboration.js`
- `static/js/workspace.js`
- `templates/models_experiment.html`
- `utils.py`
- annotation/model-experiment docs/tests/artifacts khac trong `git status`

## 6. Trang thai runtime hien tai

Verified sau Phase C2:

- PostgreSQL/Docker listener: `127.0.0.1:54329`, owning PID `1408`.
- Khong co listener tren port `5000`.
- Khong co Flask process, `training_scheduler.py`, `run.ps1` runtime hoac Colab
  worker process.
- Codex khong start/stop/restart Flask, scheduler hoac worker.
- Khong query hoac thay doi live PostgreSQL schema/Phase 9 migration ledger.
- Khong co live API/UI/GPU acceptance trong Phase C2.

## 7. Test da chay va ket qua

### Focused Phase C2

Command:

```powershell
.\.venv\Scripts\python.exe -m pytest `
  tests\test_training_control_plane.py `
  tests\test_colab_phase4_contract.py `
  tests\test_phase5_ui_contract.py `
  tests\test_training_model_catalog.py `
  tests\test_training_parameter_catalog.py `
  tests\test_phase9_migration.py -q
```

Result: `76 passed, 1 warning`.

Coverage gom:

- exact 39-field catalog/defaults/version/hash;
- invalid fraction, multi_scale, nbs, compile va channels_last rejection;
- legacy defaults/cache aliases/optimizer auto normalization;
- C2 immutable Fresh snapshot;
- contract v2/hash mismatch worker rejection;
- requested/effective C2 reporting;
- retry/resume giu nguyen C2 request payload;
- generated worker declarations/forward/effective lists;
- UI schema-driven editor va summary markers;
- Phase A model catalog va Phase B migration regression.

### Full suite

Result: `148 passed, 6 skipped, 62 warnings, 8 subtests passed`.

### Static va generated-artifact checks

- Python compile: pass.
- Notebook JSON: pass, 7 cells.
- JavaScript syntax: pass, 1 inline script.
- Notebook sync idempotency: pass.
- Worker SHA-256:
  `32D4A768A8B7E3182D76A3E9CDB0282C59EB47126595CFA82807F9175CCCF5BC`.
- Notebook SHA-256:
  `58321141C1531EA741E9AC2C77403202815633094DD30763B0AD0E3D9F7AF15D`.
- `git diff --check`: pass; chi co existing LF/CRLF warnings.

### GitNexus

- Index freshness duoc verify truoc edit: ToolIbV2 indexed at commit `93fbb41`,
  `4860 nodes`, `18358 edges`, `300 processes`, khong bao stale.
- Pre-edit critical blast radius:
  - `_normalize_finetune_parameters`: 2 direct callers, 9 processes;
  - `normalize_finetune_parameter_set_parameters`: 6 direct callers,
    9 processes.
- `gitnexus_detect_changes(scope="all")` sau edit:
  - aggregate risk: `CRITICAL`;
  - 352 changed symbols;
  - 83 affected entries;
  - 18 tracked changed files.
- Aggregate CRITICAL gom nhieu unrelated inference, annotation,
  collaboration, dataset export va model-experiment changes. Expected Phase C2
  flows la preset CRUD/config, Fresh batch, Fine-tune experiment, scheduler
  dispatch, worker `start_train`, worker `run_training_job`, task sync va
  checkpoint resume.

## 8. Loi, blocker hoac dieu chua chac chan

- Chua browser-smoke `/colab-manager` vi Flask khong chay.
- Chua co Colab worker contract v3 online de verify Pydantic/runtime behavior
  tren GPU that.
- Chua co live evidence cho `compile` va `channels_last`; hai option nay phu
  thuoc GPU/PyTorch graph va co the tang startup time hoac khong co loi ich tren
  mot so model.
- `multi_scale > 0` co the tang VRAM peak; smoke nen bat dau voi `0.25` hoac
  giu `0.0`.
- `fraction < 1` la sampling cua Ultralytics, khong thay doi immutable dataset
  archive ma ToolIb da export.
- Loss gains `box/cls/dfl` la advanced controls; can accuracy experiment, khong
  danh gia bang contract smoke.
- Phase A/B/C1 live auto/explicit, YOLO12/YOLO26 va R2 acceptance van pending;
  local Phase C2 tests khong thay the cloud acceptance.
- Worktree heavily dirty; aggregate GitNexus risk khong the quy rieng cho Phase
  C2.

## 9. Cac buoc tiep theo theo dung thu tu

1. Chi khi nguoi dung cho phep, start runtime bang quy trinh hien co; khong tu
   dong start/restart.
2. Browser-smoke `/colab-manager`:
   - mo Add Parameter Set;
   - verify 39 controls render theo 5 catalog groups;
   - verify optimizer auto hide optimizer/lr0;
   - verify explicit show optimizer/lr0;
   - save/reopen mot C2 Parameter Set va doi chieu values.
3. Mo notebook generated tren Colab va dang ky worker. Health phai co:
   - `training_parameter_contract_version: 3`;
   - parameter catalog version `phase-c2-training-v1`;
   - parameter catalog hash
     `b201f355fffc6e3dc17ac540e7d22a1db2da9cd8c202e5cc53d9c61394a9f752`;
   - optimizer contract v1, dung model catalog hash va Ultralytics `8.4.110`.
4. Queue Fresh Auto smoke, de xuat `yolo12s.pt`, `epochs=2`, `batch=4`,
   `imgsz=512`, `fraction=0.5`, `multi_scale=0.0`, `compile=false`,
   `channels_last=false`.
5. Queue Fine-tune Explicit smoke, de xuat `yolo26s.pt` parent/imported parent,
   `AdamW + lr0=0.001`, `box=7.5`, `cls=0.5`, `dfl=1.5`, `nbs=64`.
6. Verify tung task tren UI/API/manifest:
   - requested config co du 39 fields;
   - effective optimizer class va initial LR;
   - `effective_config.training_arguments` co 36 runtime fields, gom 8 C2;
   - retry/resume giu nguyen request payload, snapshot va config hash.
7. Ghi task IDs, worker IDs, artifact paths va exact live evidence vao file
   nay.
8. Sau khi live acceptance pass moi chon phase tiep theo:
   - AutoBatch/OOM guard;
   - model scales `n/m/l/x`;
   - true random-initialization scratch mode;
   - Colab CLI lifecycle automation.
9. Chi chay Phase 9 migration ledger khi nguoi dung xac nhan deployment action.

## 10. Nhung viec khong duoc lam lai hoac khong duoc thay doi

- Khong rename/drop `FineTuneParameterSet`.
- Khong redo Phase A model catalog.
- Khong redo unified Fresh/Fine-tune.
- Khong dua static UI field map tro lai lam source of truth.
- Khong tao worker parameter declarations/forward list bang tay ngoai generated
  block.
- Khong sua notebook cell bang tay; chi sync tu worker source.
- Khong bo optimizer contract, model catalog hash, parameter catalog hash,
  allowlist hoac capability gates.
- Khong ep Parameter Set defaults len Fresh legacy request khong apply Parameter
  Set.
- Khong mutate stored legacy presets chi de them default fields.
- Khong backfill old task effective values bang suy doan.
- Khong thay doi immutable `request_payload`, `parameter_set_snapshot` hoac
  `config_hash` khi retry/resume.
- Khong goi official pretrained checkpoint flow la random scratch training.
- Khong mo `n/m/l/x` neu chua chot phase rieng.
- Khong danh dau YOLO12/YOLO26, compile, channels_last hoac C2 GPU behavior la
  live validated khi chua co Colab evidence.
- Khong start/stop/restart Flask, scheduler hoac worker neu chua duoc yeu cau.
- Khong revert/overwrite dirty changes ngoai Phase C2.
- Khong commit neu nguoi dung chua yeu cau.
