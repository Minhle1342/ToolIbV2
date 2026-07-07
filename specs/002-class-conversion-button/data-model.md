# Data Model: Class Conversion

## Entities

### ClassMergeRequest (API Input)
| Field | Type | Required | Description |
|-------|------|----------|-------------|
| source_class_indices | int[] | Yes | List of 0-based class indices to merge |
| new_class_name | string | Yes | New name for the merged class |

### ClassMergeResponse (API Output)
| Field | Type | Description |
|-------|------|-------------|
| message | string | Success message |
| classes | string[] | Updated class list |
| updated_files | int | Number of label files modified |
| updated_boxes | int | Number of bounding boxes remapped |
| removed_classes | string[] | Names of classes that were merged away |

## File Formats Affected

### classes.txt
- One class name per line
- 0-indexed (line 0 = class 0)
- After merge: fewer lines, contiguous indices

### data.yaml
```yaml
names:
  - ClassName1
  - ClassName2
nc: 2
path: .
train: train/images
val: val/images
```
After merge: `names` list shrinks, `nc` decrements by (source_count - 1)

### Label files (.txt) — YOLO format
```
class_id center_x center_y width height
```
- `class_id` must be remapped: all source IDs → target ID, IDs above removed classes shift down

## State Transitions

```
Before merge:
  classes = [A, B, C, D, E]  (indices 0,1,2,3,4)
  
User selects: indices [1, 3] (B, D) → merge into "NewName"

Step 1: Pick target index = min(1, 3) = 1
Step 2: Remap in labels: class_id 3 → 1
Step 3: Rename class at index 1 to "NewName"
Step 4: Remove class at index 3 (now gap)
Step 5: Compact IDs: 
  - class_id 0 stays 0 (A)
  - class_id 1 stays 1 (NewName)
  - class_id 2 stays 2 (C)
  - class_id 3 was removed
  - class_id 4 → 3 (E)

After merge:
  classes = [A, NewName, C, E]  (indices 0,1,2,3)
```

## Validation Rules
1. `source_class_indices` must contain at least 1 index
2. All indices must be valid (0 ≤ idx < len(classes))
3. `new_class_name` must not be empty after stripping whitespace
4. `new_class_name` must not conflict with existing non-selected class names
