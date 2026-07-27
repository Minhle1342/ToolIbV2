# ToolIbV2 Colab FastAPI PoC Runbook

## Phase 4 - flow hiện tại (ưu tiên đọc phần này)

Phase 4 thay thế bước export, nén ZIP và upload Drive thủ công bằng flow:

```text
Chọn ToolIb project trên /colab-manager
→ ToolIb tạo snapshot YOLO riêng có dataset_id
→ ToolIb stream dataset.zip có bearer token tới Colab
→ Colab kiểm tra UUID + SHA-256 + nội dung ZIP
→ Colab lưu MyDrive/ToolIb_PoC/datasets/<dataset_id>/dataset.zip
→ Start Train gửi đúng dataset_id
→ Training history lưu liên kết project + dataset snapshot + remote job
```

Các phần bên dưới mô tả ZIP thủ công chỉ còn là fallback để test notebook độc
lập. Khi test UI Phase 4, không cần tự tạo hoặc copy
`MyDrive/ToolIb_PoC/dataset.zip`.

### Thao tác thật từ đầu đến cuối

1. Upload lại file `notebooks/Colab_FastAPI_PoC.ipynb` hiện tại lên Colab.
2. Chọn GPU runtime và cấp quyền cho secret `TOOLIB_COLAB_API_TOKEN`.
3. Chạy Cell 1 đến Cell 4. Cell 2 không còn báo lỗi nếu không có
   `MyDrive/ToolIb_PoC/dataset.zip`.
4. Giữ Cell 4 và runtime hoạt động, rồi copy Quick Tunnel URL.
5. Mở ToolIbV2 tại `/colab-manager`, nhập URL và cùng bearer token, sau đó bấm
   `Kiểm tra`.
6. Trong thẻ `Training dataset snapshot`, chọn đúng ToolIb project.
7. Giữ split mặc định `80/20/0` hoặc nhập split khác có tổng bằng 100; train và
   val đều phải lớn hơn 0.
8. Bấm `Chuẩn bị & tải dataset lên Colab`. Chờ trạng thái `uploaded` và ghi lại
   8 ký tự đầu của `dataset_id`.
9. Chọn `yolo11n.pt`, task `detect`, epochs, batch và imgsz rồi bấm
   `Start Train`. Nút này bị khóa nếu chưa có snapshot `uploaded`.
10. Trong Training history, xác nhận job hiển thị cùng `dataset_id`.
11. Khi job `succeeded`, xác nhận Drive có:

```text
MyDrive/ToolIb_PoC/datasets/<dataset_id>/dataset.zip
MyDrive/ToolIb_PoC/datasets/<dataset_id>/manifest.json
MyDrive/ToolIb_PoC/artifacts/<job_id>/best.pt
MyDrive/ToolIb_PoC/artifacts/<job_id>/best.onnx
MyDrive/ToolIb_PoC/artifacts/<job_id>/manifest.json
```

12. Import ONNX từ Training history và giữ model inactive cho đến khi inference
    smoke test đạt.

Nếu sửa ảnh, nhãn, classes hoặc split sau khi đã tạo snapshot, hãy bấm lại
`Chuẩn bị & tải dataset lên Colab`. ToolIb sẽ tạo `dataset_id` mới; snapshot cũ
không bị ghi đè.

### API contract bổ sung của Phase 4

ToolIb local:

```http
POST /api/training-datasets
Content-Type: application/json

{
  "project_id": 1,
  "splits": {"train": 80, "val": 20, "test": 0},
  "exclude_flagged": true,
  "include_unlabeled": false
}
```

```http
POST /api/training-datasets/<local_dataset_pk>/upload
Content-Type: application/json

{
  "remote_api_url": "https://<random>.trycloudflare.com",
  "api_token": "<bearer token>"
}
```

ToolIb backend mở file ZIP và stream tới Colab; browser không đọc toàn bộ ZIP
vào RAM. Token chỉ dùng cho request này, không nằm trong
`training_datasets` hoặc `training_jobs`.

Colab:

```http
POST /api/datasets
Authorization: Bearer <token>
Content-Type: multipart/form-data

dataset_id=<uuid>
sha256=<64 hex characters>
archive=@dataset.zip
```

Training request Phase 4:

```json
{
  "model": "yolo11n.pt",
  "epochs": 2,
  "batch": 4,
  "imgsz": 640,
  "dataset_id": "<uuid>"
}
```

Colab không nhận đường dẫn dataset do client cung cấp. Nó tự ánh xạ UUID tới
Drive root cố định, từ chối checksum sai, path traversal, symlink trong ZIP,
train/val rỗng, hoặc cùng `dataset_id` nhưng archive khác.

## Mục tiêu

Runbook này kiểm tra flow tạm thời:

```text
ToolIbV2 export dataset
→ ZIP trên Google Drive
→ Colab giải nén vào local disk
→ FastAPI nhận job
→ Ultralytics train bằng GPU
→ export best.pt và best.onnx
→ lưu artifact vào Google Drive
→ import ONNX lại ToolIbV2
```

Notebook sử dụng:

- `notebooks/Colab_FastAPI_PoC.ipynb`

Đây là PoC, không phải production deployment. Cloudflare Quick Tunnel có URL động và không có SLA.

## 1. Phạm vi

PoC hiện hỗ trợ:

- Ultralytics YOLO detection.
- `yolo11n.pt` và `yolo11s.pt`.
- Một training job tại một thời điểm.
- Dataset YOLO được tạo bởi ToolIbV2.
- Bearer token.
- Poll trạng thái job.
- Artifact được lưu về Google Drive.
- Gửi job và theo dõi trực tiếp từ màn hình `/colab-manager`.
- Lưu training history vào SQLite của ToolIbV2.
- Resume polling sau khi reload trang.
- Tải và import `best.onnx` vào Model Manager bằng một nút.

PoC chưa hỗ trợ:

- Upload dataset qua public API.
- Nhiều training job hoặc nhiều GPU.
- Resume job sau khi Colab runtime bị dừng.
- Các family YOLO-NAS, YOLOv7, YOLOX, PP-YOLOE hoặc Darknet.
- Hủy training job từ UI.
- Tự động activate model vừa import.

## 2. Chuẩn bị dataset

Trong ToolIbV2:

1. Mở màn hình Export.
2. Chọn project/images/split cần train.
3. Chọn format YOLO.
4. Chạy `Export & Generate data.yaml`.
5. Kiểm tra thư mục `exported_dataset`.

Cấu trúc mong đợi:

```text
exported_dataset/
├── data.yaml
├── images/
│   ├── train/
│   └── val/
└── labels/
    ├── train/
    └── val/
```

Nén toàn bộ thư mục thành `dataset.zip`. ZIP có thể chứa trực tiếp `data.yaml` hoặc chứa thêm thư mục `exported_dataset/`; notebook tự tìm YAML ở cả hai trường hợp.

Upload file tới:

```text
MyDrive/ToolIb_PoC/dataset.zip
```

Không giải nén và train trực tiếp trên Drive. Notebook sẽ giải nén vào `/content/toolib_poc/dataset` để giảm I/O trên Drive.

## 3. Tạo API token

Trong Google Colab:

1. Mở `Secrets`.
2. Tạo secret tên `TOOLIB_COLAB_API_TOKEN`.
3. Giá trị nên là chuỗi ngẫu nhiên ít nhất 16 ký tự.
4. Bật quyền truy cập secret cho notebook.

Ví dụ tạo token trên PowerShell:

```powershell
$rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
$bytes = New-Object byte[] 32
$rng.GetBytes($bytes)
$colabToken = -join ($bytes | ForEach-Object { $_.ToString('x2') })
$rng.Dispose()
$colabToken
```

Không paste token trực tiếp vào source notebook và không chia sẻ notebook kèm output chứa token.

## 4. Khởi chạy notebook

1. Upload `notebooks/Colab_FastAPI_PoC.ipynb` lên Google Colab.
2. Chọn `Runtime → Change runtime type → GPU`.
3. Chạy cell cài dependency.
4. Chạy cell mount Drive và validate dataset.
5. Xác nhận số ảnh train/val và class list đúng.
6. Chạy cell tạo FastAPI app.
7. Chạy cell Uvicorn + Cloudflare Tunnel.
8. Copy URL `https://<random>.trycloudflare.com`.

Không chạy lại cell tạo app hoặc server khi training đang hoạt động.

Notebook Phase 2 cho phép CORS từ ToolIbV2 chạy tại:

- `http://localhost:5000`
- `https://localhost:5000`
- `http://127.0.0.1:5000`
- `https://127.0.0.1:5000`

Nếu đã upload notebook trước Phase 2, phải upload lại file hiện tại và chạy lại từ đầu. Thay đổi CORS trong repo không tự cập nhật notebook đang mở trên Colab.

## 5. API contract

### Health

```http
GET /health
```

Không cần token. Response chỉ chứa trạng thái API, GPU và active job ID.

### Submit training

```http
POST /api/train
Authorization: Bearer <token>
Content-Type: application/json
```

Body:

```json
{
  "model": "yolo11n.pt",
  "epochs": 1,
  "batch": 4,
  "imgsz": 640
}
```

Response thành công:

```http
202 Accepted
```

```json
{
  "job_id": "<uuid>",
  "status": "queued"
}
```

Nếu đang có job:

```http
409 Conflict
```

### Job status

```http
GET /api/jobs/<job_id>
Authorization: Bearer <token>
```

Các trạng thái:

- `queued`
- `running`
- `succeeded`
- `failed`

### Download ONNX artifact

```http
GET /api/jobs/<job_id>/artifacts/onnx
Authorization: Bearer <token>
```

Endpoint chỉ trả file khi:

- Job tồn tại và có trạng thái `succeeded`.
- Artifact ONNX nằm trong đúng thư mục Drive của job.
- File có extension `.onnx`.

Client không được gửi filesystem path cần tải.

## 6. Test bằng PowerShell

Thiết lập URL và token:

```powershell
$colabUrl = 'https://example.trycloudflare.com'
$colabToken = 'replace-with-your-secret'
$headers = @{ Authorization = "Bearer $colabToken" }
```

Health:

```powershell
Invoke-RestMethod -Method Get -Uri "$colabUrl/health"
```

Submit một job một epoch:

```powershell
$body = @{
    model  = 'yolo11n.pt'
    epochs = 1
    batch  = 4
    imgsz  = 640
} | ConvertTo-Json

$submitted = Invoke-RestMethod `
    -Method Post `
    -Uri "$colabUrl/api/train" `
    -Headers $headers `
    -ContentType 'application/json' `
    -Body $body

$submitted
$jobId = $submitted.job_id
```

Poll trạng thái:

```powershell
do {
    $job = Invoke-RestMethod `
        -Method Get `
        -Uri "$colabUrl/api/jobs/$jobId" `
        -Headers $headers

    $job | ConvertTo-Json -Depth 5
    if ($job.status -in @('succeeded', 'failed')) {
        break
    }
    Start-Sleep -Seconds 10
} while ($true)
```

## 7. Test từ UI ToolIbV2

1. Giữ cell server/tunnel trên Colab đang chạy.
2. Khởi động ToolIbV2 tại `localhost:5000`.
3. Mở `/colab-manager`.
4. Chọn family `YOLO11`.
5. Chọn `yolo11n.pt` hoặc `yolo11s.pt`.
6. Chọn task `detect`, epochs, batch và image size hợp lệ.
7. Trong panel `Remote Colab API (PoC)`, paste Quick Tunnel URL.
8. Paste cùng giá trị của Colab Secret `TOOLIB_COLAB_API_TOKEN`.
9. Bấm `Kiểm tra`; trạng thái phải là `Online · GPU`.
10. Bấm `Start Train`; UI phải hiện job ID và tự poll khoảng bốn giây một lần.
11. Chờ trạng thái `succeeded` hoặc `failed`.
12. Nếu thành công, kiểm tra UI hiển thị path `best.pt`, `best.onnx` và `manifest.json`.
13. Kiểm tra job xuất hiện trong `Training history`.
14. Reload trang; history vẫn phải còn.
15. Với job `succeeded`, bấm `Import ONNX`.
16. Mở Model Manager bằng link `Model #<id>`.
17. Xác nhận model vừa import đang `inactive`.

Quy tắc lưu trên browser:

- Endpoint được lưu trong `localStorage`, vì Quick Tunnel URL không phải secret.
- Token chỉ được lưu trong `sessionStorage`; đóng tab sẽ xóa token.
- Token không được lưu trong template và không được ghi ra console.
- Nút `Dừng theo dõi` chỉ dừng polling của UI, không hủy training trên Colab.

Nếu Colab trả `409`, UI sẽ lấy `active_job_id` và chuyển sang theo dõi job đang chạy.

Model ngoài `yolo11n.pt` và `yolo11s.pt` vẫn dùng được với phần Code Generator, nhưng nút Remote `Start Train` sẽ bị khóa.

Nếu tab đã đóng hoặc token không còn trong `sessionStorage`:

1. Nhập lại Quick Tunnel URL và bearer token.
2. Trong Training history, bấm `Resume`.

Nếu tunnel không phản hồi, job local được đánh dấu `unreachable`; trạng thái remote cuối cùng không bị đổi thành `failed`.

## 8. Test bảo vệ API

Không có token phải trả `401`:

```powershell
Invoke-WebRequest `
    -Method Post `
    -Uri "$colabUrl/api/train" `
    -ContentType 'application/json' `
    -Body $body `
    -SkipHttpErrorCheck
```

Submit request thứ hai khi job đầu đang chạy phải trả `409`.

Các giá trị sau phải bị từ chối với `422`:

- Model ngoài `yolo11n.pt`, `yolo11s.pt`.
- `epochs` nhỏ hơn 1 hoặc lớn hơn 100.
- `batch` nhỏ hơn 1 hoặc lớn hơn 32.
- `imgsz` ngoài `320, 416, 512, 640, 768`.

API không nhận `dataset_yaml`, `drive_save_dir` hoặc filesystem path từ client.

## 9. Kiểm tra artifact

Khi job thành công, response status chứa:

```text
MyDrive/ToolIb_PoC/artifacts/<job_id>/best.pt
MyDrive/ToolIb_PoC/artifacts/<job_id>/best.onnx
MyDrive/ToolIb_PoC/artifacts/<job_id>/manifest.json
```

Có thể có thêm:

- `results.csv`
- `args.yaml`

Manifest phải ghi:

- Job ID.
- Model.
- Epochs.
- Batch.
- Image size.
- Dataset YAML đã dùng.
- Training save directory.
- Artifact paths.
- Finish timestamp.

Nếu job lỗi, notebook cố gắng ghi:

```text
MyDrive/ToolIb_PoC/artifacts/<job_id>/failure.json
```

## 10. Import ONNX vào ToolIbV2

Flow Phase 3:

1. Tại Training history, bấm `Import ONNX`.
2. Browser tải artifact bằng bearer token từ Colab.
3. Browser upload file vào `/api/models`.
4. ToolIbV2 tạo `AIModel` type `detection`.
5. Model được giữ `inactive`.
6. Mở link `Model #<id>` để tới Model Manager.
7. Chạy inference smoke test trên một ảnh đã biết.
8. Chỉ activate sau khi smoke test đạt.

Nếu Quick Tunnel đã dừng trước khi import, có thể dùng flow thủ công:

1. Tải `best.onnx` từ Google Drive về máy.
2. Mở Model Manager.
3. Thêm detection model mới.
4. Upload file và smoke-test trước khi activate.

Import thành công chỉ chứng minh file được app chấp nhận. Cần chạy inference để xác nhận ONNX tương thích với runtime hiện tại.

## 11. Checklist nghiệm thu

- Notebook chạy từ đầu trên một Colab GPU runtime mới.
- Dataset ZIP được giải nén và validate.
- API token sai hoặc thiếu trả `401`.
- Submit hợp lệ trả `202` trong dưới hai giây.
- Submit job thứ hai trả `409`.
- Health và job status vẫn phản hồi khi GPU đang train.
- Job chuyển `queued → running → succeeded` hoặc `failed`.
- Epoch hiện tại được cập nhật.
- UI test connection hiển thị đúng GPU và active job.
- UI không lưu token vào localStorage hoặc template.
- UI tự dừng polling khi job `succeeded` hoặc `failed`.
- Reload trang không làm mất local training history.
- Đồng bộ cùng `remote_job_id` không tạo duplicate row.
- Mất tunnel chỉ chuyển connection thành `unreachable`, không đổi remote status thành `failed`.
- Download artifact yêu cầu bearer token và không nhận path từ client.
- Model import từ Colab được giữ inactive cho tới khi người dùng activate.
- `best.pt`, `best.onnx`, `manifest.json` tồn tại trên Drive.
- ONNX được import lại ToolIbV2.
- Inference smoke test chạy được.

## 12. Lỗi thường gặp

### Dataset archive not found

Kiểm tra chính xác:

```text
/content/drive/MyDrive/ToolIb_PoC/dataset.zip
```

Hoặc sửa biến `DRIVE_ARCHIVE` trong cell cấu hình notebook.

### data.yaml không tìm thấy

Mở ZIP và xác nhận có `data.yaml` hoặc `data.yml`.

### Train split contains no images

Kiểm tra đường dẫn `path` và `train` trong YAML có đúng tương đối với vị trí YAML sau khi giải nén.

### Ultralytics tìm nhầm `/content/images/train` hoặc `/content/images/val`

ToolIbV2 export `path: .`, trong khi một số phiên bản Ultralytics có thể resolve dấu `.` từ `/content` thay vì từ thư mục chứa YAML. Notebook hiện tại tạo `/content/toolib_poc/runtime_data.yaml` với `path` tuyệt đối trước khi train.

Nếu đang dùng bản notebook cũ đã upload, chạy cell vá nóng sau cell dataset và trước khi submit job mới:

```python
from pathlib import Path
import yaml

source_yaml = Path("/content/toolib_poc/dataset/exported_dataset/data.yaml")
with source_yaml.open("r", encoding="utf-8") as stream:
    runtime_config = yaml.safe_load(stream) or {}

configured_root = Path(str(runtime_config.get("path", ".")))
if not configured_root.is_absolute():
    configured_root = (source_yaml.parent / configured_root).resolve()

runtime_config["path"] = str(configured_root)
DATASET_YAML = Path("/content/toolib_poc/runtime_data.yaml")
with DATASET_YAML.open("w", encoding="utf-8") as stream:
    yaml.safe_dump(runtime_config, stream, sort_keys=False, allow_unicode=True)

print(DATASET_YAML.read_text(encoding="utf-8"))
```

Output phải chứa một path tuyệt đối tương tự:

```yaml
path: /content/toolib_poc/dataset/exported_dataset
```

### CUDA out of memory

Thử:

- `batch: 2` hoặc `batch: 1`.
- `imgsz: 320`.
- `yolo11n.pt`.

Job phải chuyển sang `failed`; API không được chết.

### Cloudflare URL không xuất hiện

- Chạy lại cell server/tunnel sau khi xác nhận local `/health` hoạt động.
- Kiểm tra output của `cloudflared`.
- URL Quick Tunnel có thể thay đổi mỗi lần chạy.

### UI báo lỗi CORS hoặc `Failed to fetch`

- Xác nhận đang dùng notebook Phase 2 hiện tại và đã chạy lại cell tạo FastAPI app.
- Xác nhận ToolIbV2 đang mở đúng origin `localhost:5000` hoặc `127.0.0.1:5000`.
- Không mở file HTML trực tiếp bằng `file://`.
- Xác nhận Quick Tunnel URL mới nhất vẫn trả `/health`.
- Nếu Flask chạy ở port khác, thêm đúng origin đó vào `allow_origins` trong notebook rồi chạy lại cell app và server.

### `Text file busy: /content/cloudflared`

Runtime cũ vẫn còn process `cloudflared` sử dụng executable. Notebook hiện tại sẽ kiểm tra và tái sử dụng binary hợp lệ thay vì ghi đè nó.

Nếu đang dùng bản notebook cũ đã upload trước khi có fix, chạy một cell tạm:

```python
import subprocess
import time

subprocess.run(["pkill", "-x", "cloudflared"], check=False)
time.sleep(2)
```

Sau đó chạy lại cell cài dependency. Nếu runtime đang ở trạng thái không ổn định hoặc vẫn còn server/thread cũ, chọn `Runtime → Disconnect and delete runtime`, kết nối lại GPU và chạy notebook từ đầu. Artifact đã copy lên Drive không bị xóa.

### Colab runtime bị dừng

Job trong memory sẽ mất. Artifact đã copy xong trên Drive vẫn còn. PoC không cam kết resume training.

## 13. Cleanup

Khi test xong:

1. Dừng `cloudflared`.
2. Đặt `UVICORN_SERVER.should_exit = True`.
3. Shutdown executor.
4. Disconnect và delete Colab runtime.

Nếu cần xóa artifact, chỉ xóa thư mục:

```text
MyDrive/ToolIb_PoC
```

Không dùng script cleanup với path nhận từ request API.

## 14. Phase 5 - nhiều Colab worker và hàng đợi tự động

Phase 5 giữ một ranh giới thủ công bắt buộc của Colab: người dùng phải mở
runtime và cấp quyền Google Drive. Sau khi worker được đăng ký, ToolIbV2 tự
tạo snapshot, upload, submit, theo dõi, tải ONNX, import model ở trạng thái
inactive và chạy job tiếp theo.

### 14.1 Chuẩn bị control plane

Tạo một Fernet key duy nhất cho môi trường. Không đổi key khi database còn
chứa worker, vì token cũ sẽ không giải mã được.

```powershell
$env:TOOLIB_WORKER_CREDENTIAL_KEY = & .\.venv\Scripts\python.exe -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Production phải lấy giá trị này từ secret manager. Không commit key vào Git.
Đặt thêm `TOOLIB_REQUIRE_EXTERNAL_CREDENTIAL_KEY=1` ở production để app fail
closed thay vì tự tạo local key khi secret bị thiếu.

Áp dụng migration cộng thêm và kiểm tra schema:

```powershell
.\.venv\Scripts\python.exe scripts\migrate_phase5_control_plane.py
.\.venv\Scripts\python.exe scripts\migrate_phase5_control_plane.py --check
```

Chạy `run.ps1` hoặc `run.bat`. Script sẽ chạy Flask và một scheduler process
riêng. Nếu cần xem log scheduler trực tiếp, chạy hai cửa sổ:

```powershell
.\.venv\Scripts\python.exe app.py
.\run_training_scheduler.ps1
```

Chỉ chạy một scheduler cho một database trong Phase 5. SQLite phù hợp test
local; production nên dùng PostgreSQL qua `YOLO_LABELING_DB_URI`.
Không public trực tiếp Flask hiện tại ra Internet. Trước production phải đặt
toàn bộ UI/API sau authenticated reverse proxy hoặc bổ sung login/RBAC ở cấp
ứng dụng.

### 14.2 Đăng ký nhiều Colab

Với mỗi Google account:

1. Mở một Colab notebook Phase 5.
2. Chọn GPU runtime, tạo một bearer token riêng và lưu vào
   `TOOLIB_COLAB_API_TOKEN`.
3. Chạy notebook đến khi có `Temporary public API`.
4. Tại `/colab-manager`, paste URL và token vào phần Colab API hiện tại.
5. Nhập tên phân biệt, ví dụ `colab-account-1-t4`.
6. Bấm `Đăng ký API hiện tại`.
7. Lặp lại bằng account/runtime khác.

Mỗi worker online có capacity mặc định bằng 1. Hai worker có thể nhận hai task
song song; task thứ ba giữ trạng thái `queued` cho đến khi có capacity.

### 14.3 Queue batch

1. Chọn model, epochs, batch size, imgsz và split dataset.
2. Trong `Production training control plane`, chọn một hoặc nhiều ToolIb
   project.
3. Chọn priority và max attempts.
4. Bấm `Queue selected projects`.
5. Theo dõi worker, batch, task, attempt và event ngay trên cùng màn hình.

Model ONNX hoàn tất được import với `is_active=false` và
`activation_ready=false`. Người dùng phải kiểm tra chất lượng trước khi kích
hoạt.

### 14.4 Mất kết nối và reconnect

- Nếu chỉ tunnel đổi URL nhưng Colab runtime/job vẫn còn: paste URL/token mới,
  tìm đúng worker cũ và bấm `Use current API`. Scheduler tiếp tục poll cùng
  `remote_job_id`; không submit job thứ hai.
- Nếu Colab runtime đã bị xóa: remote in-memory job không còn. Sau reconnect,
  worker trả `404`; task chuyển qua retry theo policy và dùng lại snapshot đã
  lưu ở control plane.
- Không bấm tạo worker mới để thay cho worker đang có task `worker_lost`, vì
  task được gắn với stable worker ID.

### 14.5 Acceptance test nhiều worker

1. Đăng ký hai worker và xác nhận `2/2 online`.
2. Queue ba project nhỏ, mỗi project 1 epoch.
3. Xác nhận hai task có attempt `running` trên hai worker khác nhau.
4. Xác nhận task thứ ba vẫn `queued`.
5. Sau khi một task xong, xác nhận task thứ ba tự chạy mà không bấm Dispatch.
6. Xác nhận cả ba model được import nhưng chưa active.
7. Trong một lần test riêng, dừng tunnel khi job đang chạy, xác nhận
   `worker_lost`, khôi phục URL bằng `Use current API` và xác nhận không có
   remote job trùng.

### 14.6 Rollback

Trước deployment, backup database và artifact root. Nếu phải rollback code,
checkout commit Phase 4 rồi chạy lại app. Không xóa năm bảng Phase 5 trong
rollback thông thường; giữ chúng để bảo toàn queue/audit history:

```text
training_workers
training_batches
training_queue_tasks
training_job_attempts
training_job_events
```

Chỉ drop các bảng này bằng migration phá hủy riêng sau khi đã export/backup dữ
liệu và chắc chắn không quay lại Phase 5.
