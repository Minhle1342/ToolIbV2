# Huong dan UAT ToolIbV2 tren WSL2 va Docker Desktop

Tai lieu nay danh cho mot may UAT moi, da co WSL2 va Docker Desktop, can:

- clone ToolIbV2;
- tao PostgreSQL UAT moi;
- khoi tao schema va migration ledger;
- chay Flask HTTPS va training scheduler;
- kiem tra `/colab-manager` truoc khi dang ky Colab worker.

Mac dinh tai lieu tao database UAT trong. Khong dung quy trinh nay de ghi de
database production hoac tu dong copy du lieu that.

## 1. Runtime map

```text
Docker Desktop
└─ toolib_postgres: PostgreSQL 17, 127.0.0.1:54329

WSL2 Ubuntu
├─ Flask HTTPS: 0.0.0.0:5000
└─ training_scheduler.py

Windows browser
└─ https://localhost:5000
```

PostgreSQL chi bind vao `127.0.0.1`; khong mo port `54329` ra LAN.

## 2. Bat Docker Desktop WSL integration

Trong Docker Desktop:

1. Mo `Settings`.
2. Chon `Resources -> WSL Integration`.
3. Bat distro Ubuntu dang su dung.
4. Bam `Apply & Restart`.

Trong WSL:

```bash
docker version
docker compose version
docker run --rm hello-world
```

Dung lai neu mot trong ba lenh tren khong thanh cong.

## 3. Clone source va cai dependency

Nen dat repo trong filesystem WSL (`~/ToolIbV2`), khong dat duoi `/mnt/c`.

```bash
cd ~
git clone https://github.com/Minhle1342/ToolIbV2.git
cd ToolIbV2
git status
git log -1 --oneline
```

Cai system packages:

```bash
sudo apt update
sudo apt install -y \
  python3 \
  python3-venv \
  python3-pip \
  build-essential \
  libgl1 \
  libglib2.0-0 \
  curl \
  openssl
```

ToolIbV2 hien duoc verify tren Python 3.11. Neu `python3 --version` la 3.11:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Neu distro khong co Python 3.11, dung `uv` de tao dung runtime:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
source "$HOME/.local/bin/env"
uv python install 3.11
uv venv --python 3.11 .venv
source .venv/bin/activate
uv pip install -r requirements.txt
```

Xac minh:

```bash
python --version
python -c "import flask, sqlalchemy, psycopg, cv2; print('PYTHON READY')"
```

## 4. Tao secret UAT

Khong copy `.env.postgres.local` tu DEV. Moi may UAT phai co database password
va worker credential encryption key rieng.

```bash
cd ~/ToolIbV2
source .venv/bin/activate

mkdir -p "$HOME/toolib-uat-data/model_artifacts"
umask 077

DB_PASS="$(openssl rand -hex 32)"
WORKER_KEY="$(python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')"

cat > .env.postgres.local <<EOF
TOOLIB_POSTGRES_DB=toolib
TOOLIB_POSTGRES_USER=toolib
TOOLIB_POSTGRES_PASSWORD=$DB_PASS
TOOLIB_POSTGRES_PORT=54329
YOLO_LABELING_DB_URI=postgresql+psycopg://toolib:$DB_PASS@127.0.0.1:54329/toolib

TOOLIB_WORKER_CREDENTIAL_KEY=$WORKER_KEY
TOOLIB_REQUIRE_EXTERNAL_CREDENTIAL_KEY=true
TOOLIB_FINETUNE_ENABLED=true
TOOLIB_MODEL_ARTIFACT_ROOT=$HOME/toolib-uat-data/model_artifacts
EOF

chmod 600 .env.postgres.local
unset DB_PASS WORKER_KEY
```

`.env.postgres.local` da duoc `.gitignore`. Khong commit hoac gui file nay.

## 5. Tao PostgreSQL container

```bash
cd ~/ToolIbV2

docker compose \
  --env-file .env.postgres.local \
  -f compose.postgres.yml \
  up -d
```

Xac minh:

```bash
docker compose \
  --env-file .env.postgres.local \
  -f compose.postgres.yml \
  ps

docker inspect \
  --format '{{.State.Health.Status}}' \
  toolib_postgres
```

Ket qua health phai la `healthy`. Neu khong:

```bash
docker logs --tail 100 toolib_postgres
```

## 6. Load environment trong WSL

Moi terminal chay Flask, scheduler, migration hoac preflight deu phai load env:

```bash
cd ~/ToolIbV2
source .venv/bin/activate
set -a
source .env.postgres.local
set +a
```

Xac minh khong in password:

```bash
python -c "import os; print(os.environ['YOLO_LABELING_DB_URI'].split('@')[-1])"
```

Ket qua:

```text
127.0.0.1:54329/toolib
```

## 7. Khoi tao schema va migration ledger

Khoi tao cac table hien tai:

```bash
python -c "from app import create_app; create_app(); print('DATABASE SCHEMA READY')"
```

Chay migration theo thu tu:

```bash
python scripts/migrate_phase5_control_plane.py
python scripts/migrate_phase6_finetune.py
python scripts/migrate_phase7_resumable_training.py
python scripts/migrate_phase8_object_transport.py
python scripts/migrate_phase9_optimizer_contract.py
```

Kiem tra read-only:

```bash
python scripts/migrate_phase5_control_plane.py --check
python scripts/migrate_phase6_finetune.py --check
python scripts/migrate_phase7_resumable_training.py --check
python scripts/migrate_phase8_object_transport.py --check
python scripts/migrate_phase9_optimizer_contract.py --status
python scripts/training_preflight.py --database-uri "$YOLO_LABELING_DB_URI"
```

Preflight khong co worker URL co the bao `worker-health: SKIP`; database va code
checks van phai `PASS`.

Xem danh sach table:

```bash
docker exec toolib_postgres sh -lc \
  'PGPASSWORD="$POSTGRES_PASSWORD" psql \
  -U "$POSTGRES_USER" \
  -d "$POSTGRES_DB" \
  -c "\dt"'
```

Can thay toi thieu:

- `projects`, `images`, `ai_models`;
- `training_workers`, `training_batches`, `training_queue_tasks`;
- `fine_tune_parameter_sets`, `toolib_schema_migrations`.

## 8. Chay Flask HTTPS

Mo terminal WSL thu nhat:

```bash
cd ~/ToolIbV2
source .venv/bin/activate
set -a
source .env.postgres.local
set +a
python app.py
```

Lan dau app se tao `cert.pem` va `key.pem`. Mo tren Windows:

```text
https://localhost:5000
```

Self-signed certificate se tao browser warning. Voi UAT noi bo, chon tiep tuc
truy cap.

## 9. Chay training scheduler

Mo terminal WSL thu hai:

```bash
cd ~/ToolIbV2
source .venv/bin/activate
set -a
source .env.postgres.local
set +a
python training_scheduler.py
```

Flask va scheduler phai load cung `.env.postgres.local`. Log mong doi:

```text
Training scheduler started.
```

## 10. Smoke test UAT

Mo terminal WSL thu ba:

```bash
curl -k -I https://127.0.0.1:5000/

curl -ks \
  https://127.0.0.1:5000/api/training-control-plane/status \
  | python -m json.tool

curl -ks \
  https://127.0.0.1:5000/api/training-model-catalog \
  | python -m json.tool
```

Tren UI:

1. Mo `/colab-manager`.
2. Kiem tra banner `Tai nguyen huan luyen`.
3. Kiem tra YOLO11, YOLO12 va YOLO26.
4. Dang ky Colab URL, bearer token va ten worker.
5. Bam `Kiem tra ket noi`; worker phai chuyen sang online.

Sau khi co worker URL va token trong env:

```bash
export TOOLIB_COLAB_API_TOKEN='<worker-bearer-token>'

python scripts/training_preflight.py \
  --database-uri "$YOLO_LABELING_DB_URI" \
  --worker-url 'https://your-worker.trycloudflare.com' \
  --strict
```

Khong ghi bearer token truc tiep vao source hoac commit history.

## 11. Backup PostgreSQL UAT

```bash
mkdir -p "$HOME/toolib-uat-backups"

docker exec toolib_postgres sh -lc \
  'PGPASSWORD="$POSTGRES_PASSWORD" pg_dump \
  -U "$POSTGRES_USER" \
  -d "$POSTGRES_DB" \
  -Fc' \
  > "$HOME/toolib-uat-backups/toolib_$(date +%F_%H%M%S).dump"

ls -lh "$HOME/toolib-uat-backups"
```

`docker compose down` giu nguyen volume. Khong chay lenh sau tren UAT neu khong
chu dong xoa database:

```bash
docker compose -f compose.postgres.yml down -v
```

## 12. LAN access va gioi han hien tai

- Tu Windows host: dung `https://localhost:5000`.
- Tu may khac trong LAN: can WSL mirrored networking hoac Windows port proxy,
  va Windows Firewall inbound rule cho TCP `5000`.
- Khong mo port PostgreSQL `54329` ra LAN.
- `python app.py` la luong chay hien co va dung duoc cho controlled UAT. De chay
  lau dai sau reboot, can mot phase rieng tao `run_uat.sh` va `systemd` services
  cho Flask/scheduler voi `debug=False`.
- `run.ps1` va `scripts/setup_postgres.ps1` la Windows PowerShell; khong dung
  truc tiep trong WSL.

## 13. Ket qua can gui lai de kiem tra

```bash
git log -1 --oneline
docker compose --env-file .env.postgres.local -f compose.postgres.yml ps
docker inspect --format '{{.State.Health.Status}}' toolib_postgres
python scripts/migrate_phase9_optimizer_contract.py --status
python scripts/training_preflight.py --database-uri "$YOLO_LABELING_DB_URI"
```

Khong gui `.env.postgres.local`, database password, worker bearer token hoac
`TOOLIB_WORKER_CREDENTIAL_KEY`.
