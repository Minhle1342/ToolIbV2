# Implementation Plan: Class Conversion Button (Chuyển đổi)

**Branch**: `002-class-conversion-button` | **Date**: 2026-07-07 | **Spec**: [spec.md](file:///d:/Thuctap/ToolIb-main/ToolIb-main/specs/002-class-conversion-button/spec.md)

**Input**: Feature specification from `/specs/002-class-conversion-button/spec.md`

## Summary

Thêm nút "Chuyển đổi" (với icon `fa-right-left`) vào bên phải nút Upload trong sidebar header của workspace.html. Nút này mở popup cho phép chọn 1+ class hiện tại và merge/đổi tên thành 1 class mới. Backend endpoint `POST /api/projects/<id>/classes/merge` thực hiện: remap class IDs trong tất cả label files, cập nhật `classes.txt` và `data.yaml`, trả về thống kê. Frontend gọi API và refresh UI.

## Technical Context

**Language/Version**: Python 3.x (Flask backend), JavaScript (vanilla frontend)

**Primary Dependencies**: Flask, PyYAML, Font Awesome 6 (already in project)

**Storage**: File-based (classes.txt, data.yaml, YOLO .txt label files)

**Testing**: Manual verification (per project convention)

**Target Platform**: Web browser (desktop)

**Project Type**: Web application (Flask + Jinja2 templates)

## Constitution Check

*GATE: Pass — constitution is template/unfilled, no violations possible.*

## Project Structure

### Documentation (this feature)

```text
specs/002-class-conversion-button/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output
│   └── merge-classes-api.md
└── tasks.md             # Phase 2 output (via /speckit-tasks)
```

### Source Code (files to modify)

```text
templates/
└── workspace.html          # Add button + popup panel HTML

static/js/
└── workspace.js            # Add merge class logic + popup handling

routes.py                   # Add POST /api/projects/<id>/classes/merge endpoint
```

## Proposed Changes

### Component 1: Backend — Merge Classes API

#### [MODIFY] [routes.py](file:///d:/Thuctap/ToolIb-main/ToolIb-main/routes.py)

Add new endpoint after existing class management routes (after line ~792):

```python
@api_bp.route('/projects/<int:project_id>/classes/merge', methods=['POST'])
def merge_project_classes(project_id):
```

**Logic**:
1. Validate input: `source_class_indices` (int list) + `new_class_name` (string)
2. Get current classes via `utils.get_classes(project)`
3. Validate indices in range, validate name doesn't conflict with non-selected classes
4. Determine target_idx = min(source_class_indices)
5. Build ID remap table: all source IDs → target_idx
6. Iterate all Image records for the project, for each label file:
   - Read lines, remap class_ids using remap table
   - Track updated_files and updated_boxes counts
7. Rename class at target_idx to new_class_name
8. Remove other source classes (in reverse order to maintain indices)
9. Compact remaining class IDs in labels (shift down for removed gaps)
10. Call `utils.save_classes(project, classes)` — updates both `classes.txt` and `data.yaml`
11. Return response with updated classes + stats

**Pattern**: Follows existing `delete_project_class` (lines 741-792) for label file remapping.

---

### Component 2: Frontend — Button + Popup HTML

#### [MODIFY] [workspace.html](file:///d:/Thuctap/ToolIb-main/ToolIb-main/templates/workspace.html)

Insert after `#uploadDropdownContainer` `</div>` (line 80), before the hidden file inputs (line 81):

```html
<button id="mergeClassesBtn"
    class="text-primary hover:text-blue-500 rounded text-xs px-2 py-1 bg-surface border border-border transition-colors"
    title="Chuyển đổi class" onclick="currentWorkspace.openMergeClassesPanel()">
    <i class="fa-solid fa-right-left"></i>
</button>
```

Add popup panel HTML at the end of the sidebar header area (before `</div>` of sidebar-content flex container):

```html
<div id="mergeClassesPanel" class="hidden absolute left-0 top-full mt-1 ...">
  <!-- Checkbox list + text input + confirm/cancel buttons -->
</div>
```

---

### Component 3: Frontend — JavaScript Logic

#### [MODIFY] [workspace.js](file:///d:/Thuctap/ToolIb-main/ToolIb-main/static/js/workspace.js)

Add methods to workspace class:

1. `openMergeClassesPanel()` — Show popup, populate checkbox list from `projectClasses`
2. `closeMergeClassesPanel()` — Hide popup
3. `executeMergeClasses()` — Collect selected indices + new name, call API, handle response, refresh classes

## Verification Plan

### Manual Verification
1. Open workspace with a project that has multiple classes
2. Verify button appears with correct icon and position
3. Click button → popup appears with class list
4. Select classes, enter new name, confirm → success message
5. Verify `classes.txt` and `data.yaml` are updated
6. Verify label files have remapped class IDs
7. Verify right sidebar class panel refreshes correctly
