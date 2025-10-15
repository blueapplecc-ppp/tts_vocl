#!/bin/bash
# TTS火山版 - 重启脚本
# 作者: 蘑菇🍄
# 说明: 优雅地重启Gunicorn服务

set -e

# 配置变量
PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"

# 颜色定义
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${GREEN}🔄 重启TTS火山版服务...${NC}"

# 进入项目目录
cd "$PROJECT_DIR"

# 停止服务
echo -e "${YELLOW}1. 停止现有服务...${NC}"
./stop.sh

# 等待服务完全停止
echo -e "${YELLOW}2. 等待服务完全停止...${NC}"
sleep 3

# 启动服务
echo -e "${YELLOW}3. 启动新服务...${NC}"
./start.sh

echo -e "${GREEN}✅ 服务重启完成!${NC}"
