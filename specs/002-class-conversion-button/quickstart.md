# Quickstart: Class Conversion Button

## Prerequisites
- Running Flask server (`python app.py` or equivalent)
- A project with at least 2 classes defined in `classes.txt` / `data.yaml`
- Some labeled images (`.txt` label files with bounding boxes)

## Validation Scenarios

### Scenario 1: Basic Class Merge via UI
1. Open workspace page for a project with multiple classes
2. Locate the "Chuyển đổi" button (right of the Upload button in left sidebar header)
3. Click the button — a popup panel appears with:
   - Checkbox list of all current classes
   - Text input for new class name
   - "Xác nhận" (Confirm) and "Hủy" (Cancel) buttons
4. Check 2+ classes, enter a new name, click "Xác nhận"
5. **Expected**: 
   - Success notification with count of updated files/boxes
   - Class panel on right sidebar refreshes with merged classes
   - `classes.txt` and `data.yaml` reflect the new class list

### Scenario 2: API Direct Test
```bash
curl -X POST http://localhost:5000/api/projects/1/classes/merge \
  -H "Content-Type: application/json" \
  -d '{"source_class_indices": [0, 2], "new_class_name": "MergedClass"}'
```
**Expected**: 200 response with updated classes list and stats

### Scenario 3: Edge Cases
- Select only 1 class → should rename that single class
- Enter a name that conflicts with a non-selected class → 400 error
- Select all classes → should merge all into one class
- Empty new name → 400 error

### Scenario 4: Verify File Changes
After merging, verify:
```bash
# Check classes.txt
cat <project_root>/classes.txt

# Check data.yaml
cat <project_root>/data.yaml

# Check a label file — class IDs should be remapped
cat <project_root>/some_image.txt
```
