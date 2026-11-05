"""一键生产启动（R12）：python serve.py（HOST / PORT 可用环境变量或 .env 覆盖）。"""
import os

from waitress import serve

from wsgi import app

if __name__ == "__main__":
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "8000"))
    print(f"生产服务已启动：http://{host}:{port}/（Ctrl+C 停止）")
    serve(app, host=host, port=port, threads=8)
