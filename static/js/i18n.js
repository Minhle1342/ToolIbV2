const translations = {
    en: {
        // Base
        "brand": "YOLO Hub",
        "nav_dashboard": "Dashboard",
        "nav_export": "Export Dataset",
        "nav_theme": "Switch Theme",
        "nav_lang": "Tiếng Việt",
        
        // Workspace - Sidebar Left
        "images": "Images",
        "upload_images": "Upload Images",
        "upload_files": "Files",
        "upload_folder": "Folder",
        "filter_all_images": "All Images",
        "filter_my_view": "My View",
        "filter_all_status": "All Status",
        "filter_flagged": "Flagged",
        "filter_labeled": "Labeled",
        "filter_unlabeled": "Unlabeled",
        "filter_by_classes": "Filter by Classes",
        "loading_classes": "Loading classes...",
        "btn_assign": "Assign",
        "btn_export": "Export",

        // Workspace - Toolbar
        "tool_draw": "Draw (D)",
        "tool_select": "Select/Edit (V)",
        "tool_lock": "Lock/Unlock Box (L)",
        "tool_hide": "Hide/Show Image (H)",
        "tool_auto": "Auto Label (Magic Wand)",
        "tool_sequence_numbers": "Show Bounding Box Sequence Numbers",
        "tool_zoom_on_focus": "Toggle Zoom on Focus",
        "tool_hide_boxes": "Hide/Show Bounding Boxes",
        "auto_current": "Current Canvas",
        "auto_all": "All Unlabeled Images",
        "no_image": "No Image",
        "tool_flag": "Flag Image (F)",
        "btn_saved": "Saved",
        "btn_saving": "Saving...",
        "auto_save": "Auto Save",
        "search_image_label": "Search Image:",
        "search_image_placeholder": "Enter filename...",
        "btn_search": "Search",

        // Workspace - Sidebar Right
        "inspection": "Inspection",
        "select_zoom": "Select a box to zoom",
        "nothing_selected": "Nothing selected",
        "delete_box": "Delete Box (Del/Q)",
        "classes": "Classes",
        "search_placeholder": "Search...",
        "new_class_placeholder": "New class name...",
        "btn_add": "Add",

        // Modals
        "assign_images": "Assign Images",
        "view_name": "View Name",
        "number_images": "Number of Images",
        "assign_mode": "Assign Mode",
        "cancel": "Cancel",
        "shortcuts": "Keyboard Shortcuts",
        "export_dataset": "Export Dataset",
        "scope": "Scope",
        "scope_project": "Entire Project",
        "scope_view": "Current View (Assigned)",
        "scope_current": "Current Image Only",
        "exclude_flagged": "Exclude Flagged Images",
        "train": "Train",
        "val": "Valid",
        "test": "Test",
        "yolo_version": "YOLO Version",
        "export_success": "Export successfully! Extract the dataset, upload to Colab and use this code to train YOLO.",
        "colab_title": "Google Colab Training Code",
        "btn_close": "Close",
        "btn_copy": "Copy",
        "copied": "Copied!",

        // Dashboard
        "dashboard_title": "Projects",
        "dashboard_newProject": "New Project",
        "dashboard_createProjectTitle": "Create New Project",
        "dashboard_projectName": "Project Name",
        "dashboard_imagesFolderPath": "Images Folder Path (Absolute)",
        "dashboard_dragDrop": "Drag & drop images folder here, or click to select folder",
        "dashboard_dragDropEdit": "Drag & drop new images folder here, or click to select",
        "dashboard_supportedFormats": "Supports JPG, PNG, BMP, JPEG (and corresponding .txt label files if any)",
        "dashboard_btnCancel": "Cancel",
        "dashboard_btnCreate": "Create",
        "dashboard_editProjectTitle": "Edit Project",
        "dashboard_btnSaveChanges": "Save Changes",
        "dashboard_openWorkspace": "Open Workspace",
        "dashboard_editProject": "Edit Project",
        "dashboard_guideProject": "Guide",
        "dashboard_scanFolder": "Scan Folder",
        "dashboard_deleteProject": "Delete Project",
        "dashboard_confirmDelete": "Are you sure you want to delete this project? This will only remove metadata from DB, image files will remain.",
        "dashboard_confirmScan": "Scan folder for new images?",
        "dashboard_reqProjectName": "Please enter \"Project Name\" at the top of the form before dragging and dropping to upload so the system can categorize the storage folder!",
        "dashboard_noValidFiles": "No valid images or label files (.txt, .yaml) found in the folder!",
        "dashboard_uploadingCount": "Uploading {0} files...",
        "dashboard_uploadPart": "[Part {0}/{1}] Sending {2} files... {3}",
        "dashboard_uploadingPercent": "Uploading {0}%",
        "dashboard_filesCount": "{0} files",
        "dashboard_uploadFailPart": "Uploading part {0} failed",
        "dashboard_uploadSuccess": "Upload successful!",
        "dashboard_completedPercent": "Completed 100%",
        "dashboard_totalFiles": "Total: {0} files",
        "dashboard_uploadError": "Upload error!",
        "dashboard_failed": "Failed",
        "dashboard_errorMsg": "Error: {0}",
        "dashboard_delete_password_prompt": "Enter password to delete this project:",
        "dashboard_delete_password_incorrect": "Incorrect password! Project was not deleted.",
        "unsaved_changes_warning": "You have unsaved changes! Click OK to switch image anyway without saving, or Cancel to stay."
    },
    vi: {
        // Base
        "brand": "YOLO Hub",
        "nav_dashboard": "Bảng điều khiển",
        "nav_export": "Xuất Dữ liệu",
        "nav_theme": "Đổi Giao diện",
        "nav_lang": "English",
        
        // Workspace - Sidebar Left
        "images": "Hình ảnh",
        "upload_images": "Tải ảnh lên",
        "upload_files": "Tệp (Files)",
        "upload_folder": "Thư mục (Folder)",
        "filter_all_images": "Tất cả ảnh",
        "filter_my_view": "Góc nhìn của tôi",
        "filter_all_status": "Tất cả trạng thái",
        "filter_flagged": "Đã gắn cờ",
        "filter_labeled": "Đã có Bounding Box",
        "filter_unlabeled": "Chưa có Bounding Box",
        "filter_by_classes": "Lọc theo nhãn (Classes)",
        "loading_classes": "Đang tải nhãn...",
        "btn_assign": "Phân công",
        "btn_export": "Xuất dữ liệu",

        // Workspace - Toolbar
        "tool_draw": "Vẽ (D)",
        "tool_select": "Chọn/Sửa (V)",
        "tool_lock": "Khóa/Mở Khóa (L)",
        "tool_hide": "Ẩn/Hiện Ảnh (H)",
        "tool_auto": "Gán nhãn tự động",
        "tool_sequence_numbers": "Hiển thị số thứ tự Bounding Box",
        "tool_zoom_on_focus": "Bật/Tắt phóng to khi focus",
        "tool_hide_boxes": "Ẩn/Hiện Bounding Box",
        "auto_current": "Ảnh hiện tại",
        "auto_all": "Tất cả ảnh chưa gán nhãn",
        "no_image": "Chưa có ảnh",
        "tool_flag": "Gắn cờ (F)",
        "btn_saved": "Đã lưu",
        "btn_saving": "Đang lưu...",
        "auto_save": "Tự động lưu",
        "search_image_label": "Tìm kiếm ảnh:",
        "search_image_placeholder": "Nhập tên file ảnh...",
        "btn_search": "Tìm kiếm",

        // Workspace - Sidebar Right
        "inspection": "Chi tiết",
        "select_zoom": "Chọn một box để thu phóng",
        "nothing_selected": "Chưa chọn gì",
        "delete_box": "Xóa Box (Del/Q)",
        "classes": "Nhãn (Classes)",
        "search_placeholder": "Tìm kiếm...",
        "new_class_placeholder": "Tên nhãn mới...",
        "btn_add": "Thêm",

        // Modals
        "assign_images": "Phân công ảnh",
        "view_name": "Tên View",
        "number_images": "Số lượng ảnh",
        "assign_mode": "Chế độ phân công",
        "cancel": "Hủy",
        "shortcuts": "Phím tắt",
        "export_dataset": "Xuất Dữ liệu",
        "scope": "Phạm vi",
        "scope_project": "Toàn bộ dự án",
        "scope_view": "View hiện tại (Đã phân công)",
        "scope_current": "Chỉ ảnh hiện tại",
        "exclude_flagged": "Loại bỏ ảnh đã gắn cờ",
        "train": "Train",
        "val": "Valid",
        "test": "Test",
        "yolo_version": "Phiên bản YOLO",
        "export_success": "Export thành công! Hãy nén thư mục dataset, upload lên Colab và dùng đoạn code dưới đây để train YOLO.",
        "colab_title": "Mã huấn luyện Google Colab",
        "btn_close": "Đóng",
        "btn_copy": "Sao chép",
        "copied": "Đã sao chép!",

        // Dashboard
        "dashboard_title": "Dự án",
        "dashboard_newProject": "Dự án mới",
        "dashboard_createProjectTitle": "Tạo Dự án mới",
        "dashboard_projectName": "Tên Dự án",
        "dashboard_imagesFolderPath": "Đường dẫn Thư mục Ảnh (Tuyệt đối)",
        "dashboard_dragDrop": "Kéo & thả thư mục ảnh vào đây, hoặc click để chọn thư mục",
        "dashboard_dragDropEdit": "Kéo & thả thư mục ảnh mới vào đây, hoặc click để chọn",
        "dashboard_supportedFormats": "Hỗ trợ JPG, PNG, BMP, JPEG (và file nhãn .txt tương ứng nếu có)",
        "dashboard_btnCancel": "Hủy",
        "dashboard_btnCreate": "Tạo",
        "dashboard_editProjectTitle": "Chỉnh sửa Dự án",
        "dashboard_btnSaveChanges": "Lưu Thay đổi",
        "dashboard_openWorkspace": "Mở Workspace",
        "dashboard_editProject": "Chỉnh sửa",
        "dashboard_guideProject": "Hướng dẫn",
        "dashboard_scanFolder": "Quét thư mục",
        "dashboard_deleteProject": "Xóa dự án",
        "dashboard_confirmDelete": "Bạn có chắc chắn muốn xóa dự án này? Thao tác này chỉ xóa dữ liệu khỏi DB, file ảnh vẫn sẽ được giữ lại.",
        "dashboard_confirmScan": "Quét thư mục để tìm ảnh mới?",
        "dashboard_reqProjectName": "Vui lòng nhập \"Tên Dự án\" ở đầu form trước khi kéo thả tải lên để hệ thống phân loại thư mục lưu trữ!",
        "dashboard_noValidFiles": "Không tìm thấy ảnh hoặc file nhãn (.txt, .yaml) hợp lệ trong thư mục!",
        "dashboard_uploadingCount": "Đang tải lên {0} tệp...",
        "dashboard_uploadPart": "[Phần {0}/{1}] Đang gửi {2} tệp... {3}",
        "dashboard_uploadingPercent": "Đang tải lên {0}%",
        "dashboard_filesCount": "{0} tệp",
        "dashboard_uploadFailPart": "Tải lên phần {0} thất bại",
        "dashboard_uploadSuccess": "Tải lên thành công!",
        "dashboard_completedPercent": "Đã hoàn thành 100%",
        "dashboard_totalFiles": "Tổng: {0} tệp",
        "dashboard_uploadError": "Lỗi tải lên!",
        "dashboard_failed": "Thất bại",
        "dashboard_errorMsg": "Lỗi: {0}",
        "dashboard_delete_password_prompt": "Nhập mật khẩu để xóa dự án này:",
        "dashboard_delete_password_incorrect": "Mật khẩu không chính xác! Không thể xóa dự án.",
        "unsaved_changes_warning": "Bạn có thay đổi chưa lưu! Bấm OK để tiếp tục chuyển ảnh mà không lưu, hoặc Cancel để ở lại."
    }
};

let currentLang = localStorage.getItem('app_lang') || 'en';

window.t = function(key, ...args) {
    let text = translations[currentLang][key] || key;
    if (args.length > 0) {
        args.forEach((arg, i) => {
            text = text.replace(`{${i}}`, arg);
        });
    }
    return text;
};

function setLanguage(lang) {
    if (lang !== 'en' && lang !== 'vi') return;
    currentLang = lang;
    localStorage.setItem('app_lang', lang);
    applyTranslations();
}

function toggleLanguage() {
    setLanguage(currentLang === 'en' ? 'vi' : 'en');
}

function applyTranslations() {
    const dict = translations[currentLang];
    
    // Element's inner text
    document.querySelectorAll('[data-i18n]').forEach(el => {
        const key = el.getAttribute('data-i18n');
        if (dict[key]) {
            let text = dict[key];
            if (el.dataset.suffix) {
                text += el.dataset.suffix;
            }
            el.textContent = text;
        }
    });

    // Element's placeholder
    document.querySelectorAll('[data-i18n-placeholder]').forEach(el => {
        const key = el.getAttribute('data-i18n-placeholder');
        if (dict[key]) {
            el.placeholder = dict[key];
        }
    });

    // Element's title (for tooltips)
    document.querySelectorAll('[data-i18n-title]').forEach(el => {
        const key = el.getAttribute('data-i18n-title');
        if (dict[key]) {
            el.title = dict[key];
        }
    });
}

document.addEventListener('DOMContentLoaded', applyTranslations);
