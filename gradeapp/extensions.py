"""扩展单例。

所有 Flask 扩展在这里实例化、在应用工厂里 ``init_app()``，
避免循环导入（蓝图 / 模型只依赖本模块，不依赖 ``create_app``）。
"""

from __future__ import annotations

from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from flask_wtf import CSRFProtect

# ORM：6 张表的模型定义在 models.py
db = SQLAlchemy()

# 数据库迁移（Alembic）。compare_type 让字段类型变更也能被 autogenerate 发现
migrate = Migrate(compare_type=True)

# 全局 CSRF 防护：所有非 GET 请求都校验 token（表单统一走 Flask-WTF）
csrf = CSRFProtect()

__all__ = ["db", "migrate", "csrf"]
