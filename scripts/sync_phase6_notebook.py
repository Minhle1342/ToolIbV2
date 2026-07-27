import json
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
NOTEBOOK_PATH = REPOSITORY_ROOT / 'notebooks' / 'Colab_FastAPI_PoC.ipynb'
WORKER_SOURCE_PATH = REPOSITORY_ROOT / 'notebooks' / 'colab_worker_phase6.py'
TARGET_CELL_INDEX = 3


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
    NOTEBOOK_PATH.write_text(
        json.dumps(notebook, ensure_ascii=False, indent=1) + '\n',
        encoding='utf-8',
    )
    print(f'Synced {WORKER_SOURCE_PATH.name} into {NOTEBOOK_PATH.name}.')


if __name__ == '__main__':
    main()
