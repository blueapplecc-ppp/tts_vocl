#!/bin/bash
# TTS火山版 - 安全启动脚本
# 作者: 蘑菇🍄
# 说明: 使用Gunicorn生产级WSGI服务器启动应用

set -e  # 遇到错误立即退出

# 配置变量
PROJECT_DIR="/data/b2v/tts_vocl"
VENV_DIR="${PROJECT_DIR}/.venv"
LOG_DIR="${PROJECT_DIR}/run"
PID_FILE="${LOG_DIR}/gunicorn.pid"
LOG_FILE="${LOG_DIR}/gunicorn.log"

# 应用配置
HOST="0.0.0.0"
PORT="8082"
WORKERS="4"                    # 4个worker进程（匹配CPU核心+容错）
TIMEOUT="240"                  # 4分钟超时（防止worker卡死）
MAX_REQUESTS="1000"           # 每个worker处理1000个请求后重启（防止内存泄漏）
MAX_REQUESTS_JITTER="50"      # 重启时间随机抖动±50（避免同时重启）

# 颜色定义
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# 检查并清理现有进程
echo -e "${YELLOW}🔍 检查现有gunicorn进程...${NC}"
EXISTING_PIDS=$(ps aux | grep "[g]unicorn.*8082.*app:create_app" | awk '{print $2}' | tr '\n' ' ')
if [ -n "$EXISTING_PIDS" ]; then
    echo -e "${YELLOW}⚠️  发现现有gunicorn进程: $EXISTING_PIDS${NC}"
    echo -e "${YELLOW}正在清理现有进程...${NC}"
    echo "$EXISTING_PIDS" | xargs kill -9 2>/dev/null || true
    sleep 2
    echo -e "${GREEN}✅ 现有进程已清理${NC}"
fi

# 检查PID文件
if [ -f "$PID_FILE" ]; then
    echo -e "${YELLOW}⚠️  发现残留PID文件，正在清理...${NC}"
    rm -f "$PID_FILE"
fi

# 创建日志目录
mkdir -p "$LOG_DIR"

# 检查虚拟环境
if [ ! -d "$VENV_DIR" ]; then
    echo -e "${RED}❌ 虚拟环境不存在: $VENV_DIR${NC}"
    echo -e "${YELLOW}请先创建虚拟环境:${NC}"
    echo -e "  python3 -m venv .venv"
    echo -e "  source .venv/bin/activate"
    echo -e "  pip install -r requirements.txt"
    exit 1
fi

# 激活虚拟环境
source "$VENV_DIR/bin/activate"

# 检查依赖
if ! python -c "import gunicorn" 2>/dev/null; then
    echo -e "${RED}❌ gunicorn未安装${NC}"
    echo -e "${YELLOW}请先安装依赖: pip install -r requirements.txt${NC}"
    exit 1
fi

# 检查配置文件（外层父目录）
PARENT_DIR=$(dirname "$PROJECT_DIR")
if [ ! -f "$PARENT_DIR/db_config.json" ] && [ ! -f "$PARENT_DIR/db_config.ini" ]; then
    echo -e "${YELLOW}⚠️  警告: 未找到外层配置文件 (db_config.json 或 db_config.ini)${NC}"
    echo -e "${YELLOW}请确保在父目录配置完成: $PARENT_DIR${NC}"
fi

# 启动Gunicorn
echo -e "${GREEN}🚀 启动TTS火山版服务...${NC}"
echo -e "   监听地址: ${GREEN}${HOST}:${PORT}${NC}"
echo -e "   Worker数: ${GREEN}${WORKERS}${NC}"
echo -e "   日志文件: ${GREEN}${LOG_FILE}${NC}"
echo -e "   PID文件:  ${GREEN}${PID_FILE}${NC}"

cd "$PROJECT_DIR"

gunicorn \
    -w "$WORKERS" \
    -b "${HOST}:${PORT}" \
    --timeout "$TIMEOUT" \
    --max-requests "$MAX_REQUESTS" \
    --max-requests-jitter "$MAX_REQUESTS_JITTER" \
    --pid "$PID_FILE" \
    --access-logfile "$LOG_FILE" \
    --error-logfile "$LOG_FILE" \
    --capture-output \
    --enable-stdio-inheritance \
    --log-level info \
    "app:create_app()" \
    >> "$LOG_FILE" 2>&1 &

# 等待启动
sleep 2

# 验证启动状态
if [ -f "$PID_FILE" ]; then
    PID=$(cat "$PID_FILE")
    if ps -p "$PID" > /dev/null 2>&1; then
        echo -e "${GREEN}✅ 服务启动成功!${NC}"
        echo -e "   PID: ${GREEN}$PID${NC}"
        echo -e "   访问地址: ${GREEN}http://localhost:${PORT}${NC}"
        echo -e ""
        echo -e "📝 查看日志: tail -f $LOG_FILE"
        echo -e "🛑 停止服务: ./stop.sh"
        echo -e "🔄 重启服务: ./restart.sh"
        echo -e "💊 健康检查: ./health.sh"
    else
        echo -e "${RED}❌ 服务启动失败，请检查日志:${NC}"
        echo -e "   tail -100 $LOG_FILE"
        exit 1
    fi
else
    echo -e "${RED}❌ 未找到PID文件，启动可能失败${NC}"
    echo -e "   tail -100 $LOG_FILE"
    exit 1
fi

