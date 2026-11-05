"""生产部署入口（R12）。

开发环境（调试 / 自动重载）：
    flask run                      # .flaskenv 提供 FLASK_APP / FLASK_DEBUG

生产环境（waitress，Windows 友好的纯 Python WSGI 服务器）：
    waitress-serve --listen=0.0.0.0:8000 wsgi:app
    # 或者
    python serve.py                # HOST / PORT 可用环境变量覆盖

密钥与端口等配置从环境变量 / .env 注入，见 .env.example。
"""
from gradeapp import create_app

app = create_app()
