
<!-- @import "[TOC]" {cmd="toc" depthFrom=1 depthTo=6 orderedList=false} -->
# 📖 HƯỚNG DẪN CHIA SẺ & PHÂN PHỐI ẢNH CHO THÀNH VIÊN NHÓM 🏷️

Tài liệu này hướng dẫn chi tiết cách sử dụng tính năng **Views & Assign** trong **Team YOLO Labeling Hub** để phân chia công việc gán nhãn hình ảnh cho các thành viên 

trong nhóm, giúp làm việc song song qua mạng LAN và tránh việc gán nhãn trùng lặp.

---

## 🛠️ 1. Tổng Quan Về Cách Hoạt Động (Mô hình LAN)

Hệ thống hoạt động theo mô hình **Máy chủ - Máy trạm (Client - Server)** kết nối qua mạng nội bộ (Wi-Fi hoặc mạng dây LAN):

```mermaid
graph TD
    A[Máy Chủ - Của Bạn<br>Chạy Flask Server] <--- Kết nối LAN ---> B[Máy Thành Viên A<br>Trình duyệt Web]
    A <--- Kết nối LAN ---> C[Máy Thành Viên B<br>Trình duyệt Web]
    A <--- Kết nối LAN ---> D[Máy Thành Viên C<br>Trình duyệt Web]
```

*   **Máy chủ (Server)**: Là máy tính chứa thư mục ảnh gốc và chạy mã nguồn dự án. Mọi dữ liệu nhãn `.txt` và cơ sở dữ liệu SQLite đều được lưu trữ tập trung tại đây.
*   **Máy thành viên (Client)**: Chỉ cần mở trình duyệt web truy cập vào địa chỉ IP của Máy chủ để gán nhãn. Không cần cài đặt Python hay tải ảnh về máy cá nhân.

---

## 🚀 2. Quy Trình Thực Hiện Chi Tiết

### 📍 Bước 1: Khởi chạy Server và lấy IP (Dành cho Máy chủ)

1. Mở Terminal tại thư mục dự án và khởi chạy máy chủ:
   ```bash
   python app.py
   ```
2. Trên màn hình Terminal, hãy tìm dòng thông báo chứa địa chỉ mạng LAN của bạn. Ví dụ:
   ```text
   * Running on http://192.168.1.43:5000
   ```
3. Gửi địa chỉ IP này (ví dụ: `http://192.168.1.43:5000`) cho tất cả các thành viên trong nhóm.

> **LƯU Ý CỰC KỲ QUAN TRỌNG**
> Máy chủ của bạn phải được kết nối chung một mạng Wi-Fi hoặc mạng LAN với máy tính của các thành viên khác.

---

### 📍 Bước 2: Truy cập ứng dụng (Dành cho Thành viên)

1. Các thành viên mở trình duyệt (Khuyên dùng **Google Chrome** hoặc **Microsoft Edge
**).
2. Nhập địa chỉ IP Máy chủ được cung cấp vào thanh địa chỉ để truy cập giao diện **YOLO Labeling Hub**.
3. Bấm nút **Open Workspace** tại dự án muốn gán nhãn.

---

### 📍 Bước 3: Tạo Phân Vùng & Phân Phối Ảnh (Assign)

Để chia ảnh cho từng người, người quản trị hoặc bản thân thành viên thực hiện các bước sau ngay trên Workspace:

1. Tại thanh Sidebar bên trái (phía dưới danh sách ảnh), nhấn nút **Assign** (biểu tượng hình người kèm dấu cộng).
2. Một hộp thoại **Assign Images** sẽ hiển thị:
   *   **View Name**: Tên định danh phân vùng làm việc của thành viên (Ví dụ: `Minh_BBox_1`, `Tuan_BBox_1`).
   *   **Number of Images**: Số lượng ảnh muốn phân công cho thành viên này (Ví dụ: `50` hoặc `100` ảnh).
3. Bấm nút **Assign** để xác nhận.

> **MẸO NHỎ**
> Hệ thống sẽ tự động lọc ra các hình ảnh **chưa được phân phối cho ai (view_id = null)** và gán chúng cho View mới này, đảm bảo không có bất kỳ hai thành viên nào bị trùng ảnh gán nhãn.

---

### 📍 Bước 4: Lọc Ảnh & Tiến Hành Gán Nhãn Song Song

Sau khi đã được gán ảnh, mỗi thành viên cần cấu hình bộ lọc trên máy của mình để chỉ hiển thị ảnh của riêng họ:

1. Ở đầu Sidebar bên trái của màn hình Workspace, tìm bộ lọc **View Filter** (mặc định là *All Images*).
2. Bấm chọn đúng tên **View** của mình (Ví dụ: chọn `Minh_BBox_1`).
3. Lúc này, danh sách ảnh sẽ chỉ hiển thị các bức ảnh đã được gán riêng cho bạn.
4. Thành viên tiến hành gán nhãn (vẽ BBox), nhấn **Saved** (hoặc phím tắt `Ctrl + S`). Nhãn sẽ được tự động lưu thẳng về Máy chủ trong thời gian thực.

---

### 📍 Bước 5: Xuất Dữ Liệu Sau Khi Hoàn Thành (Export)

Khi một thành viên đã gán nhãn xong phân vùng của mình và muốn lấy dữ liệu để huấn luyện thử nghiệm:

1. Bấm nút **Export** tại Sidebar bên trái.
2. Tại mục **Scope**, chọn **Current View (Assigned)**.
3. Cấu hình tỷ lệ chia Train/Val (ví dụ: `0.8`) và định dạng cấu trúc thư mục.
4. Bấm **Export**. Tập dữ liệu được phân chia hoàn chỉnh (kèm tệp cấu hình `data.yaml`) sẽ được tạo ra tại thư mục `exported_dataset` trên Máy chủ.

---

## ⚠️ 3. Các Lưu Ý Quan Trọng

*   **Kết nối mạng**: Luôn đảm bảo kết nối mạng LAN ổn định trong suốt quá trình gán nhãn để việc đồng bộ dữ liệu BBox về máy chủ không bị gián đoạn.
*   **Tự động Constraints**: Tất cả các hộp bao (BBox) được vẽ sẽ tự động bị chặn nếu kéo tràn ra ngoài rìa ảnh, giúp đảm bảo định dạng nhãn YOLO luôn chính xác khi huấn luyện mô hình.
*   **Tra cứu Phím tắt nhanh**: Nhấn phím **`** (Backquote - phím nằm dưới phím Esc) bất kỳ lúc nào để hiện bảng tra cứu toàn bộ phím tắt hỗ trợ thao tác nhanh bằng một tay.
