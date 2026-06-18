# ⌨️ BẢNG TRA CỨU PHÍM TẮT GÁN NHÃN YOLO 🏷️

Tài liệu này tổng hợp toàn bộ các phím tắt (Hotkeys) trong trình gán nhãn **Team YOLO Labeling Hub** giúp bạn tối ưu hóa tốc độ làm việc, gán nhãn nhanh bằng một tay và giảm mỏi cơ tay khi thao tác kéo thả chuột.

---

## 🛠️ 1. Chế Độ Làm Việc & Canvas (Tools & Canvas)

| Phím tắt | Chức năng | Hướng dẫn sử dụng |
| :--- | :--- | :--- |
| <kbd>D</kbd> | **Chế độ Vẽ (Draw Mode)** | Chuyển con trỏ thành bút để kéo vẽ BBox mới trên ảnh. |
| <kbd>S</kbd> hoặc <kbd>V</kbd> | **Chế độ Chọn (Select Mode)** | Chuyển về con trỏ chuột để chọn, di chuyển, phóng to/thu nhỏ hoặc xoay BBox đã vẽ. |
| **Giữ <kbd>Space</kbd> + Kéo chuột** | **Di chuyển ảnh (Pan)** | Giữ phím Space (hoặc phím <kbd>Alt</kbd>) và kéo chuột để di chuyển vùng nhìn khi ảnh đang Zoom lớn. |
| <kbd>Ctrl</kbd> + **Lăn chuột** | **Phóng to / Thu nhỏ** | Cuộn chuột lên để Phóng to (Zoom In), cuộn chuột xuống để Thu nhỏ (Zoom Out) ảnh. |
| <kbd>~</kbd> hoặc <kbd>`</kbd> | **Hiện/Ẩn danh sách phím tắt** | Nhấn phím Backquote (phím nằm ngay dưới phím Esc) để bật/tắt bảng tra cứu nhanh phím tắt. |

---

## 📦 2. Quản Lý Hộp Bao (BBox Management)

| Phím tắt | Chức năng | Hướng dẫn sử dụng |
| :--- | :--- | :--- |
| <kbd>A</kbd> | **Sticky Move (Dính con trỏ)** | **[ĐỘC QUYỀN]** Nhấn A khi đang chọn BBox, hộp sẽ dính vào chuột để di chuyển mà không cần bấm giữ chuột trái. Bấm chuột trái một lần nữa để đặt hộp xuống. |
| <kbd>Ctrl</kbd> + <kbd>D</kbd> | **Nhân bản BBox (Duplicate)** | Tạo một bản sao giống hệt BBox đang chọn và tự động đưa bản sao vào chế độ **Sticky Move** để bạn di chuyển nhanh sang vị trí mới. |
| <kbd>Del</kbd> hoặc <kbd>Backspace</kbd> hoặc <kbd>Q</kbd> | **Xóa BBox (Delete)** | Xóa bỏ hoàn toàn BBox đang được lựa chọn khỏi hình ảnh. |
| <kbd>Ctrl</kbd> + <kbd>Z</kbd> | **Hoàn tác (Undo)** | Quay lại thao tác vừa vẽ, sửa hoặc xóa BBox trước đó. |
| <kbd>Ctrl</kbd> + <kbd>Y</kbd> hoặc <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>Z</kbd> | **Làm lại (Redo)** | Đi tiếp thao tác đã Hoàn tác (Undo) trước đó. |
| <kbd>Ctrl</kbd> + **Bấm chuột trái** | **Chọn nhiều BBox** | Giữ phím Ctrl và click chuột vào các BBox khác nhau để chọn cùng lúc nhiều hộp bao. |

---

## 🎨 3. Thuộc Tính & Chế Độ Hiển Thị (Attributes & Views)

| Phím tắt | Chức năng | Hướng dẫn sử dụng |
| :--- | :--- | :--- |
| <kbd>0</kbd> - <kbd>9</kbd> | **Chọn Class nhanh** | Đổi BBox đang chọn sang Class (lớp đối tượng) tương ứng với số thứ tự phím từ 0 đến 9 trong bảng Classes. |
| <kbd>L</kbd> | **Khóa/Mở khóa BBox (Lock)** | Khóa hộp lại để tránh việc vô tình click chuột làm xê dịch hoặc thay đổi kích thước BBox trong quá trình làm việc. |
| <kbd>I</kbd> | **Chế độ Cô lập (Isolate)** | Ẩn tất cả các BBox khác, chỉ hiển thị duy nhất BBox đang chọn để dễ dàng kiểm tra chi tiết. Nhấn lại phím <kbd>I</kbd> để hiển thị lại bình thường. |
| <kbd>H</kbd> | **Ẩn/Hiện ảnh nền (Hide Image)** | Tạm thời ẩn hình ảnh nền đi (chỉ hiển thị khung xương các BBox) giúp dễ dàng phát hiện các BBox rác hoặc chồng chéo. |
| <kbd>F</kbd> | **Đánh dấu ảnh lỗi (Flag)** | Đánh dấu bức ảnh hiện tại là "Cần kiểm tra lại" (Flagged) để dễ dàng lọc riêng hoặc loại bỏ khi xuất dữ liệu. |

---

## 🚀 4. Điều Hướng & Lưu Trữ (Navigation & Save)

| Phím tắt | Chức năng | Hướng dẫn sử dụng |
| :--- | :--- | :--- |
| **Mũi tên Phải** (<kbd>→</kbd>) | **Ảnh tiếp theo** | Lưu nhãn của ảnh hiện tại và chuyển sang bức ảnh tiếp theo trong danh sách. |
| **Mũi tên Trái** (<kbd>←</kbd>) | **Ảnh trước đó** | Lưu nhãn của ảnh hiện tại và quay lại bức ảnh trước đó trong danh sách. |
| <kbd>Ctrl</kbd> + <kbd>S</kbd> | **Lưu thủ công** | Lưu lại trạng thái BBox và nhãn của ảnh hiện tại ngay lập tức vào cơ sở dữ liệu. |

---

## 💡 Mẹo Nhỏ Để Đạt Tốc Độ Tối Đa:
1. **Gán nhãn bằng 1 tay**: Tay trái của bạn luôn đặt trên bàn phím tại khu vực phím <kbd>A</kbd>, <kbd>S</kbd>, <kbd>D</kbd>, <kbd>Q</kbd> và dãy số từ <kbd>0</kbd> đến <kbd>9</kbd>. Tay phải cầm chuột. Điều này giúp bạn gán nhãn cực nhanh mà không cần di chuyển tay.
2. **Tối ưu hóa phím `Ctrl + D` + `Sticky Move`**: Khi có nhiều vật thể cùng loại và cùng kích thước gần nhau, hãy chọn BBox -> bấm `Ctrl + D` -> di chuyển chuột đến vị trí mới -> Click chuột trái. Thao tác này nhanh hơn vẽ mới gấp 5 lần!
