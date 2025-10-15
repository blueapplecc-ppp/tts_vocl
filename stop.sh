#!/bin/bash
# TTS火山版 - 安全停止脚本
# 作者: 蘑菇🍄
# 说明: 优雅地停止Gunicorn服务

set -e

# 配置变量
PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG_DIR="${PROJECT_DIR}/run"
PID_FILE="${LOG_DIR}/gunicorn.pid"

# 颜色定义
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

# 检查PID文件
if [ ! -f "$PID_FILE" ]; then
    echo -e "${YELLOW}⚠️  未找到PID文件，服务可能未运行${NC}"
    
    # 尝试查找进程（精确匹配）
    PIDS=$(ps aux | grep "[g]unicorn.*8082.*app:create_app" | awk '{print $2}' | tr '\n' ' ')
    if [ -n "$PIDS" ]; then
        echo -e "${YELLOW}⚠️  发现运行中的gunicorn进程: $PIDS${NC}"
        echo -e "${YELLOW}正在优雅停止这些进程...${NC}"
        # 先尝试优雅停止
        echo "$PIDS" | xargs kill -TERM 2>/dev/null || true
        sleep 3
        # 检查是否还在运行
        REMAINING_PIDS=$(ps aux | grep "[g]unicorn.*8082.*app:create_app" | awk '{print $2}' | tr '\n' ' ')
        if [ -n "$REMAINING_PIDS" ]; then
            echo -e "${YELLOW}强制终止残留进程: $REMAINING_PIDS${NC}"
            echo "$REMAINING_PIDS" | xargs kill -9 2>/dev/null || true
        fi
        echo -e "${GREEN}✅ 进程已终止${NC}"
    else
        echo -e "${GREEN}✅ 确认服务未运行${NC}"
    fi
    exit 0
fi

# 读取PID
PID=$(cat "$PID_FILE")

# 检查进程是否存在
if ! ps -p "$PID" > /dev/null 2>&1; then
    echo -e "${YELLOW}⚠️  PID $PID 对应的进程不存在${NC}"
    rm -f "$PID_FILE"
    echo -e "${GREEN}✅ 已清理残留PID文件${NC}"
    exit 0
fi

# 优雅停止（发送TERM信号）
echo -e "${GREEN}🛑 正在停止服务 (PID: $PID)...${NC}"
kill -TERM "$PID"

# 等待进程退出（最多30秒）
TIMEOUT=30
COUNT=0
while ps -p "$PID" > /dev/null 2>&1; do
    sleep 1
    COUNT=$((COUNT + 1))
    if [ $COUNT -eq $TIMEOUT ]; then
        echo -e "${YELLOW}⚠️  优雅停止超时，强制终止进程...${NC}"
        kill -KILL "$PID"
        sleep 1
        break
    fi
    echo -ne "   等待进程退出... ${COUNT}s/${TIMEOUT}s\r"
done

# 验证停止状态
if ps -p "$PID" > /dev/null 2>&1; then
    echo -e "${RED}❌ 进程无法停止 (PID: $PID)${NC}"
    exit 1
else
    rm -f "$PID_FILE"
    echo -e "${GREEN}✅ 服务已成功停止${NC}"
fi

# 清理worker进程（防止残留，精确匹配）
WORKER_PIDS=$(ps aux | grep "[g]unicorn.*8082.*app:create_app" | grep -v "$$" | awk '{print $2}')
if [ -n "$WORKER_PIDS" ]; then
    echo -e "${YELLOW}⚠️  发现残留worker进程，正在清理...${NC}"
    echo "$WORKER_PIDS" | xargs kill -9 2>/dev/null || true
    echo -e "${GREEN}✅ Worker进程已清理${NC}"
fi

