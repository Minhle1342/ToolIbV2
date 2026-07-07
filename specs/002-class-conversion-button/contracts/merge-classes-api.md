# API Contract: Merge Classes

## Endpoint

```
POST /api/projects/<project_id>/classes/merge
```

## Request Body

```json
{
  "source_class_indices": [1, 3],
  "new_class_name": "NewClassName"
}
```

## Success Response (200)

```json
{
  "message": "Classes merged successfully",
  "classes": ["ClassA", "NewClassName", "ClassC", "ClassE"],
  "updated_files": 42,
  "updated_boxes": 156,
  "removed_classes": ["ClassB", "ClassD"]
}
```

## Error Responses

### 400 Bad Request — Missing fields
```json
{
  "error": "source_class_indices and new_class_name are required"
}
```

### 400 Bad Request — Invalid indices
```json
{
  "error": "Invalid class index: 99"
}
```

### 400 Bad Request — Name conflict
```json
{
  "error": "Class name 'ExistingClass' already exists in non-selected classes"
}
```

### 400 Bad Request — Empty selection
```json
{
  "error": "At least one source class must be selected"
}
```

### 404 Not Found — Invalid project
```json
{
  "error": "Project not found"
}
```
