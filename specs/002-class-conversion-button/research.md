# Research: Class Conversion Button

## Decision: UI Pattern for Class Conversion Dialog

**Decision**: Use a custom inline dialog/popup (similar to the existing upload dropdown pattern) that opens when clicking the "Chuyển đổi" button, rather than a full-screen modal.

**Rationale**: 
- The project uses native `confirm()` / `alert()` for simple confirmations
- No modal framework is used (no SweetAlert, no Bootstrap modal, etc.)
- A custom popup panel consistent with existing dropdown patterns (like `#uploadDropdownMenu`) would fit the existing codebase style
- For this feature, we need a more complex UI (checkbox list + text input), so a fixed overlay panel is more appropriate

**Alternatives considered**:
- Native `prompt()` — too limited for multi-select + text input
- Full modal library (SweetAlert2, etc.) — too heavy, not in existing deps
- Inline expansion in sidebar — not enough space

## Decision: Label File Update Strategy

**Decision**: Merge selected class IDs into a single target class ID, then compact remaining IDs to maintain contiguous indexing.

**Rationale**:
- YOLO format requires class IDs to be 0-indexed contiguous integers
- The existing `delete_project_class` route (line 741-792 in routes.py) already handles ID remapping in label files
- The merge operation is: pick lowest ID among selected classes → remap all selected to that ID → rename that class → remove other selected classes → compact remaining IDs

**Alternatives considered**:
- Keep gaps in class IDs — breaks YOLO convention
- Only rename without merging — doesn't match user requirement

## Decision: Backend API Design

**Decision**: Create a new endpoint `POST /api/projects/<project_id>/classes/merge`

**Rationale**: 
- Follows existing route pattern in `routes.py` (lines 689-792)
- Uses existing `utils.save_classes()` which already updates both `classes.txt` and `data.yaml`
- Separation from existing class CRUD endpoints keeps code clean

## Technology Details

- **Icon**: `fa-solid fa-right-left` (exchange/convert icon from FontAwesome 6)
- **Backend**: Flask route using existing `utils.get_classes()` and `utils.save_classes()`
- **Frontend**: Custom popup panel rendered via JavaScript in `workspace.js`
- **Files affected**: `data.yaml` (names + nc), `classes.txt`, all `.txt` label files
