# Feature: Class Conversion Button (Chuyển đổi)

## Overview
Thêm nút "Chuyển đổi" (Convert/Merge Classes) vào toolbar bên phải nút Upload trong trang workspace.html. Nút này cho phép người dùng chọn 1 hoặc nhiều class hiện tại và đổi tên tất cả thành 1 tên class mới, cập nhật đồng thời cả file `data.yaml` và `classes.txt` của project.

## Requirements

### Functional Requirements
1. Nút "Chuyển đổi" với icon nằm bên phải nút `#uploadDropdownContainer`
2. Khi click nút sẽ mở modal dialog cho phép:
   - Hiển thị danh sách tất cả class hiện tại (từ classes.txt / data.yaml)
   - Chọn 1 hoặc nhiều class nguồn (source classes) bằng checkbox
   - Nhập tên class mới (target class name)
3. Khi xác nhận:
   - Tất cả class được chọn sẽ được merge/đổi tên thành 1 class mới
   - Cập nhật `data.yaml` (names + nc) 
   - Cập nhật `classes.txt`
   - Cập nhật tất cả label files (.txt) để remap class_id cho các box thuộc class đã chọn
4. Hiển thị kết quả (số file đã cập nhật, số box đã thay đổi)

### Non-Functional Requirements
- Consistent styling with existing buttons in the toolbar
- Vietnamese tooltip text
- Handle edge cases: empty selection, duplicate names, all classes selected
