#!/usr/bin/env bash
set -euo pipefail

# ===== 配置区（按需修改） =====
REPO_URL="https://github.com/your-org/tts_vocl.git"   # 替换为你的仓库地址（首次拉取时使用）
BRANCH="main"
APP_DIR="$(pwd)"     # 固定为当前项目根目录
PYTHON_BIN="python3"
BIND_HOST="0.0.0.0"
BIND_PORT="8081"
WORKERS="2"
THREADS="4"
TIMEOUT="180"
LOG_LEVEL="INFO"

# MySQL（沿用部署环境已存在的数据库服务）
MYSQL_HOST="127.0.0.1"
MYSQL_PORT="3306"
MYSQL_USER="tts_user"
MYSQL_PASSWORD="change-me"
MYSQL_DB="tts_vocl"

# OSS
OSS_ENDPOINT="https://oss-cn-shanghai.aliyuncs.com"
OSS_BUCKET="ai-books-audios"
OSS_AK="YOUR_OSS_AK"
OSS_SK="YOUR_OSS_SK"

# VOLC TTS
VOLC_APP_ID="YOUR_VOLC_APP_ID"
VOLC_ACCESS_TOKEN="YOUR_VOLC_ACCESS_TOKEN"
VOLC_SECRET_KEY="YOUR_VOLC_SECRET"
VOLC_API_BASE="https://open.volcengineapi.com"

AUTH_ENABLED="false"
# ===== 配置区结束 =====

echo "[1/8] 准备目录"
mkdir -p "$APP_DIR/logs" "$APP_DIR/run"

echo "[2/8] 拉取/更新代码（可选）"
if [ ! -d "$APP_DIR/.git" ]; then
  echo "当前目录非 git 仓库，如需从远端拉取请执行："
  echo "git clone --branch $BRANCH --depth 1 $REPO_URL $APP_DIR"
else
  git -C "$APP_DIR" fetch --all || true
  git -C "$APP_DIR" checkout "$BRANCH" || true
  git -C "$APP_DIR" pull --ff-only origin "$BRANCH" || true
fi

echo "[3/8] 创建虚拟环境并安装依赖"
cd "$APP_DIR"
$PYTHON_BIN -m venv .venv
. .venv/bin/activate
pip install --upgrade pip wheel
pip install -r requirements.txt

echo "[4/8] 写入配置 ../db_config.json"
cat > "../db_config.json" <<JSON
{
  "AUTH_ENABLED": ${AUTH_ENABLED},
  "MYSQL": {
    "HOST": "${MYSQL_HOST}",
    "PORT": ${MYSQL_PORT},
    "USER": "${MYSQL_USER}",
    "PASSWORD": "${MYSQL_PASSWORD}",
    "DB": "${MYSQL_DB}",
    "POOL_SIZE": 10,
    "POOL_TIMEOUT": 5,
    "POOL_RECYCLE": 1800
  },
  "OSS": {
    "ENDPOINT": "${OSS_ENDPOINT}",
    "BUCKET": "${OSS_BUCKET}",
    "ACCESS_KEY_ID": "${OSS_AK}",
    "ACCESS_KEY_SECRET": "${OSS_SK}"
  },
  "VOLC_TTS": {
    "APP_ID": "${VOLC_APP_ID}",
    "ACCESS_TOKEN": "${VOLC_ACCESS_TOKEN}",
    "SECRET_KEY": "${VOLC_SECRET_KEY}",
    "API_BASE": "${VOLC_API_BASE}"
  },
  "JWT": { "SECRET": "change-me", "EXPIRES_MINUTES": 120 }
}
JSON

echo "[5/8] 生成管理脚本（start/stop/restart/health）"
cat > "$APP_DIR/start.sh" <<SH
#!/usr/bin/env bash
set -e
cd "$APP_DIR"
. .venv/bin/activate
export LOG_LEVEL="${LOG_LEVEL}"
export LOG_LEVEL_TTS_CLIENT="INFO"
export LOG_LEVEL_TTS_SERVICE="INFO"
export LOG_LEVEL_PROTOCOLS="INFO"
if [ -f run/tts_vocl.pid ]; then
  OLD=\$(cat run/tts_vocl.pid || true)
  if [ -n "\$OLD" ] && kill -0 "\$OLD" 2>/dev/null; then
    echo "Killing old PID \$OLD"
    kill "\$OLD" || true
    sleep 1
  fi
fi
echo "Starting gunicorn on ${BIND_HOST}:${BIND_PORT} ..."
nohup .venv/bin/gunicorn -w ${WORKERS} -k gthread --threads ${THREADS} -b ${BIND_HOST}:${BIND_PORT} \
  --timeout ${TIMEOUT} --access-logfile - --error-logfile - run_refactored_app:app \
  > logs/server.out 2>&1 &
echo \$! > run/tts_vocl.pid
echo "Started PID \$(cat run/tts_vocl.pid)"
SH
chmod +x "$APP_DIR/start.sh"

cat > "$APP_DIR/stop.sh" <<SH
#!/usr/bin/env bash
set -e
cd "$APP_DIR"
if [ -f run/tts_vocl.pid ]; then
  PID=\$(cat run/tts_vocl.pid)
  if [ -n "\$PID" ] && kill -0 "\$PID" 2>/dev/null; then
    echo "Stopping PID \$PID"
    kill "\$PID" || true
    sleep 1
  fi
  rm -f run/tts_vocl.pid
else
  echo "No pidfile. Nothing to stop."
fi
SH
chmod +x "$APP_DIR/stop.sh"

cat > "$APP_DIR/restart.sh" <<SH
#!/usr/bin/env bash
set -e
"$APP_DIR/stop.sh" || true
"$APP_DIR/start.sh"
SH
chmod +x "$APP_DIR/restart.sh"

cat > "$APP_DIR/health.sh" <<'SH'
#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"
. .venv/bin/activate
python - <<'PY'
from app import create_app
app = create_app()
app.testing = True
c = app.test_client()
for path in ['/api/diagnose/oss','/api/diagnose/tts']:
    r = c.get(path)
    print(path, r.status_code, r.get_data(as_text=True)[:200])
PY
SH
chmod +x "$APP_DIR/health.sh"

echo "[6/8] 数据库初始化（如需要）"
echo "使用部署环境已有的数据库服务执行（无需 sudo）："
echo "mysql -h${MYSQL_HOST} -P${MYSQL_PORT} -u${MYSQL_USER} -p${MYSQL_PASSWORD} ${MYSQL_DB} < ${APP_DIR}/schema.sql"
echo "添加唯一索引（避免并发重复）："
echo "mysql -h${MYSQL_HOST} -P${MYSQL_PORT} -u${MYSQL_USER} -p${MYSQL_PASSWORD} -e \"USE ${MYSQL_DB}; ALTER TABLE tts_audios ADD UNIQUE KEY uq_tts_audios_oss_object_key (oss_object_key);\""

echo "[7/8] 启动服务"
bash "$APP_DIR/start.sh"

echo "[8/8] 健康检查"
bash "$APP_DIR/health.sh" || true

echo "部署完成：访问 http://<服务器IP>:${BIND_PORT}/"

