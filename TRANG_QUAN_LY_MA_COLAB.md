# 🚀 TRANG QUẢN LÝ MÃ GOOGLE COLAB (COLAB CODE MANAGER - CRUD)

Tài liệu thiết kế và mã nguồn hoàn chỉnh cho **Trang quản lý mã Google Colab với tính năng CRUD Template & Trình sinh mã thời gian thực (Real-time Code Generator)** hỗ trợ **TẤT CẢ TỔNG CỘNG 17 PHIÊN BẢN YOLO** (từ YOLOv1 đến YOLO11, YOLO12, YOLO26, YOLO-World, YOLO-NAS, YOLOX, PP-YOLOE...) cùng các thông số **Tiền xử lý (Preprocessing)** và **Tăng cường dữ liệu (Data Augmentation)** chuyên sâu, có tích hợp **Icon Tooltip (?)**, **Ghi chú chi tiết tác dụng sau dấu `#` trong mã Colab**, **Tự động Highlight & Phóng to mã khi tinh chỉnh**, **Tự động Cuộn đến vị trí thông số** và **Tùy chỉnh Cỡ chữ (A+/A-)**.

---

## 📑 MỤC LỤC
1. [Tổng quan kiến trúc & Thống kê 17 Phiên bản YOLO](#1-tổng-quan-kiến-trúc--thống-kê-17-phiên-bản-yolo)
   - [1.1. Sơ đồ giao diện Split Screen Chiếm Tối Đa Khung Phải](#11-sơ-đồ-giao-diện-split-screen-chiếm-tối-đà-khung-phải)
   - [1.2. Thống kê tất cả 17 Phiên bản YOLO trong lịch sử Computer Vision](#12-thống-kê-tất-cả-17-phiên-bản-yolo-trong-lịch-sử-computer-vision)
2. [Tính năng Nổi bật: Ghi chú tác dụng sau `#` & Highlight thời gian thực](#2-tính-năng-nổi-bật-ghi-chú-tác-dụng-sau--highlight-thời-gian-thực)
3. [Chi tiết các thông số & Tác dụng của Icon Tooltip (?) khi Huấn luyện](#3-chi-tiết-các-thông-số--tác-dụng-của-icon-tooltip--khi-huấn-luyện)
   - [3.1. Thông số Tiền xử lý (Preprocessing Parameters)](#31-thông-số-tiền-xử-lý-preprocessing-parameters)
   - [3.2. Thông số Tăng cường Dữ liệu (Data Augmentation Parameters)](#32-thông-số-tăng-cường-dữ-liệu-data-augmentation-parameters)
4. [Quy trình Quản lý Template (CRUD Operations)](#4-quy-trình-quản-lý-template-crud-operations)
5. [Mã nguồn HTML / JS / CSS Hoàn chỉnh](#5-mã-nguồn-html--js--css-hoàn-chỉnh)
6. [Hướng dẫn tích hợp vào Hệ thống Flask / YOLO Hub](#6-hướng-dẫn-tích-hợp-vào-hệ-thống-flask--yolo-hub)

---

## 1. TỔNG QUAN KIẾN TRÚC & THỐNG KÊ 17 PHIÊN BẢN YOLO

### 1.1. Sơ đồ giao diện Split Screen Chiếm Tối Đa Khung Phải

Trang quản lý mã Colab được thiết kế dạng **Layout 2 cột (Split Screen 100% Height)**:

```
+-----------------------------------------------------------------------------------------------+
|                                      HEADER & CRUD BAR                                        |
|  [Chọn Template ▼]  [+ Tạo mới Template]  [💾 Lưu Cấu Hình]  [🗑️ Xóa]  [🔄 Reset Mặc Định]   |
+-------------------------------------------------------------+---------------------------------+
| CỘT TRÁI: BẢNG TINH CHỈNH THÔNG SỐ (50% Width)              | CỘT PHẢI: MÃ COLAB (Full Height)|
| ----------------------------------------------------------- | ------------------------------- |
| 📁 1. Chọn Họ YOLO & Checkpoint Weights (?)                  | [A-][15px][A+] [📋Copy] [📥.ipynb|
| 📁 2. Preprocessing (Resize ?, Letterbox ?, Gray ?...)      | ------------------------------- |
| 📁 3. Geometric Augmentations (Rotate ?, Flip ?, Scale ?..)  | # 1. SETUP ENVIRONMENT          |
| 📁 4. Color & HSV Augmentations (Hue ?, Sat ?, Value ?...)   | !pip install ultralytics        |
| 📁 5. Advanced Augmentations (Mosaic ?, Mixup ?, Erasing ?) |                                 |
| 📁 6. Albumentations Pipeline (Blur ?, CLAHE ?...)          | model.train(                    |
|                                                             |   degrees=>> [ 15.0 ] << (HL)   |
| (Cuộn tinh chỉnh bên trái -> Tự động Highlight & Scroll)    |   # Xoay ảnh ngẫu nhiên...      |
|                                                             | )                               |
+-------------------------------------------------------------+---------------------------------+
```

---

### 1.2. Thống kê Tất cả 17 Phiên bản YOLO từ trước đến nay

| STT | Phiên bản YOLO | Năm ra mắt | Tác giả / Tổ chức | Kiến trúc & Đặc điểm nổi bật | Các biến đổi trọng số (Checkpoints) | Thư viện / Package trên Colab |
|-----|----------------|------------|-------------------|--------------------------------|-------------------------------------|--------------------------------|
| 1 | **YOLO26** | 2026 | Ultralytics | End-to-end NMS-free inference cho Edge devices, tối ưu tốc độ cực đại | `yolo26n`, `yolo26s`, `yolo26m`, `yolo26l`, `yolo26x` | `pip install ultralytics` |
| 2 | **YOLO12** | 2025 | Community / Research | Attention-Centric Architecture kết hợp CNN & Self-Attention | `yolov12n`, `yolov12s`, `yolov12m`, `yolov12l`, `yolov12x` | `pip install ultralytics` |
| 3 | **YOLO11** | 2024 | Ultralytics | Chuẩn sản xuất hiện tại (Baseline), tối ưu độ chính xác & bộ nhớ | `yolo11n`, `yolo11s`, `yolo11m`, `yolo11l`, `yolo11x` | `pip install ultralytics` |
| 4 | **YOLOv10** | 2024 | Tsinghua University | NMS-free dual assignments training, giảm Latency tối đa | `yolov10n`, `yolov10s`, `yolov10m`, `yolov10b`, `yolov10l`, `yolov10x` | `pip install ultralytics` |
| 5 | **YOLOv9** | 2024 | WongKinYiu / Ultralytics | Programmable Gradient Information (PGI) & GELAN architecture | `yolov9t`, `yolov9s`, `yolov9m`, `yolov9c`, `yolov9e` | `pip install ultralytics` |
| 6 | **YOLO-World**| 2024 | Tencent / Ultralytics | Real-time Open-Vocabulary Object Detection (Zero-shot detection) | `yolov8s-world`, `yolov8m-world`, `yolov8l-world`, `yolov8x-world` | `pip install ultralytics` |
| 7 | **YOLOv8** | 2023 | Ultralytics | Anchor-free, hỗ trợ Detection, Segmentation, Pose, Classification | `yolov8n`, `yolov8s`, `yolov8m`, `yolov8l`, `yolov8x` | `pip install ultralytics` |
| 8 | **YOLO-NAS** | 2023 | Deci AI | Neural Architecture Search (AutoML), tối ưu độ trễ cứng cho GPU | `yolo_nas_s`, `yolo_nas_m`, `yolo_nas_l` | `pip install super-gradients` |
| 9 | **YOLOv7** | 2022 | WongKinYiu | Extended-ELAN, Trainable Bag-of-Freebies | `yolov7-tiny`, `yolov7`, `yolov7x`, `yolov7-w6`, `yolov7-e6` | `git clone WongKinYiu/yolov7` |
| 10 | **YOLOv6** | 2022 | Meituan | RepVGG backbone, thiết kế riêng cho thiết bị công nghiệp | `yolov6n`, `yolov6s`, `yolov6m`, `yolov6l` | `pip install ultralytics` / Meituan |
| 11 | **YOLOX** | 2021 | Megvii | Anchor-free, Decoupled head, SimOTA label assignment | `yolox-nano`, `yolox-tiny`, `yolox-s`, `yolox-m`, `yolox-l`, `yolox-x` | `pip install yolox` |
| 12 | **PP-YOLOE**| 2022 | Baidu | RepResNet backbone, ESE Attn, Task Alignment Learning | `ppyoloe_crn_s_80e`, `ppyoloe_crn_m_80e`, `ppyoloe_crn_l_80e` | `pip install paddledet` |
| 13 | **YOLOv5** | 2020 | Ultralytics | Phiên bản huyền thoại đưa YOLO vào sản xuất PyTorch thương mại | `yolov5n`, `yolov5s`, `yolov5m`, `yolov5l`, `yolov5x` | `pip install ultralytics` |
| 14 | **YOLOv4** | 2020 | Alexey Bochkovskiy | CSPDarknet53, PANet, Mish activation, Optimal Speed & Accuracy | `yolov4-tiny`, `yolov4` | `git clone AlexeyAB/darknet` |
| 15 | **YOLOv3** | 2018 | Joseph Redmon | Darknet-53, Multi-scale prediction (3 scale), Anchor boxes | `yolov3-tiny`, `yolov3`, `yolov3-spp` | `pip install ultralytics` / Darknet |
| 16 | **YOLOv2** | 2016 | Joseph Redmon | Darknet-19, Anchor boxes, Batch Normalization, High-res classifier | `yolov2-tiny`, `yolov2` | Darknet C framework |
| 17 | **YOLOv1** | 2015 | Joseph Redmon | Đặt nền móng cho Single-stage End-to-end Object Detection | `yolov1` | Darknet C framework |

---

## 2. TÍNH NĂNG NỔI BẬT: GHI CHÚ TÁC DỤNG SAU `#` & HIGHLIGHT THỜI GIAN THỰC

Giao diện đã được nâng cấp với **3 cải tiến quan trọng**:

1. **Tự động thêm Ghi chú giải thích phía sau dấu `#` cho TẤT CẢ thông số**:
   - Tất cả các dòng tham số trong khối mã Colab bên phải (cho Dropdown, Input, Checkbox, Slider) đều được gắn kèm giải thích tác dụng tương đương với nội dung hiển thị trong Tooltip **`?`**.
2. **Khung chứa mã chiếm 100% chiều cao (Full Height Right Column)**:
   - Sử dụng thiết lập Flexbox `flex-1 h-full min-h-0` giúp khung hiển thị mã Colab bên phải mở rộng tối đa theo toàn bộ chiều cao màn hình.
3. **Cỡ chữ lớn & Bộ tăng giảm linh hoạt (A- / A+)**:
   - Mã nguồn hiển thị mặc định ở cỡ chữ **15px (Large Font)** giúp đọc mã dễ dàng hơn hẳn cỡ chữ nhỏ trước đây.
   - Thêm nút điều chỉnh cỡ chữ trực tiếp **`A-`** và **`A+`** từ 12px đến 24px trên thanh công cụ.

---

## 3. CHI TIẾT CÁC THÔNG SỐ & TÁC DỤNG CỦA ICON TOOLTIP (?) KHI HUẤN LUYỆN

Cạnh mỗi thông số tinh chỉnh trên giao diện đều có icon **`?`** dạng Tooltip và đoạn ghi chú sau dấu **`#`** giải thích chi tiết tác động đến quá trình học của mô hình:

### 3.1. Thông số Tiền xử lý (Preprocessing Parameters)

| STT | Tên thông số | Mã tham số | Tác dụng giải thích trong Icon Tooltip (?) & Sau dấu `#` khi Huấn luyện |
|-----|--------------|------------|-------------------------------------------------------------------|
| 1 | **Họ Phiên bản YOLO** | `yolo_family` | Chọn họ kiến trúc YOLO (YOLOv1 -> YOLO26). Định hình cấu trúc mô hình, cơ chế NMS, tốc độ suy luận và độ chính xác mAP. |
| 2 | **Mô hình Trọng số** | `model_version` | Kích thước trọng số (n=Nano, s=Small, m=Medium, l=Large, x=XLarge). Trọng số nhỏ chạy nhanh tốn ít VRAM, trọng số lớn mAP cao hơn nhưng train lâu. |
| 3 | **Task Bài toán** | `task_type` | Loại bài toán: Object Detection (nhận diện vật thể), Instance Segmentation (phân vùng pixel), Image Classification (phân loại), Pose Estimation (tư thế). |
| 4 | **Số Epochs** | `epochs` | Số lần toàn bộ tập ảnh train đi qua mô hình. Quá ít gây Underfitting (chưa học hết), quá nhiều gây Overfitting (học vẹt). |
| 5 | **Batch Size** | `batch_size` | Số lượng ảnh xử lý cùng lúc trong 1 bước cập nhật gradient. Batch lớn giúp gradient ổn định nhưng đòi hỏi VRAM GPU cao. |
| 6 | **Target Size** | `imgsz` | Kích thước vuông ảnh được resize trước khi đưa vào mô hình (vd: 640x640). Ảnh lớn nhận diện vật thể nhỏ tốt hơn nhưng giảm FPS. |
| 7 | **BBox Format** | `bbox_format` | Định dạng nhãn vật thể: YOLO (tâm x,y,w,h [0-1]), COCO (x_min,y_min,w,h), Pascal VOC (x_min,y_min,x_max,y_max). |
| 8 | **Letterbox Padding** | `letterbox` | Thêm viền xám để giữ nguyên tỷ lệ khung hình gốc (Aspect Ratio), tránh làm méo dạng vật thể khi resize. |
| 9 | **Auto-Orient EXIF** | `auto_orient` | Tự động xoay ảnh đúng chiều dựa vào thẻ metadata EXIF của camera trước khi huấn luyện. |
| 10 | **Ảnh Xám** | `grayscale` | Chuyển ảnh RGB (3 kênh) thành ảnh xám (1 kênh). Giảm 66% dung lượng bộ nhớ đầu vào, triệt tiêu nhiễu màu sắc, thích hợp cho OCR, ảnh X-quang. |
| 11 | **CLAHE Equalization** | `histogram_eq` | Cân bằng biểu đồ độ sáng cục bộ. Tăng tương phản và làm nổi bật chi tiết ở vùng quá tối hoặc bị lóa sáng. |

### 3.2. Thông số Tăng cường Dữ liệu (Data Augmentation Parameters)

| STT | Tên thông số | Mã tham số | Tác dụng giải thích trong Icon Tooltip (?) & Sau dấu `#` khi Huấn luyện |
|-----|--------------|------------|-------------------------------------------------------------------|
| 1 | **Rotation Angle** | `degrees` | Xoay ảnh ngẫu nhiên góc [-degrees, +degrees]. Giúp mô hình nhận diện vật thể nghiêng hoặc bị xoay ở các góc khác nhau. |
| 2 | **Translation** | `translate` | Dịch chuyển ảnh theo chiều ngang/dọc (tỷ lệ fraction). Giúp mô hình nhận diện vật thể nằm ở các vị trí khác nhau trong khung hình (Spatial Invariance). |
| 3 | **Scaling Gain** | `scale` | Phóng to/thu nhỏ ảnh ngẫu nhiên theo tỷ lệ gain. Giúp mô hình học nhận diện vật thể ở khoảng cách xa (nhỏ) và gần (to). |
| 4 | **Shear Angle** | `shear` | Kéo xiên/bóp méo góc ảnh theo độ. Giúp mô hình nhận diện vật thể khi nhìn từ các góc nghiêng biến dạng hình học. |
| 5 | **Horizontal Flip** | `fliplr` | Xác suất lật ảnh ngẫu nhiên theo chiều ngang (Trái <-> Phải). Tăng gấp đôi sự phong phú dữ liệu tự nhiên (xe, người, động vật). |
| 6 | **Vertical Flip** | `flipud` | Xác suất lật ảnh ngẫu nhiên theo chiều dọc (Trên <-> Dưới). Thích hợp cho ảnh vệ tinh, flycam nhìn từ trên xuống, soi vi kính. |
| 7 | **HSV Hue** | `hsv_h` | Biến đổi sắc độ màu ngẫu nhiên không gian HSV. Tránh mô hình học vẹt theo màu sắc cố định (vd: biển báo bị phai màu da cam). |
| 8 | **HSV Saturation** | `hsv_s` | Biến đổi độ bão hòa màu ngẫu nhiên (từ màu nhạt sang sặc sỡ). Giúp mô hình hoạt động tốt dưới trời nắng, mưa, sương mù. |
| 9 | **HSV Value / Brightness**| `hsv_v` | Biến đổi độ sáng tối ngẫu nhiên trong kênh Value (HSV). Giúp mô hình nhận diện tốt cả ban ngày, ban đêm lẫn bóng râm. |
| 10 | **Mosaic Augmentation** | `mosaic` | Ghép 4 ảnh ngẫu nhiên thành 1 ảnh duy nhất. Giúp mô hình học nhận diện vật thể trong nhiều bối cảnh nhỏ, cải thiện mAP cho vật thể nhỏ. |
| 11 | **MixUp Augmentation** | `mixup` | Trộn 2 ảnh và nhãn của chúng theo tỷ lệ mờ đục (Alpha Blending). Tạo mẫu train mượt mà, chống hiện tượng Overfitting hiệu quả. |
| 12 | **Copy-Paste Augmentation**| `copy_paste` | Cắt vật thể phân vùng từ ảnh này dán sang vị trí ngẫu nhiên ở ảnh khác. Cực hiệu quả cho bài toán Instance Segmentation. |
| 13 | **Random Erasing / Cutout**| `erasing` | Che phủ các vùng hình chữ nhật ngẫu nhiên trên ảnh. Ép mô hình học nhận diện vật thể ngay cả khi bị che khuất một phần (Occlusion). |
| 14 | **Blur Limit** | `blur_limit` | Làm mờ ảnh ngẫu nhiên bằng bộ lọc Gaussian Blur. Mô phỏng ảnh bị nhòe do rung camera hoặc vật thể di chuyển nhanh. |
| 15 | **CLAHE Limit** | `clahe_limit` | Ngưỡng cắt tương phản (Clip Limit) cho thuật toán CLAHE trong Albumentations. Khống chế mức tăng tương phản để tránh làm khuếch đại hạt nhiễu (noise). |

---

## 4. QUY TRÌNH QUẢN LÝ TEMPLATE (CRUD OPERATIONS)

1. **Create (Tạo mới Template)**: Thêm cấu hình huấn luyện mới.
2. **Read (Đọc & Xem Preset)**: Chọn từ 3 preset chuẩn (Standard YOLO26, High Augmentation, Light Preprocessing).
3. **Update (Cập nhật Template)**: Thay đổi thông số và cập nhật đè.
4. **Delete (Xóa Template)**: Loại bỏ các template không dùng.

---

## 5. MÃ NGUỒN HTML / JS / CSS HOÀN CHỈNH

Vui lòng tham khảo mã nguồn đầy đủ trong file [templates/colab_manager.html](file:///d:/Thuctap/ToolIb-main/ToolIb-main/templates/colab_manager.html).

---

## 6. HƯỚNG DẪN TÍCH HỢP VÀO HỆ THỐNG FLASK / YOLO HUB

1. Đã đăng ký route `@app.route('/colab-manager')` trong `app.py`.
2. Đã thêm Nav Link vào Sidebar trong `templates/base.html`.
3. Truy cập chạy thử tại: `http://localhost:5000/colab-manager`.

---
*Tài liệu cập nhật ghi chú giải thích chi tiết phía sau dấu # trong khung mã Colab cho dự án ToolIb / YOLO Hub.*
