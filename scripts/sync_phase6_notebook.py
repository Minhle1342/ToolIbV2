import json
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
NOTEBOOK_PATH = REPOSITORY_ROOT / 'notebooks' / 'Colab_FastAPI_PoC.ipynb'
WORKER_SOURCE_PATH = REPOSITORY_ROOT / 'notebooks' / 'colab_worker_phase6.py'
TARGET_CELL_INDEX = 3
INTRODUCTION_CELL_INDEX = 0
CLEANUP_CELL_INDEX = 6

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


def main():
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
