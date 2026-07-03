# Team YOLO Labeling Hub 🏷️

Công cụ gán nhãn dữ liệu YOLO chuyên nghiệp, hoạt động trên nền tảng Web/LAN, hỗ trợ làm việc nhóm, tích hợp Auto-Labeling và quy trình gán nhãn tối ưu hóa tốc độ.

## 🚀 Tính Năng Nổi Bật

- **Gán nhãn BBox chuẩn YOLO**: Giao diện kéo thả mượt mà, hỗ trợ zoom/pan ảnh độ phân giải cao.
- **Sticky Move (Tính năng độc quyền)**: Di chuyển BBox mà không cần giữ chuột, giúp giảm mỏi tay và tăng chính xác.
- **Undo/Redo**: Hệ thống lịch sử thao tác đầy đủ (Ctrl+Z / Ctrl+Y).
- **Auto-Labeling**: Tự động gán nhãn bằng mô hình AI (YOLO ONNX).
- **Đa dạng định dạng Export**: Hỗ trợ xuất dữ liệu theo cấu trúc YOLO chuẩn hoặc cấu trúc Split (Train/Val/Test).
- **Hỗ trợ làm việc nhóm**: Lưu trữ tập trung qua SQLite, dễ dàng truy cập từ các máy khác trong mạng LAN.
- **Shortcuts Overlay**: Tra cứu phím tắt nhanh chóng ngay trong ứng dụng.

---

## 🛠️ Hướng Dẫn Cài Đặt

### 1. Yêu cầu hệ thống
- **Python**: Phiên bản 3.9 trở lên.
- **Trình duyệt**: Chrome hoặc Edge (khuyên dùng).

### 2. Các bước cài đặt

1. **Tải mã nguồn**: Tải hoặc Clone dự án về máy.
2. **Cài đặt thư viện**: Mở terminal (CMD/PowerShell) tại thư mục dự án và chạy:
   ```bash
   pip install -r requirements.txt
   ```
3. **Cấu hình Model AI**: Đặt file mô hình YOLO của bạn (định dạng `.onnx`) vào thư mục `models/`. Mặc định ứng dụng sẽ tìm file `models/yolo12s.onnx`.

### 3. Khởi chạy ứng dụng (Mới: Click đúp vào `run.bat` để chạy nhanh)

#### Cách 1: Click đúp chạy ngay (Khuyên dùng)
* Nhấp đúp chuột vào file **`run.bat`** ở thư mục gốc của dự án.
* File này sẽ tự động chạy script PowerShell **`run.ps1`**, kích hoạt môi trường ảo `.venv` (nếu có), tự động mở trình duyệt hiển thị ứng dụng tại địa chỉ `https://localhost:5000` và khởi chạy server Flask.

#### Cách 2: Khởi chạy bằng lệnh thủ công (Terminal)
Chạy lệnh sau để khởi động server:
```bash
python app.py
```
Sau đó, truy cập vào địa chỉ: `https://localhost:5000` (hoặc `https://<IP_MAY_CHỦ>:5000` nếu truy cập từ máy khác trong mạng).

---

## ⌨️ Hệ Thống Phím Tắt (Hotkeys)

| Phím | Chức năng |
| :--- | :--- |
| **`** (Backquote) | **Hiện/Ẩn bảng hướng dẫn phím tắt** |
| **S** | Chế độ Chọn (Select) |
| **D** | Chế độ Vẽ (Draw) |
| **A** | **Sticky Move**: BBox dính vào con trỏ để di chuyển nhanh |
| **Ctrl + D** | Nhân bản BBox (Tự động vào chế độ Sticky) |
| **Ctrl + Z / Y** | **Undo / Redo** thao tác |
| **Ctrl + Click** | Chọn nhiều BBox cùng lúc |
| **0-9** | Chọn class nhanh cho BBox |
| **Q / Del** | Xóa BBox đang chọn |
| **L** | Khóa/Mở khóa BBox |
| **H** | Ẩn/Hiện ảnh nền (để kiểm tra BBox rác) |
| **I** | Chế độ Cô lập (Isolate): Chỉ hiện BBox đang chọn |
| **Space + Kéo** | Di chuyển (Pan) ảnh khi đang zoom |
| **F** | Đánh dấu (Flag) ảnh cần kiểm tra lại |
| **Mũi tên Trái/Phải** | Chuyển ảnh Trước/Sau |

---

## 📁 Xuất Dữ Liệu (Export)

Công cụ hỗ trợ xuất dữ liệu linh hoạt thông qua menu Export:
- **Scope**: Toàn bộ dự án, theo View (đã gán cho user), hoặc ảnh hiện tại.
- **Exclude Flagged**: Tự động loại bỏ các ảnh đã đánh dấu lỗi/cần kiểm tra.
- **Format**: Chọn giữa cấu trúc YOLO chuẩn hoặc cấu trúc thư mục phân tách Train/Val.

---

## 📝 Lưu ý quan trọng
- Luôn đảm bảo BBox nằm trong phạm vi ảnh. Hệ thống đã tích hợp tính năng tự động chặn (Constraint) nếu BBox tràn ra ngoài.
- Khi export, file `data.yaml` sẽ tự động được tạo tương thích với YOLO v5/v8.
- **Cấu hình Classes**: Mỗi dự án yêu cầu phải có một file `classes.txt` (chứa danh sách các nhãn, mỗi dòng một nhãn) đặt trực tiếp trong thư mục gốc của dự án (Root Path).

**Chúc bạn có trải nghiệm gán nhãn tuyệt vời!** 🚀
# Team-YOLO-Labeling-Hub
