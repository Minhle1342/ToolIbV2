# Hướng dẫn test YOLO11s, YOLO12s và YOLO26s trên màn hình

Tài liệu này dùng cho giao diện `Huấn luyện mô hình YOLO` tại
`https://localhost:5000/colab-manager`.

Luồng chính hiện chỉ hỗ trợ:

- Object Detection.
- `yolo11s.pt`.
- `yolo12s.pt`.
- `yolo26s.pt`.
- Fresh training từ checkpoint chính thức.
- Fine-tune từ một parent `.pt` đã được worker xác thực.
- Một thư viện bộ tham số dùng chung cho cả Fresh và Fine-tune.
- 39 tham số được render từ catalog dùng chung, không lấy từ model map viết cứng
  trên giao diện.
- Nhiều Colab worker chạy song song.

Hai phần `Legacy direct Colab smoke test` và `Legacy generator` chỉ là đường lui
để kiểm tra tương thích cũ. Không dùng hai phần này cho bài acceptance chính.

## 1. Kết quả cuối cùng cần chứng minh

Mỗi model phải đi qua chuỗi sau:

```text
Chọn YOLO model
→ chọn ToolIb project
→ chọn bộ tham số trong database
→ queue training job
→ scheduler giao job cho Colab worker
→ worker train và trả artifact
→ ToolIb import ONNX ở trạng thái inactive
→ chạy inference bằng ảnh thật
→ bounding box và class đúng
```

Chỉ đánh dấu `PASS` khi có bằng chứng training thật trên Colab và inference thật
trên ToolIbV2. Test local hoặc test contract không thay thế bước này.

## 2. Chuẩn bị trước khi mở màn hình

### 2.1. ToolIb project

Chuẩn bị ít nhất một project nhỏ:

- Có ảnh đã gán nhãn.
- Có ít nhất một class.
- Có đủ ảnh để tạo cả `train` và `val`.
- Nên có 2-5 ảnh riêng để test inference.
- Không dùng project đang chỉnh sửa dở.

Để smoke test nhanh, dùng dataset nhỏ và bộ tham số 1 epoch.

### 2.2. Mỗi Google Colab worker

Với mỗi worker cần:

1. Một Colab runtime riêng.
2. GPU đã được bật.
3. Notebook mới nhất:

   ```text
   notebooks/Colab_FastAPI_PoC.ipynb
   ```

4. Colab Secret tên `TOOLIB_COLAB_API_TOKEN`.
5. Một Quick Tunnel URL riêng.

Không dùng Cloudflare R2 `Token Value` làm worker bearer token. Hai credential
này phục vụ hai mục đích khác nhau.

### 2.3. Chạy notebook

Trong Google Colab:

1. Chọn `Runtime` → `Change runtime type` → `GPU`.
2. Chạy Cell 1 đến Cell 4 theo thứ tự.
3. Xác nhận `CUDA available: True`.
4. Xác nhận notebook dùng Ultralytics `8.4.110`.
5. Xác nhận health/catalog có đúng ba model:

   ```text
   yolo11s.pt
   yolo12s.pt
   yolo26s.pt
   ```

6. Copy URL dạng:

   ```text
   https://....trycloudflare.com
   ```

7. Giữ Colab runtime hoạt động trong toàn bộ bài test.

### 2.4. Chạy training preflight trước khi mở giao diện

Từ thư mục repository, chạy kiểm tra offline. Lệnh này chỉ đọc catalog, worker
source và notebook; không khởi động Flask, scheduler hoặc worker:

```powershell
.\.venv\Scripts\python.exe scripts\training_preflight.py
```

Kết quả đúng khi chưa truyền database/worker:

```text
[PASS] catalogs
[PASS] generated-worker
[PASS] notebook-sync
[SKIP] phase9-database
[SKIP] worker-health
READY
```

Khi đã có database URI và Colab worker, chạy acceptance nghiêm ngặt. Không đặt
token trực tiếp trong command history:

```powershell
$env:YOLO_LABELING_DB_URI = '<database-uri>'
$env:TOOLIB_COLAB_API_TOKEN = '<worker-bearer-token>'
.\.venv\Scripts\python.exe scripts\training_preflight.py `
  --worker-url 'https://....trycloudflare.com' `
  --strict
```

`--strict` chỉ trả `READY` khi catalog/notebook, Phase 9 database và worker GPU
đều sẵn sàng, đúng version/hash và scheduler chấp nhận Fresh/Fine-tune.

## 3. Mở giao diện mới

1. Khởi động ToolIbV2 bằng `toollb.bat`, `run.ps1` hoặc cách chạy local hiện tại.
2. Mở:

   ```text
   https://localhost:5000/colab-manager
   ```

3. Nếu trình duyệt cảnh báo chứng chỉ local, chọn `Advanced` và tiếp tục tới
   `localhost`.
4. Xác nhận đầu trang hiển thị:

   ```text
   Huấn luyện mô hình YOLO
   YOLO11s · YOLO12s · YOLO26s
   ```

5. Xác nhận `Loại nhận diện` chỉ hiển thị
   `Nhận diện vật thể (Object Detection)`.
6. Xác nhận không có lựa chọn Segment, Classify hoặc Pose trong luồng chính.

## 4. Kiểm tra các phần legacy đã được thu gọn

Khi mới mở trang:

- `Legacy direct Colab smoke test` phải đang đóng.
- Cột code generator bên phải phải đang ẩn.
- `Công cụ cũ dành cho kỹ thuật` phải đang đóng.
- URL và token worker phải nằm trong panel `Thiết lập máy huấn luyện`, sau
  Bước 5 và đang thu gọn mặc định.

Chỉ khi cần kiểm tra tương thích cũ:

1. Mở `Công cụ cũ dành cho kỹ thuật`.
2. Bấm `Mở trình tạo mã Colab cũ`.
3. Xác nhận cột code và template controls xuất hiện.
4. Bấm lại để ẩn.

Không cần mở legacy generator để queue Fresh hoặc Fine-tune.

## 5. Đăng ký một Colab worker

Ở banner `Tài nguyên huấn luyện` đầu trang, bấm `Đăng ký Colab`. Trang sẽ mở
panel `Thiết lập máy huấn luyện` sau Bước 5 và đưa con trỏ vào ô địa chỉ.

1. Tại `Địa chỉ kết nối Colab`, dán URL của Colab.
2. Tại `Mã bảo mật của Colab`, nhập đúng giá trị của
   `TOOLIB_COLAB_API_TOKEN`.
3. Nhập tên worker, ví dụ:

   ```text
   Colab T4 account A
   ```

4. Bấm `Thêm máy`.
5. Trên thẻ máy vừa thêm, bấm `Kiểm tra kết nối`.
6. Xác nhận worker hiển thị online, có GPU và có dòng:

   ```text
   Presets ready
   ```

Nếu card hiển thị `upgrade worker`, worker đang chạy notebook cũ và không nhận
job Fresh dùng parameter preset. Upload notebook mới và chạy lại runtime.

Nếu Quick Tunnel đổi URL nhưng vẫn là cùng runtime/worker:

1. Bấm `Quản lý Colab` ở banner đầu trang.
2. Dán địa chỉ và mã bảo mật mới vào panel vừa mở.
3. Trên đúng thẻ máy cũ, bấm `Cập nhật địa chỉ`.
4. Bấm `Kiểm tra kết nối`.

Không tạo worker trùng chỉ vì URL tunnel thay đổi.

## 6. Tạo hai bộ tham số smoke test

Trong Bước 3 `Chọn cách huấn luyện`, tìm `Chọn cấu hình huấn luyện`.

Phase C2 có 39 fields do catalog cung cấp, chia thành 5 nhóm:

- Core training: 6 fields (`epochs`, `batch`, `imgsz`, `patience`, `fraction`,
  `freeze`).
- Optimizer and schedule: 9 fields (`optimizer_mode`, `optimizer`, `lr0`, `lrf`,
  `momentum`, `weight_decay`, `warmup_epochs`, `cos_lr`, `nbs`).
- Runtime and memory: 6 fields (`rect`, `cache`, `amp`, `compile`,
  `channels_last`, `seed`).
- Detection loss: 3 fields (`box`, `cls`, `dfl`).
- Augmentation: 15 fields (`hsv_h`, `hsv_s`, `hsv_v`, `mosaic`, `scale`,
  `close_mosaic`, `degrees`, `translate`, `shear`, `perspective`, `flipud`,
  `fliplr`, `mixup`, `copy_paste`, `multi_scale`).

### 6.1. Smoke Auto 1 epoch cho Fresh

Trong Auto mode, worker gửi `optimizer=auto` cho Ultralytics. Giao diện phải
ẩn/disable `optimizer` cụ thể và `lr0`; requested `lr0` không được trình bày
như một effective control. Runtime sẽ ghi optimizer class và initial effective
LR do trainer thực sự chọn.

1. Bấm `Tạo cấu hình riêng`.
2. Nhập:

   | Trường | Giá trị smoke test |
   |---|---:|
   | Tên bộ tham số | `Smoke Auto 1 epoch` |
   | Epochs | `1` |
   | Batch | `2` |
   | Image size | `320` |
   | Optimizer mode | `Auto (Ultralytics resolves)` |
   | Final LR factor `lrf` | `0.01` |
   | Freeze layers | `0` cho Fresh |
   | Dataset fraction | `1.0` |
   | Multi-scale range | `0.0` |
   | torch.compile mode | `Off` |
   | Channels-last memory | `Off` |
   | Mosaic | `1.0` |
   | Scale | `0.5` |
   | Close mosaic | `0` |
   | Degrees | `0` |
   | Translate | `0.1` |
   | Mixup | `0` |
   | Copy-paste | `0` |
   | Seed | `42` |

3. Bấm `Lưu cấu hình`.
4. Mở lại preset và xác nhận `lr0` không xuất hiện trong Auto mode.
5. Tick đúng `Smoke Auto 1 epoch`.

### 6.2. Smoke Explicit 1 epoch cho Fine-tune

Trong Explicit mode, `optimizer` và `lr0` đều bắt buộc. Worker phải truyền cả
hai giá trị; requested config và effective runtime values được lưu riêng.

1. Bấm `Tạo cấu hình riêng`.
2. Nhập:

   | Trường | Giá trị smoke test |
   |---|---:|
   | Tên bộ tham số | `Smoke Explicit 1 epoch` |
   | Epochs | `1` |
   | Batch | `2` |
   | Image size | `320` |
   | Optimizer mode | `Explicit` |
   | Optimizer | `AdamW` |
   | Requested learning rate `lr0` | `0.001` |
   | Final LR factor `lrf` | `0.01` |
   | Freeze layers | `10` |
   | Box / Class / DFL loss gain | `7.5 / 0.5 / 1.5` |
   | Nominal batch size `nbs` | `64` |
   | Mosaic | `0.5` |
   | Seed | `42` |

3. Bấm `Lưu cấu hình`.
4. Mở lại preset và xác nhận `AdamW` cùng `lr0=0.001` vẫn hiển thị.
5. Tick đúng `Smoke Explicit 1 epoch` khi test Fine-tune.

Nếu chỉ muốn mỗi model tạo một job, bỏ tick các preset khác.

Quy tắc số lượng job:

```text
Số project được chọn × số bộ tham số được tick = số training job
```

Ví dụ: 2 project × 3 preset = 6 job.

Lưu ý: trong luồng chính, `Epochs`, `Batch`, `Image size`, optimizer/schedule,
freeze và augmentation được lấy từ `Chọn cấu hình huấn luyện`. Các field cũ
phục vụ legacy direct/generator không phải source of truth cho batch mới.

## 7. Test Fresh YOLO12s

### 7.1. Chọn model

Trong Bước 1 `Chọn mô hình`:

1. Chọn `YOLO12 Small`.
2. Xác nhận checkpoint là `yolo12s.pt`.
3. Xác nhận `Loại nhận diện` là
   `Nhận diện vật thể (Object Detection)`.

### 7.2. Chọn dữ liệu và bắt đầu

Trong Bước 2 `Chọn dữ liệu`:

1. Nhập tên batch:

   ```text
   Acceptance Fresh YOLO12s
   ```

2. Chọn một ToolIb project.
3. Giữ split `80 / 20 / 0`.
4. Giữ bật `Bỏ qua ảnh đã đánh dấu cần xem lại`.
5. Giữ tắt `Dùng cả ảnh nền chưa gán nhãn` trong lần test đầu.
6. Trong `Tùy chọn dữ liệu và chạy lại`, giữ `Số lần thử tối đa = 3` và
   `Độ ưu tiên = 0`.

Trong Bước 3 `Chọn cách huấn luyện`:

1. Chọn mode:

   ```text
   Tạo model mới từ model YOLO chuẩn
   ```

2. Tick duy nhất preset `Smoke Auto 1 epoch`.
3. Xác nhận nút hiển thị `Bắt đầu huấn luyện model mới`.
4. Bấm nút đúng một lần.

### 7.3. Theo dõi

Trong Bước 5 `Theo dõi kết quả`:

1. Xác nhận `Đang chờ` tăng.
2. Nếu hệ thống chưa tự phân công, bấm `Phân công ngay` một lần.
3. Xác nhận task chuyển theo chuỗi gần giống:

   ```text
   queued
   → preparing_dataset
   → uploading_dataset
   → remote_running
   → downloading_artifacts
   → importing_model
   → succeeded
   ```

4. Xác nhận worker card hiển thị active job trong lúc train.
5. Xác nhận batch kết thúc `succeeded`.

Điều kiện PASS:

- Task dùng model `yolo12s.pt`.
- Parameter snapshot là `Smoke Auto 1 epoch`.
- Requested config ghi `optimizer_mode=auto`, `optimizer=auto`, `lr0=null`.
- Effective config ghi optimizer class và initial effective LR từ trainer.
- Worker thực hiện đúng 1 epoch, batch 2, image size 320.
- Có `best.pt`, `best.onnx` và `manifest.json`.
- ONNX được import vào ToolIbV2 ở trạng thái inactive.

## 8. Test Fresh YOLO26s

Lặp lại Phần 7 với:

```text
Model: YOLO26 Small
Checkpoint: yolo26s.pt
Batch name: Acceptance Fresh YOLO26s
Mode: Fresh
Preset: Smoke Auto 1 epoch
```

Điều kiện PASS giống YOLO12s.

YOLO11s đã chạy ổn có thể chỉ test hồi quy với cùng preset nếu cần xác nhận thay
đổi UI không làm hỏng baseline.

## 9. Chạy YOLO12s và YOLO26s song song bằng hai worker

Chuẩn bị hai Colab runtime độc lập:

```text
Worker A, capacity 1
Worker B, capacity 1
```

Đăng ký cả hai trong `Thiết lập máy huấn luyện` và xác nhận
`Máy sẵn sàng: 2/2`.

Sau đó:

1. Queue batch Fresh YOLO12s theo Phần 7.
2. Không chờ nó hoàn thành.
3. Đổi model sang YOLO26s.
4. Queue batch Fresh YOLO26s theo Phần 8.
5. Theo dõi Bước 5 `Theo dõi kết quả`.

Kết quả đúng:

```text
YOLO12 task → Worker A → running
YOLO26 task → Worker B → running
```

Worker A và Worker B có thể đổi model cho nhau; điều cần chứng minh là hai task
`running` cùng lúc trên hai worker khác nhau.

Nếu chỉ một task chạy:

- Xác nhận cả hai worker online.
- Xác nhận cả hai có `Presets ready`.
- Xác nhận `allowed_models` của cả hai có YOLO12s và YOLO26s.
- Xác nhận worker thứ hai không có active job cũ.
- Bấm `Phân công ngay` một lần.

## 10. Test Fine-tune YOLO12/YOLO26

Fine-tune dùng cùng Bước 3 `Chọn cách huấn luyện`; không còn panel riêng.

### 10.1. Chuẩn bị parent `.pt`

1. Chọn đúng một ToolIb project trong Bước 2 `Chọn dữ liệu`.
2. Tại `Bạn muốn làm gì?`, chọn:

   ```text
   Tiếp tục cải thiện model .pt hiện có
   ```

3. Các field parent phải xuất hiện.
4. Nhập tên parent.
5. Chọn file `.pt` của YOLO12s hoặc YOLO26s.
6. Bấm `Tải lên và kiểm tra`.
7. Chờ trạng thái parent `Ready`.
8. Chọn parent trong dropdown `Chọn model đã kiểm tra`.
9. Nếu cần, bấm `Kiểm tra lại model đã chọn`.

### 10.2. Chọn preset fine-tune smoke

Tick duy nhất `Smoke Explicit 1 epoch` đã tạo ở Phần 6.2. Xác nhận trước khi
queue:

```text
optimizer_mode = explicit
optimizer = AdamW
requested lr0 = 0.001
freeze = 10
```

Không dùng `Smoke Auto 1 epoch` cho bài acceptance Explicit này, vì Auto mode
không coi requested `lr0` là effective control.

### 10.3. Queue Fine-tune

1. Nhập tên batch, ví dụ `Acceptance Fine-tune YOLO12s`.
2. Xác nhận chỉ một project được chọn.
3. Xác nhận parent đang `Ready`.
4. Xác nhận nút là `Bắt đầu cải thiện model`.
5. Bấm một lần.
6. Theo dõi task tới `succeeded`.

Fine-tune PASS khi:

- Task dùng đúng parent model.
- Parameter snapshot đúng preset đã chọn.
- Requested config giữ `AdamW + lr0=0.001`.
- Effective config ghi optimizer class và initial LR đọc từ trainer runtime.
- Artifact mới được tạo; không ghi đè parent.
- Model mới được import ở trạng thái inactive.
- Inference ảnh thật chạy đúng.

Lặp lại cho parent YOLO26s.

## 11. Test chuyển mode trên giao diện

Thực hiện trước khi acceptance thật:

1. Chọn `Tạo model mới từ model YOLO chuẩn`.
2. Xác nhận parent fields bị ẩn.
3. Xác nhận cấu hình baseline cho model mới được đề xuất.
4. Chọn `Tiếp tục cải thiện model .pt hiện có`.
5. Xác nhận parent fields xuất hiện.
6. Xác nhận cấu hình baseline Fine-tune được đề xuất.
7. Chuyển lại `Tạo model mới từ model YOLO chuẩn`.
8. Xác nhận parent fields lại bị ẩn.

Nếu lựa chọn `Tiếp tục cải thiện model .pt hiện có` bị vô hiệu hóa, kiểm tra
feature flag Fine-tune và trạng thái migration trước khi test tiếp.

## 12. Test inference sau khi training

Với từng ONNX mới:

1. Mở `Thí nghiệm mô hình`.
2. Chọn model YOLO12 hoặc YOLO26 vừa import.
3. Có thể chọn thêm YOLO11 baseline để so sánh.
4. Upload ít nhất:
   - Hai ảnh chắc chắn có vật thể.
   - Một ảnh khó.
   - Một ảnh không có vật thể nếu có thể.
5. Giữ Confidence `25%`, IoU `45%` trong lần đầu.
6. Bấm `Chạy Thí nghiệm`.

Inference PASS khi:

- Model ONNX load thành công.
- Bounding box nằm đúng vật thể.
- Class name đúng.
- Không có box âm hoặc vượt ảnh bất thường.
- Ảnh background không sinh quá nhiều false positive.

Chỉ sau bước này mới bấm `Sử dụng cho Auto-label (Detection)`.

## 13. Failure map nhanh

| Hiện tượng | Kiểm tra đầu tiên | Cách xử lý |
|---|---|---|
| Worker `offline` | Colab runtime và tunnel | Chạy lại Cell 4, bấm `Quản lý Colab`, cập nhật URL bằng `Cập nhật địa chỉ`, rồi `Kiểm tra kết nối` |
| Worker `upgrade worker` | Notebook/capability | Upload notebook mới, thêm/cập nhật máy và kiểm tra kết nối lại |
| Job nằm `waiting_for_worker` | `allowed_models`, `Presets ready`, capacity | Dùng worker mới hỗ trợ đúng model và parameter presets |
| Tạo quá nhiều job | Số project × số preset | Giảm xuống tối đa 100 job mỗi batch |
| Fine-tune không queue | Parent hoặc số project | Parent phải Ready và chỉ chọn đúng một project |
| CUDA out of memory | Batch và image size trong preset | Đổi batch 1-2, image size 320 |
| Job `worker_lost` | Runtime/tunnel và checkpoint store | Reconnect trong grace period hoặc để scheduler resume trên worker tương thích |
| ONNX import được nhưng box sai | Dataset/class mapping/export | Không activate; kiểm tra ảnh thật, label và class order |

## 14. Phiếu ghi kết quả

| Bài test | YOLO11s | YOLO12s | YOLO26s |
|---|---|---|---|
| Worker nhận đúng model | Đã biết/PASS/FAIL | PASS/FAIL | PASS/FAIL |
| Fresh `Smoke Auto 1 epoch` | Đã biết/PASS/FAIL | PASS/FAIL | PASS/FAIL |
| Có `best.pt` | Đã biết/PASS/FAIL | PASS/FAIL | PASS/FAIL |
| Có `best.onnx` | Đã biết/PASS/FAIL | PASS/FAIL | PASS/FAIL |
| ONNX import inactive | Đã biết/PASS/FAIL | PASS/FAIL | PASS/FAIL |
| Inference ảnh thật | Đã biết/PASS/FAIL | PASS/FAIL | PASS/FAIL |
| Fine-tune `Smoke Explicit 1 epoch` | Chưa test/PASS/FAIL | PASS/FAIL | PASS/FAIL |

Ghi thêm cho từng job:

- Batch ID và Task ID.
- Worker ID/GPU.
- Model và training mode.
- Parameter set name/version.
- Dataset snapshot ID.
- Thời gian bắt đầu/kết thúc.
- Artifact path.
- Ảnh chụp status `succeeded`.
- Ảnh inference có bounding box.

## 15. Stop condition

Không tuyên bố YOLO12s hoặc YOLO26s đã được hỗ trợ hoàn chỉnh nếu thiếu một
trong ba bằng chứng:

1. Colab worker train thật tới `succeeded`.
2. ToolIbV2 import được ONNX ở trạng thái inactive.
3. Inference ảnh thật có box và class đúng.

Test local xác nhận code và contract. Ba bằng chứng trên mới xác nhận flow vận
hành thực tế.
