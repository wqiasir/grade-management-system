"""Flask 扩展初始化模块（避免循环导入）。"""
from __future__ import annotations

from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from flask_wtf import CSRFProtect

db = SQLAlchemy()
migrate = Migrate(compare_type=True)  # 允许 autogenerate 检测字段类型变更
csrf = CSRFProtect()                  # 全局 CSRF 防护

__all__ = ["db", "migrate", "csrf"]