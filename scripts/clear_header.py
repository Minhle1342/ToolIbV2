import os
import re
from pathlib import Path

def validate_and_rename_yolo_dataset(image_path, label_path, dry_run=True):
    """
    Script nâng cấp: Đổi tên đồng bộ ảnh và nhãn YOLO, hỗ trợ cả 2 pattern X_Y_ và X_.
    Đảm bảo an toàn dữ liệu, chống lệch pha tên giữa ảnh và nhãn khi trùng lặp.
    """
    
    # -----------------------------------------------------------------
    # BƯỚC 1: KIỂM TRA LỖI NHẬP LIỆU (VALIDATION)
    # -----------------------------------------------------------------
    if not os.path.exists(image_path):
        print(f"❌ LỖI: Đường dẫn thư mục ảnh không tồn tại: {image_path}")
        return
        
    if not os.path.exists(label_path):
        print(f"❌ LỖI: Đường dẫn thư mục nhãn không tồn tại: {label_path}")
        return

    print("=== KHỞI CHẠY TIẾN TRÌNH KIỂM TRA VÀ ĐỔI TÊN ĐỒNG BỘ ===")
    if dry_run:
        print("⚠️ CHẾ ĐỘ: DRY RUN (Chỉ chạy thử, chưa thay đổi file trên ổ đĩa) ⚠️\n")
    else:
        print("⚡ CHẾ ĐỘ: CHẠY THẬT (Dữ liệu trên ổ đĩa SẼ BỊ THAY ĐỔI) ⚡\n")

    # Regex thông minh: Khớp "X_Y_" hoặc "X_" ở đầu chuỗi
    pattern = re.compile(r'^(?:\d+_\d+|\d+)_(.*)')

    # Đọc toàn bộ file trong 2 thư mục
    try:
        raw_images = [f for f in os.listdir(image_path) if os.path.isfile(os.path.join(image_path, f))]
        raw_labels = [f for f in os.listdir(label_path) if os.path.isfile(os.path.join(label_path, f))]
    except Exception as e:
        print(f"❌ LỖI: Không thể đọc danh sách file từ thư mục. Chi tiết: {e}")
        return

    # -----------------------------------------------------------------
    # BƯỚC 2: PHÂN TÍCH VÀ ĐỒNG BỘ HÓA TÊN FILE (ANTI-DESYNC LOGIC)
    # -----------------------------------------------------------------
    # Tìm tất cả các "Tên gốc" (Stem) xuất hiện trong hệ thống dataset
    all_stems = set()
    image_mapping = {} # old_stem -> full_image_filename
    label_mapping = {} # old_stem -> full_label_filename

    for img in raw_images:
        stem, _ = os.path.splitext(img)
        all_stems.add(stem)
        image_mapping[stem] = img

    for lbl in raw_labels:
        stem, _ = os.path.splitext(lbl)
        all_stems.add(stem)
        label_mapping[stem] = lbl

    # Bản đồ quy hoạch tên: old_stem -> new_stem
    stem_rename_map = {}
    processed_new_stems = set()

    # Tính toán trước tất cả các tên mới để tránh xung đột
    for old_stem in sorted(all_stems):
        match = pattern.match(old_stem)
        if match:
            new_stem = match.group(1)
        else:
            new_stem = old_stem # Giữ nguyên nếu không khớp pattern số ở đầu

        # Xử lý trùng lặp tên sau khi làm sạch (Collision Resolution)
        base_new_stem = new_stem
        counter = 1
        while new_stem in processed_new_stems:
            new_stem = f"{base_new_stem}_{counter}"
            counter += 1
        
        processed_new_stems.add(new_stem)
        stem_rename_map[old_stem] = new_stem

    # -----------------------------------------------------------------
    # BƯỚC 3: THỰC THI ĐỔI TÊN HÀNG LOẠT
    # -----------------------------------------------------------------
    print("--- Tiến hành xử lý đổi tên ---")
    
    for old_stem, new_stem in stem_rename_map.items():
        if old_stem == new_stem:
            continue # Không có thay đổi thì bỏ qua

        # 1. Đổi tên file Ảnh nếu có
        if old_stem in image_mapping:
            old_img_name = image_mapping[old_stem]
            _, ext = os.path.splitext(old_img_name)
            new_img_name = new_stem + ext
            
            print(f"[IMAGE] {old_img_name}  ==>  {new_img_name}")
            if not dry_run:
                os.rename(os.path.join(image_path, old_img_name), os.path.join(image_path, new_img_name))

        # 2. Đổi tên file Nhãn nếu có (Đảm bảo dùng chung new_stem chính xác với Ảnh)
        if old_stem in label_mapping:
            old_lbl_name = label_mapping[old_stem]
            _, ext = os.path.splitext(old_lbl_name)
            new_lbl_name = new_stem + ext
            
            print(f"[LABEL] {old_lbl_name}  ==>  {new_lbl_name}")
            if not dry_run:
                os.rename(os.path.join(label_path, old_lbl_name), os.path.join(label_path, new_lbl_name))

    print("\n=== HOÀN THÀNH TIẾN TRÌNH RENAME CODES ===")

# -----------------------------------------------------------------
# CẤU HÌNH ĐẦU VÀO ĐỂ CHẠY SCRIPT
# -----------------------------------------------------------------
if __name__ == "__main__":
    IMAGE_FOLDER = r"D:\Thuctap\ToolIb-main\ToolIb-main\exported_dataset\images\train"
    LABEL_FOLDER = r"D:\Thuctap\ToolIb-main\ToolIb-main\exported_dataset\labels\train"
    
    # LƯU Ý: Đã sửa thành "False" viết hoa theo đúng cú pháp Python.
    # Hãy để True để kiểm tra terminal trước, khi thấy chuẩn thì sửa thành False để lưu thật vào ổ cứng.
    DRY_RUN_MODE = False 
    
    validate_and_rename_yolo_dataset(IMAGE_FOLDER, LABEL_FOLDER, dry_run=DRY_RUN_MODE)