import json
import sys
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from training_model_catalog import (  # noqa: E402
    ENABLED_TRAINING_MODEL_CHECKPOINTS,
    TRAINING_MODEL_CATALOG_HASH,
    TRAINING_MODEL_CATALOG_VERSION,
)
from training_parameter_catalog import (  # noqa: E402
    TRAINING_PARAMETER_ALWAYS_FORWARD_FIELDS,
    TRAINING_PARAMETER_CATALOG_HASH,
    TRAINING_PARAMETER_CATALOG_VERSION,
    TRAINING_PARAMETER_CONTRACT_VERSION,
    TRAINING_PARAMETER_EFFECTIVE_FIELDS,
    TRAINING_PARAMETER_FIELD_SPECS,
    TRAINING_PARAMETER_SET_FORWARD_FIELDS,
)


NOTEBOOK_PATH = REPOSITORY_ROOT / 'notebooks' / 'Colab_FastAPI_PoC.ipynb'
WORKER_SOURCE_PATH = REPOSITORY_ROOT / 'notebooks' / 'colab_worker_phase6.py'
TARGET_CELL_INDEX = 3
INTRODUCTION_CELL_INDEX = 0
CLEANUP_CELL_INDEX = 6
WORKER_CATALOG_START = '# BEGIN GENERATED TRAINING MODEL CATALOG'
WORKER_CATALOG_END = '# END GENERATED TRAINING MODEL CATALOG'
WORKER_PARAMETER_START = '# BEGIN GENERATED TRAINING PARAMETER CATALOG'
WORKER_PARAMETER_END = '# END GENERATED TRAINING PARAMETER CATALOG'

INTRODUCTION_MARKDOWN = """# ToolIbV2 Colab Training API PoC

Notebook này chạy một FastAPI worker tạm thời trên Google Colab, public bằng Cloudflare Quick Tunnel và xử lý tối đa một job Ultralytics YOLO detection tại một thời điểm.

Luồng truyền dữ liệu:

- Mặc định: ToolIb upload mỗi snapshot dataset/parent model lên S3 hoặc Cloudflare R2 một lần; worker tải trực tiếp bằng presigned HTTPS URL rồi train trên local disk của Colab.
- Kết quả `best.pt`, `best.onnx`, `last.pt`, manifest và metrics được worker upload thẳng lên object storage; ToolIb tải từ đó về central artifact store.
- Google Drive và upload/download qua Quick Tunnel vẫn được giữ làm fallback tương thích khi object storage chưa bật.
- API dùng Bearer token lấy từ Colab Secret `TOOLIB_COLAB_API_TOKEN`; presigned URL không xuất hiện trong trạng thái job.
- Quick Tunnel chỉ truyền lệnh điều khiển và polling khi object transport hoạt động; đây vẫn là endpoint tạm thời, không phải production endpoint.

Chạy các cell từ trên xuống. Không chạy lại cell API trong lúc model đang train.
"""

CLEANUP_MARKDOWN = """## Hoàn tất và cleanup

Khi job thành công, ToolIb tự tải artifact từ object storage và import model. Chỉ dùng `MyDrive/ToolIb_PoC/artifacts/<job_id>/` khi hệ thống đang chạy fallback cũ.

Khi test xong:

```python
if TUNNEL_PROCESS.poll() is None:
    TUNNEL_PROCESS.terminate()
UVICORN_SERVER.should_exit = True
TRAIN_EXECUTOR.shutdown(wait=False, cancel_futures=True)
```

Disconnect Colab runtime để giải phóng GPU. URL Quick Tunnel sẽ không còn sử dụng được sau khi tunnel hoặc runtime dừng.
"""


def render_worker_catalog_block():
    allowed_models = ', '.join(
        json.dumps(checkpoint)
        for checkpoint in ENABLED_TRAINING_MODEL_CHECKPOINTS
    )
    return '\n'.join((
        WORKER_CATALOG_START,
        f'TRAINING_MODEL_CATALOG_VERSION = {json.dumps(TRAINING_MODEL_CATALOG_VERSION)}',
        f'TRAINING_MODEL_CATALOG_HASH = {json.dumps(TRAINING_MODEL_CATALOG_HASH)}',
        f'ALLOWED_MODELS = {{{allowed_models}}}',
        WORKER_CATALOG_END,
    ))


def _python_literal(value):
    return repr(value)


def _render_literal_type(values):
    return 'Literal[' + ', '.join(_python_literal(value) for value in values) + ']'


def render_worker_parameter_field(field):
    field_type = field['type']
    default = field.get('worker_default', field['default'])
    if field_type == 'integer':
        annotation = 'int'
    elif field_type in {'number', 'nullable_number'}:
        annotation = 'float' + (' | None' if field_type == 'nullable_number' else '')
    elif field_type == 'boolean':
        annotation = 'bool'
    elif field_type == 'enum':
        annotation = _render_literal_type(
            option['value'] for option in field['options']
        )
    elif field_type == 'boolean_or_enum':
        annotation = 'bool | ' + _render_literal_type(
            option['value'] for option in field['options']
        )
    else:
        raise ValueError(f'Unsupported worker field type: {field_type}.')

    constraints = []
    if field.get('minimum') is not None:
        constraints.append(f'ge={_python_literal(field["minimum"])}')
    if field.get('exclusive_minimum') is not None:
        constraints.append(
            f'gt={_python_literal(field["exclusive_minimum"])}'
        )
    if field.get('maximum') is not None:
        constraints.append(f'le={_python_literal(field["maximum"])}')
    default_source = _python_literal(default)
    if constraints or field_type == 'nullable_number':
        arguments = ', '.join([f'default={default_source}', *constraints])
        default_source = f'Field({arguments})'
    return f'    {field["name"]}: {annotation} = {default_source}'


def _render_tuple(name, values):
    lines = [f'{name} = (']
    lines.extend(f'    {_python_literal(value)},' for value in values)
    lines.append(')')
    return lines


def render_worker_parameter_block():
    lines = [
        WORKER_PARAMETER_START,
        (
            'TRAINING_PARAMETER_CATALOG_VERSION = '
            f'{_python_literal(TRAINING_PARAMETER_CATALOG_VERSION)}'
        ),
        (
            'TRAINING_PARAMETER_CATALOG_HASH = '
            f'{_python_literal(TRAINING_PARAMETER_CATALOG_HASH)}'
        ),
        (
            'TRAINING_PARAMETER_CONTRACT_VERSION = '
            f'{TRAINING_PARAMETER_CONTRACT_VERSION}'
        ),
    ]
    lines.extend(_render_tuple(
        'TRAINING_PARAMETER_ALWAYS_FORWARD_FIELDS',
        TRAINING_PARAMETER_ALWAYS_FORWARD_FIELDS,
    ))
    lines.extend(_render_tuple(
        'TRAINING_PARAMETER_SET_FORWARD_FIELDS',
        TRAINING_PARAMETER_SET_FORWARD_FIELDS,
    ))
    lines.extend(_render_tuple(
        'TRAINING_PARAMETER_EFFECTIVE_FIELDS',
        TRAINING_PARAMETER_EFFECTIVE_FIELDS,
    ))
    lines.extend(('', 'class TrainingParameterRequest(BaseModel):'))
    lines.extend(
        render_worker_parameter_field(field)
        for field in TRAINING_PARAMETER_FIELD_SPECS
    )
    lines.extend(('', WORKER_PARAMETER_END))
    return '\n'.join(lines)


def _replace_generated_block(source, start_marker, end_marker, content):
    start = source.find(start_marker)
    end = source.find(end_marker)
    if start < 0 or end < start:
        raise RuntimeError(f'Worker generation markers are missing: {start_marker}.')
    end += len(end_marker)
    return source[:start] + content + source[end:]


def sync_worker_catalog():
    source = WORKER_SOURCE_PATH.read_text(encoding='utf-8')
    generated_source = _replace_generated_block(
        source,
        WORKER_CATALOG_START,
        WORKER_CATALOG_END,
        render_worker_catalog_block(),
    )
    generated_source = _replace_generated_block(
        generated_source,
        WORKER_PARAMETER_START,
        WORKER_PARAMETER_END,
        render_worker_parameter_block(),
    )
    if generated_source != source:
        WORKER_SOURCE_PATH.write_text(generated_source, encoding='utf-8')


def main():
    sync_worker_catalog()
    notebook = json.loads(NOTEBOOK_PATH.read_text(encoding='utf-8'))
    cells = notebook.get('cells') or []
    if len(cells) <= TARGET_CELL_INDEX:
        raise RuntimeError('Colab notebook does not contain the worker cell.')
    target_cell = cells[TARGET_CELL_INDEX]
    if target_cell.get('cell_type') != 'code':
        raise RuntimeError('Phase 6 worker target is not a code cell.')

    source = WORKER_SOURCE_PATH.read_text(encoding='utf-8')
    if not source.startswith(
        '# 3. Define the authenticated FastAPI app'
    ):
        raise RuntimeError('Unexpected Phase 6 worker source header.')
    target_cell['source'] = source.splitlines(keepends=True)
    target_cell['execution_count'] = None
    target_cell['outputs'] = []
    cells[INTRODUCTION_CELL_INDEX]['source'] = (
        INTRODUCTION_MARKDOWN.splitlines(keepends=True)
    )
    cells[CLEANUP_CELL_INDEX]['source'] = (
        CLEANUP_MARKDOWN.splitlines(keepends=True)
    )
    NOTEBOOK_PATH.write_text(
        json.dumps(notebook, ensure_ascii=False, indent=1) + '\n',
        encoding='utf-8',
    )
    print(f'Synced {WORKER_SOURCE_PATH.name} into {NOTEBOOK_PATH.name}.')


if __name__ == '__main__':
    main()
