# Flask CLI 开发配置（由 python-dotenv 自动加载，仅在开发环境使用）
FLASK_APP=gradeapp
FLASK_DEBUG=1

# 密钥不再写在这里（R12 起）：复制 .env.example 为 .env 并设置 SECRET_KEY；
# 未配置时应用会自动生成随机临时密钥并告警（重启后会话失效）。
