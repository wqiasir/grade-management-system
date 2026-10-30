"""杭电计算机学院学生成绩管理系统 —— 应用工厂。"""
from __future__ import annotations

import os
import secrets
from datetime import timedelta
from pathlib import Path

import click
from flask import Flask, current_app, g, render_template
from flask.cli import with_appcontext
from flask_migrate import upgrade as alembic_upgrade
from sqlalchemy import func, inspect

from .extensions import csrf, db, migrate

__version__ = "0.1.0"

DEFAULT_DB_FILENAME = "gradeapp.sqlite"
SYSTEM_NAME = "杭电计算机学院学生成绩管理系统"
SCHOOL_NAME = "杭州电子科技大学计算机学院"


def create_app(test_config: dict | None = None) -> Flask:
    """应用工厂：支持测试配置隔离与动态实例目录初始化。"""
    app = Flask(__name__, instance_relative_config=True)

    app.config.from_mapping(
        SYSTEM_NAME=SYSTEM_NAME,
        SCHOOL_NAME=SCHOOL_NAME,
        SECRET_KEY=os.environ.get("SECRET_KEY"),
        SQLALCHEMY_DATABASE_URI=f"sqlite:///{(Path(app.instance_path) / DEFAULT_DB_FILENAME).as_posix()}",
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        SQLALCHEMY_ENGINE_OPTIONS={"pool_pre_ping": True},
    )

    app.config.from_pyfile("config.py", silent=True)
    app.config.from_prefixed_env()

    if test_config:
        app.config.from_mapping(test_config)

    if not app.config.get("SECRET_KEY"):
        app.config["SECRET_KEY"] = secrets.token_hex(32)
        app.logger.warning("未配置 SECRET_KEY，已生成随机临时密钥（重启后会话失效）。")

    Path(app.instance_path).mkdir(parents=True, exist_ok=True)

    app.config.setdefault("PERMANENT_SESSION_LIFETIME", timedelta(days=7))
    app.config.setdefault("SESSION_COOKIE_HTTPONLY", True)
    app.config.setdefault("SESSION_COOKIE_SAMESITE", "Lax")

    db.init_app(app)
    migrate.init_app(app, db)
    csrf.init_app(app)

    from . import models  # noqa: F401

    _register_blueprints(app)
    _register_views(app)
    _register_commands(app)
    _register_navigation(app)
    _register_branding(app)
    _register_error_handlers(app)

    return app


def _register_blueprints(app: Flask) -> None:
    from .admin import bp as admin_bp
    from .auth import bp as auth_bp
    from .report import bp as report_bp
    from .score import bp as score_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(score_bp)
    app.register_blueprint(report_bp)


def _register_views(app: Flask) -> None:
    from .dashboard import dashboard_context
    from .decorators import ROLE_LABELS, role_label
    from .models import MODELS

    @app.route("/")
    def index():
        existing = set(inspect(db.engine).get_table_names())
        tables = [
            {
                "name": (name := m.__tablename__),
                "built": (built := name in existing),
                "rows": db.session.scalar(db.select(func.count()).select_from(m)) if built else None,
            }
            for m in MODELS
        ]

        user = g.get("user")
        ctx = dashboard_context(user) if user else {}
        return render_template(
            "index.html",
            version=__version__,
            tables=tables,
            db_path=db.engine.url.database,
            role_labels=ROLE_LABELS,
            current_role_label=role_label(getattr(user, "role", None)),
            **ctx,
        )


def _register_navigation(app: Flask) -> None:
    from .menu import menu_for_user

    @app.context_processor
    def inject_nav() -> dict[str, object]:
        return {"nav_items": menu_for_user(g.get("user"))}


def _register_branding(app: Flask) -> None:
    @app.context_processor
    def inject_branding() -> dict[str, str]:
        return {"system_name": app.config["SYSTEM_NAME"], "school_name": app.config["SCHOOL_NAME"]}


def _register_error_handlers(app: Flask) -> None:
    from .decorators import role_label

    @app.errorhandler(403)
    def handle_forbidden(error):
        return render_template(
            "errors/403.html",
            required_roles=(),
            message=None,
            current_role_label=role_label(getattr(g.get("user"), "role", None)),
        ), 403

    @app.errorhandler(404)
    def handle_not_found(error):
        return render_template("errors/404.html"), 404


def _migrations_dir() -> Path:
    return Path(current_app.root_path).parent / "migrations"


def _sqlite_file_path() -> Path:
    uri = current_app.config["SQLALCHEMY_DATABASE_URI"]
    if not uri.startswith("sqlite:///"):
        raise click.ClickException(f"init-db 只支持 SQLite，当前为：{uri}")
    return Path(uri.replace("sqlite:///", "", 1))


@click.command("init-db")
@click.option("--force", is_flag=True, help="先删除现有数据库文件再重建")
@with_appcontext
def init_db_command(force: bool) -> None:
    db_file, directory = _sqlite_file_path(), _migrations_dir()

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
    stats = _seed_sample_data()
    click.echo(
        f"种子数据完成：新增用户 {stats['user']}、学生 {stats['student']}、"
        f"教师 {stats['teacher']}、课程 {stats['course']}（已存在的记录跳过）"
    )


def _seed_sample_data() -> dict[str, int]:
    from .models import Course, Student, Teacher, User

    created = {"user": 0, "student": 0, "teacher": 0, "course": 0}

    def get_or_create_user(username: str, role: str, real_name: str, password: str) -> User:
        user = db.session.scalar(db.select(User).filter_by(username=username))
        if not user:
            user = User(username=username, role=role, real_name=real_name)
            user.set_password(password)
            db.session.add(user)
            db.session.flush()
            created["user"] += 1
        return user

    get_or_create_user("admin", "admin", "系统管理员", "admin123")
    teacher_user = get_or_create_user("teacher", "teacher", "张伟", "teacher123")
    student_user = get_or_create_user("student", "student", "李小明", "student123")

    if not teacher_user.teacher:
        teacher = Teacher(user_id=teacher_user.id, tno="T2001", name="张伟", title="副教授", department="计算机学院")
        db.session.add(teacher)
        db.session.flush()
        created["teacher"] += 1

    if not student_user.student:
        student = Student(user_id=student_user.id, sno="2025001", name="李小明", gender="男", class_name="计算机2501", enroll_year=2025)
        db.session.add(student)
        db.session.flush()
        created["student"] += 1

    if not db.session.scalar(db.select(Course).filter_by(code="CS101")):
        db.session.add(Course(
            code="CS101", name="程序设计基础", credit=3.0, hours=48,
            teacher_id=teacher_user.teacher.id, semester="2025-2026-1", capacity=60
        ))
        created["course"] += 1

    db.session.commit()
    return created


def _register_commands(app: Flask) -> None:
    app.cli.add_command(init_db_command)
    app.cli.add_command(seed_command)