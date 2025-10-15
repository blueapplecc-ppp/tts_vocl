#!/bin/bash
# TTS火山版 - 健康检查脚本
# 作者: 蘑菇🍄
# 说明: 检查服务运行状态

set -e

# 配置变量
PROJECT_DIR="/data/b2v/tts_vocl"
LOG_DIR="${PROJECT_DIR}/run"
PID_FILE="${LOG_DIR}/gunicorn.pid"
PORT="8082"

# 颜色定义
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${GREEN}💊 TTS火山版健康检查${NC}"
echo "=================================="

# 检查PID文件
if [ -f "$PID_FILE" ]; then
    PID=$(cat "$PID_FILE")
    echo -e "PID文件: ${GREEN}存在${NC} ($PID)"
    
    # 检查进程是否存在
    if ps -p "$PID" > /dev/null 2>&1; then
        echo -e "主进程: ${GREEN}运行中${NC} ($PID)"
    else
        echo -e "主进程: ${RED}不存在${NC}"
    fi
else
    echo -e "PID文件: ${RED}不存在${NC}"
fi

# 检查端口监听
echo -e "\n端口监听检查:"
LISTENING_PROCESSES=$(ss -tlnp | grep ":$PORT " | wc -l)
if [ "$LISTENING_PROCESSES" -gt 0 ]; then
    echo -e "端口 $PORT: ${GREEN}正在监听${NC}"
    ss -tlnp | grep ":$PORT "
else
    echo -e "端口 $PORT: ${RED}未监听${NC}"
fi

# 检查worker进程
echo -e "\nWorker进程检查:"
WORKER_COUNT=$(ps aux | grep "[g]unicorn.*8082.*app:create_app" | wc -l)
if [ "$WORKER_COUNT" -gt 0 ]; then
    echo -e "Worker进程: ${GREEN}$WORKER_COUNT 个${NC}"
    ps aux | grep "[g]unicorn.*8082.*app:create_app" | head -5
else
    echo -e "Worker进程: ${RED}0 个${NC}"
fi

# HTTP健康检查
echo -e "\nHTTP健康检查:"
if curl -s -f "http://localhost:$PORT" > /dev/null 2>&1; then
    echo -e "HTTP响应: ${GREEN}正常${NC}"
else
    echo -e "HTTP响应: ${RED}异常${NC}"
fi

# 检查日志文件
echo -e "\n日志文件检查:"
if [ -f "${LOG_DIR}/gunicorn.log" ]; then
    LOG_SIZE=$(du -h "${LOG_DIR}/gunicorn.log" | cut -f1)
    echo -e "日志文件: ${GREEN}存在${NC} (大小: $LOG_SIZE)"
    
    # 检查最近的错误
    RECENT_ERRORS=$(tail -100 "${LOG_DIR}/gunicorn.log" | grep -i "error\|exception\|failed" | wc -l)
    if [ "$RECENT_ERRORS" -gt 0 ]; then
        echo -e "最近错误: ${YELLOW}$RECENT_ERRORS 条${NC}"
    else
        echo -e "最近错误: ${GREEN}无${NC}"
    fi
else
    echo -e "日志文件: ${RED}不存在${NC}"
fi

echo -e "\n=================================="
echo -e "检查完成!"
