"""学生成绩管理系统 —— 应用工厂。

R1 交付物：可运行的 Flask 应用、6 张表的 ORM 定义、Alembic 迁移、``init-db`` / ``seed`` 命令。
架构参考 Flask 官方教程（Flaskr）的应用工厂与测试夹具写法，业务代码全部自写。
"""

from __future__ import annotations

import os
import secrets
from pathlib import Path

import click
from flask import Flask, current_app, render_template
from flask.cli import with_appcontext
from flask_migrate import upgrade as alembic_upgrade
from sqlalchemy import func, inspect

from .extensions import csrf, db, migrate

__version__ = "0.1.0"

#: 默认数据库文件名（落在 instance/ 下，不入版本控制）
DEFAULT_DB_FILENAME = "gradeapp.sqlite"


def create_app(test_config: dict | None = None) -> Flask:
    """应用工厂。测试通过传入 ``test_config`` 拿到互相隔离的临时数据库。"""
    app = Flask(__name__, instance_relative_config=True)

    app.config.from_mapping(
        # 不在代码里硬编码密钥：开发用 .flaskenv，生产用环境变量
        SECRET_KEY=os.environ.get("SECRET_KEY"),
        SQLALCHEMY_DATABASE_URI="sqlite:///"
        + (Path(app.instance_path) / DEFAULT_DB_FILENAME).as_posix(),
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        SQLALCHEMY_ENGINE_OPTIONS={"pool_pre_ping": True},
    )

    # 本地覆盖（instance/config.py，不入版本控制）
    app.config.from_pyfile("config.py", silent=True)
    # FLASK_* 环境变量覆盖
    app.config.from_prefixed_env()

    if test_config is not None:
        app.config.from_mapping(test_config)

    if not app.config.get("SECRET_KEY"):
        app.config["SECRET_KEY"] = secrets.token_hex(32)
        app.logger.warning(
            "未配置 SECRET_KEY，已生成随机临时密钥（重启后会话失效）；"
            "请通过环境变量或 instance/config.py 配置。"
        )

    Path(app.instance_path).mkdir(parents=True, exist_ok=True)

    db.init_app(app)
    migrate.init_app(app, db)
    csrf.init_app(app)

    from . import models  # noqa: F401  —— 导入模型，注册到 db.metadata 供 Alembic 使用

    _register_views(app)
    _register_commands(app)

    return app


# --------------------------------------------------------------------------- #
# 视图（R1 只有首页；R2 起由各蓝图接管）
# --------------------------------------------------------------------------- #
def _register_views(app: Flask) -> None:
    from .models import MODELS

    @app.route("/")
    def index():
        """首页：证明系统已启动，并列出 6 张表的建表与数据情况。"""
        existing = set(inspect(db.engine).get_table_names())
        tables = []
        for model in MODELS:
            name = model.__tablename__
            built = name in existing
            rows = db.session.scalar(db.select(func.count()).select_from(model)) if built else None
            tables.append({"name": name, "built": built, "rows": rows})

        return render_template(
            "index.html",
            version=__version__,
            tables=tables,
            db_path=db.engine.url.database,
        )


# --------------------------------------------------------------------------- #
# CLI 命令
# --------------------------------------------------------------------------- #
def _migrations_dir() -> Path:
    """迁移脚本目录：项目根（gradeapp 的上一级）/migrations。"""
    return Path(current_app.root_path).parent / "migrations"


def _sqlite_file_path() -> Path:
    uri = current_app.config["SQLALCHEMY_DATABASE_URI"]
    if not uri.startswith("sqlite:///"):
        raise click.ClickException(f"init-db 只支持 SQLite，当前为：{uri}")
    return Path(uri.replace("sqlite:///", "", 1))


@click.command("init-db")
@click.option("--force", is_flag=True, help="先删除现有数据库文件再重建（会清空数据）")
@with_appcontext
def init_db_command(force: bool) -> None:
    """应用 Alembic 迁移创建数据库表（等价于 flask db upgrade）。"""
    db_file = _sqlite_file_path()
    directory = _migrations_dir()

    if not (directory / "env.py").is_file():
        raise click.ClickException(f"未找到迁移目录 {directory}，请先执行 flask db init。")

    if force:
        db.session.remove()
        db.engine.dispose()
        if db_file.exists():
            db_file.unlink()
            click.echo(f"已删除旧数据库：{db_file}")

    db_file.parent.mkdir(parents=True, exist_ok=True)
    alembic_upgrade(directory=str(directory))
    click.echo(f"数据库已就绪：{db_file}")


@click.command("seed")
@with_appcontext
def seed_command() -> None:
    """写入演示数据：admin / teacher / student 各一个 + 一门课程（可重复执行）。"""
    stats = _seed_sample_data()
    click.echo(
        "种子数据完成："
        f"新增用户 {stats['user']}、学生 {stats['student']}、"
        f"教师 {stats['teacher']}、课程 {stats['course']}（已存在的记录跳过）"
    )


def _seed_sample_data() -> dict[str, int]:
    """幂等的种子数据写入。账号口令仅用于教学演示。"""
    from .models import Course, Student, Teacher, User

    created = {"user": 0, "student": 0, "teacher": 0, "course": 0}

    def get_or_create_user(username: str, role: str, real_name: str, password: str) -> User:
        user = db.session.scalar(db.select(User).filter_by(username=username))
        if user is None:
            user = User(username=username, role=role, real_name=real_name)
            user.set_password(password)
            db.session.add(user)
            db.session.flush()
            created["user"] += 1
        return user

    get_or_create_user("admin", "admin", "系统管理员", "admin123")
    teacher_user = get_or_create_user("teacher", "teacher", "张伟", "teacher123")
    student_user = get_or_create_user("student", "student", "李小明", "student123")

    teacher = teacher_user.teacher
    if teacher is None:
        teacher = Teacher(
            user_id=teacher_user.id,
            tno="T2001",
            name="张伟",
            title="副教授",
            department="计算机学院",
        )
        db.session.add(teacher)
        db.session.flush()
        created["teacher"] += 1

    student = student_user.student
    if student is None:
        student = Student(
            user_id=student_user.id,
            sno="2025001",
            name="李小明",
            gender="男",
            class_name="计算机2501",
            enroll_year=2025,
        )
        db.session.add(student)
        db.session.flush()
        created["student"] += 1

    course = db.session.scalar(db.select(Course).filter_by(code="CS101"))
    if course is None:
        db.session.add(
            Course(
                code="CS101",
                name="程序设计基础",
                credit=3.0,
                hours=48,
                teacher_id=teacher.id,
                semester="2025-2026-1",
                capacity=60,
            )
        )
        created["course"] += 1

    db.session.commit()
    return created


def _register_commands(app: Flask) -> None:
    app.cli.add_command(init_db_command)
    app.cli.add_command(seed_command)
