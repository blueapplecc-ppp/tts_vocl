# 无 sudo 首次部署指南（TTS_VOCL）

本指南面向“没有 sudo 权限”的部署场景。你只需要一个普通用户帐号、可访问的数据库与对象存储/火山 TTS 凭据，以及对外可访问的一个端口（示例 8081），即可完成首次上线与后续一键更新。

重要约定
- 当前工作目录即为项目根目录（与你本地/仓库结构完全一致）。
- 所有后端服务均运行在本项目根目录下创建的 Python 虚拟环境（`./.venv`）中。
- 数据库沿用部署环境上“已有的服务”（本项目不在虚拟环境内运行 DB）。

## 核心要点
- 运行方式：用户态 Gunicorn（不占用 80/443），监听 `0.0.0.0:8081` 或你的自定义端口。
- 配置位置：将 `db_config.json` 放在“当前项目根目录的父目录”（即 `../db_config.json`）。应用会自动从此处加载（见 `app/__init__.py` 的外部配置加载逻辑）。
- 目录结构（实际）：
  - 代码：`./`
  - 配置：`../db_config.json`（即“代码上一级目录”）
  - 虚拟环境：`./.venv`
  - 日志：`./logs`
  - 进程文件：`./run/tts_vocl.pid`

> 注意：程序会从 `app/` 目录的“上上级目录”查找 `db_config.json`。当你在 **项目根目录** 下运行应用时，`../` 正好是“上上级”，所以请将配置放到 `../db_config.json`。

---

## 一、前置准备
- 安装系统自带 Python（例如 `python3 --version`）与 `pip`/`venv` 模块（一般已内置）。
- 必须在“项目根目录 ./”执行本文脚本（`APP_DIR=\$(pwd)`）。
- 确认服务器防火墙/安全组开放你选择的端口（示例 8081）。
- 准备数据库（沿用部署环境已有服务）、OSS、火山 TTS 的可用凭据。

---

## 二、首次部署（一键脚本）
将以下内容保存为 `./deploy.sh`，修改“配置区”的变量后执行：

```
#!/usr/bin/env bash
set -euo pipefail

# ===== 配置区 =====
REPO_URL="https://github.com/your-org/tts_vocl.git"   # 替换为你的仓库
BRANCH="main"
APP_DIR="$(pwd)"   # 固定为当前项目根目录
PYTHON_BIN="python3"
BIND_HOST="0.0.0.0"
BIND_PORT="8081"
WORKERS="2"
THREADS="4"
TIMEOUT="180"
LOG_LEVEL="INFO"

# MySQL
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

echo "[2/8] 拉取代码"
if [ -d "$APP_DIR/.git" ]; then
  git -C "$APP_DIR" fetch --all
  git -C "$APP_DIR" checkout "$BRANCH"
  git -C "$APP_DIR" pull --ff-only origin "$BRANCH"
else
  git clone --branch "$BRANCH" --depth 1 "$REPO_URL" "$APP_DIR"
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
# 杀掉残留
if [ -f run/tts_vocl.pid ]; then
  OLD=\$(cat run/tts_vocl.pid || true)
  if [ -n "$OLD" ] && kill -0 "$OLD" 2>/dev/null; then
    echo "Killing old PID $OLD"
    kill "$OLD" || true
    sleep 1
  fi
fi
echo "Starting gunicorn on ${BIND_HOST}:${BIND_PORT} ..."
nohup .venv/bin/gunicorn -w ${WORKERS} -k gthread --threads ${THREADS} -b ${BIND_HOST}:${BIND_PORT} \
  --timeout ${TIMEOUT} --access-logfile - --error-logfile - run_refactored_app:app \
  > logs/server.out 2>&1 &
echo $! > run/tts_vocl.pid
echo "Started PID \$(cat run/tts_vocl.pid)"
SH
chmod +x "$APP_DIR/start.sh"

cat > "$APP_DIR/stop.sh" <<SH
#!/usr/bin/env bash
set -e
cd "$APP_DIR"
if [ -f run/tts_vocl.pid ]; then
  PID=\$(cat run/tts_vocl.pid)
  if [ -n "$PID" ] && kill -0 "$PID" 2>/dev/null; then
    echo "Stopping PID $PID"
    kill "$PID" || true
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
echo "如果是首次建库，请使用部署环境已有的数据库服务执行（无需 sudo）："
echo "mysql -h${MYSQL_HOST} -P${MYSQL_PORT} -u${MYSQL_USER} -p${MYSQL_PASSWORD} ${MYSQL_DB} < ${APP_DIR}/schema.sql"
echo "添加唯一索引（避免并发重复）："
echo "mysql -h${MYSQL_HOST} -P${MYSQL_PORT} -u${MYSQL_USER} -p${MYSQL_PASSWORD} -e \"USE ${MYSQL_DB}; ALTER TABLE tts_audios ADD UNIQUE KEY uq_tts_audios_oss_object_key (oss_object_key);\""

echo "[7/8] 启动服务"
bash "$APP_DIR/start.sh"

echo "[8/8] 健康检查"
bash "$APP_DIR/health.sh" || true

echo "部署完成：访问 http://<服务器IP>:${BIND_PORT}/"
```

---

## 三、目录与配置说明（相对于当前项目根目录 ./）
- 代码仓：`./`
- 配置：`../db_config.json`（必须在“代码仓上一级目录”；示例模板见 `docs/example_db_config.json`）
- 启动：`./start.sh`
- 停止：`./stop.sh`
- 重启：`./restart.sh`
- 健康：`./health.sh`
- 日志：`./logs/server.out`（Gunicorn 标准输出/错误），应用结构化日志同目录

> 安全建议：`db_config.json` 含敏感凭据，建议 `chmod 600 ../db_config.json`。

---

## 四、常见问题与排障
- 访问 404/502：确认进程是否启动、端口是否对外开放。
- TTS 401/握手失败：刷新 Access Token，更新 `../db_config.json` 后执行 `./restart.sh`。
- OSS 403/上传失败：检查 AK/SK 与 Bucket 权限、地域是否匹配。
- 数据库错误：确认 schema.sql 已导入、唯一索引已添加，数据库账号权限足够。
- 前端“网络错误”提示：
  - 看浏览器 Network 的 `/upload` 响应是否为 JSON；
  - 如果实时 SSE 中断，页面会自动切换轮询；
  - 页面底部“状态栏”会输出结构化事件对象，便于定位（含 text_id）。

---

## 五、更新与回滚
- 更新：重复执行 `./deploy.sh`（会 git pull、装包、重启）。
- 手动更新：`git pull && . .venv/bin/activate && pip install -r requirements.txt && ./restart.sh`
- 回滚：使用 Git tag/commit 切回老版本后 `./restart.sh`

---

## 六、对外暴露（可选）
无 sudo 环境无法占用 80/443。你可以：
- 直接对外开放 `:8081`；或
- 用上层网关/负载均衡转发 80/443 → 8081；或
- 临时 SSH 反向隧道/端口映射。

如需我生成 `deploy.sh` 到仓库 `docs/scripts/` 便于统一下发，请告知。
