#!/usr/bin/env python3
"""
TTS火山版 - 开发环境启动脚本

此脚本仅用于开发环境，提供Flask内置服务器启动。
生产环境请使用: ./start.sh

作者: 蘑菇🍄
"""

from app import create_app

app = create_app()

if __name__ == "__main__":
    print("🚀 启动TTS火山版开发服务器...")
    print("⚠️  注意：此脚本仅用于开发环境")
    print("📝 生产环境请使用: ./start.sh")
    print("🌐 访问地址: http://localhost:8082")
    app.run(host="0.0.0.0", port=8082, debug=True, use_reloader=False)
