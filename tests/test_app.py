"""R1 验证：应用骨架、6 张表、CLI 命令、数据库约束。

对应第 7 节 R1 的完成标准：至少 1 条 smoke test，且 pytest 全绿。
"""

from __future__ import annotations

import pytest
from flask import Flask
from flask.testing import FlaskCliRunner, FlaskClient
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError

from gradeapp import __version__, create_app
from gradeapp.extensions import db
from gradeapp.models import MODELS, Course, Enrollment, Score, Student, Teacher, User

EXPECTED_TABLES = {"user", "student", "teacher", "course", "enrollment", "score"}


# --------------------------------------------------------------------------- #
# 冒烟测试：应用能创建、首页能打开
# --------------------------------------------------------------------------- #
def test_create_app_returns_working_app(app: Flask) -> None:
    assert app.name == "gradeapp"
    assert app.config["TESTING"] is True
    assert create_app({"TESTING": True}).name == "gradeapp"


def test_index_page_reports_system_started(client: FlaskClient) -> None:
    """R1 演示要点：首页显示"系统已启动"，并列出 6 张表。"""
    response = client.get("/")
    assert response.status_code == 200

    html = response.get_data(as_text=True)
    assert "系统已启动" in html
    assert __version__ in html
    for table in EXPECTED_TABLES:
        assert table in html


# --------------------------------------------------------------------------- #
# 数据模型：6 张表与冻结的设计
# --------------------------------------------------------------------------- #
def test_models_declare_exactly_six_tables(app: Flask) -> None:
    assert {model.__tablename__ for model in MODELS} == EXPECTED_TABLES
    assert len(MODELS) == 6
    # conftest 已 create_all，实际库里也应存在这 6 张表
    assert EXPECTED_TABLES <= set(inspect(db.engine).get_table_names())


def test_expected_columns_exist(app: Flask) -> None:
    """字段与第 5 节表格逐条对齐。"""
    expected_columns = {
        "user": {"id", "username", "password_hash", "role", "real_name", "is_active", "created_at"},
        "student": {"id", "user_id", "sno", "name", "gender", "class_name", "enroll_year"},
        "teacher": {"id", "user_id", "tno", "name", "title", "department"},
        "course": {"id", "code", "name", "credit", "hours", "teacher_id", "semester", "capacity"},
        "enrollment": {"id", "student_id", "course_id", "enrolled_at"},
        "score": {"id", "enrollment_id", "exam_type", "score", "updated_by", "updated_at"},
    }
    inspector = inspect(db.engine)
    for table, expected in expected_columns.items():
        actual = {column["name"] for column in inspector.get_columns(table)}
        assert actual == expected, f"{table} 字段不符：{actual ^ expected}"


# --------------------------------------------------------------------------- #
# CLI：init-db 走 Alembic 迁移建表
# --------------------------------------------------------------------------- #
def test_init_db_command_builds_tables_from_migration(app: Flask, runner: FlaskCliRunner) -> None:
    db.drop_all()
    assert not (EXPECTED_TABLES <= set(inspect(db.engine).get_table_names()))

    result = runner.invoke(args=["init-db", "--force"])

    assert result.exit_code == 0, result.output
    tables = set(inspect(db.engine).get_table_names())
    assert EXPECTED_TABLES <= tables
    assert "alembic_version" in tables  # 证明表是迁移建的，不是 create_all


def test_migration_schema_matches_models(app: Flask, runner: FlaskCliRunner) -> None:
    """防止"模型改了但没生成迁移"的漂移：迁移建出的表结构应与模型一致。"""
    db.drop_all()
    runner.invoke(args=["init-db", "--force"])

    inspector = inspect(db.engine)
    for model in MODELS:
        table = model.__tablename__
        migrated = {column["name"] for column in inspector.get_columns(table)}
        declared = {column.name for column in model.__table__.columns}
        assert migrated == declared, f"{table} 迁移与模型不一致：{migrated ^ declared}"


# --------------------------------------------------------------------------- #
# CLI：seed 幂等
# --------------------------------------------------------------------------- #
def test_seed_command_creates_sample_data_idempotently(app: Flask, runner: FlaskCliRunner) -> None:
    result = runner.invoke(args=["seed"])
    assert result.exit_code == 0, result.output

    users = db.session.scalars(db.select(User)).all()
    assert {user.username for user in users} == {"admin", "teacher", "student"}
    assert {user.role for user in users} == {"admin", "teacher", "student"}
    assert db.session.scalar(db.select(db.func.count()).select_from(Student)) == 1
    assert db.session.scalar(db.select(db.func.count()).select_from(Teacher)) == 1
    assert db.session.scalar(db.select(db.func.count()).select_from(Course)) == 1

    # 教师/学生档案与账号正确挂接
    teacher = db.session.scalar(db.select(Teacher))
    student = db.session.scalar(db.select(Student))
    assert teacher.user.username == "teacher"
    assert student.user.username == "student"
    assert db.session.scalar(db.select(Course)).teacher_id == teacher.id

    # 再跑一次不应产生重复记录
    again = runner.invoke(args=["seed"])
    assert again.exit_code == 0, again.output
    assert db.session.scalar(db.select(db.func.count()).select_from(User)) == 3


def test_seed_passwords_are_hashed(app: Flask, runner: FlaskCliRunner) -> None:
    """为 R2 登录做准备：库里只有哈希，且校验函数可用。"""
    runner.invoke(args=["seed"])
    admin = db.session.scalar(db.select(User).filter_by(username="admin"))
    assert admin.password_hash != "admin123"
    assert admin.check_password("admin123") is True
    assert admin.check_password("wrong-password") is False


# --------------------------------------------------------------------------- #
# 数据库约束：唯一性与取值范围
# --------------------------------------------------------------------------- #
def _make_enrollment() -> tuple[User, Teacher, Student, Course, Enrollment]:
    """构造一条最小可用链路：用户 → 教师/学生 → 课程 → 选课。"""
    admin = User(username="u_admin", role="admin", real_name="管理员")
    admin.set_password("x")
    teacher_user = User(username="u_teacher", role="teacher", real_name="教师")
    teacher_user.set_password("x")
    student_user = User(username="u_student", role="student", real_name="学生")
    student_user.set_password("x")
    db.session.add_all([admin, teacher_user, student_user])
    db.session.flush()

    teacher = Teacher(user_id=teacher_user.id, tno="T9001", name="教师")
    student = Student(user_id=student_user.id, sno="9001", name="学生")
    db.session.add_all([teacher, student])
    db.session.flush()

    course = Course(
        code="C9001",
        name="测试课程",
        credit=2.0,
        hours=32,
        teacher_id=teacher.id,
        semester="2025-2026-1",
        capacity=10,
    )
    db.session.add(course)
    db.session.flush()

    enrollment = Enrollment(student_id=student.id, course_id=course.id)
    db.session.add(enrollment)
    db.session.commit()
    return admin, teacher, student, course, enrollment


def test_username_and_sno_must_be_unique(app: Flask) -> None:
    _make_enrollment()

    db.session.add(User(username="u_admin", role="student", real_name="重复账号"))
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()

    other_user = User(username="u_student2", role="student", real_name="另一学生")
    other_user.set_password("x")
    db.session.add(other_user)
    db.session.flush()
    db.session.add(Student(user_id=other_user.id, sno="9001", name="学号重复"))
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()


def test_role_is_restricted_to_three_values(app: Flask) -> None:
    db.session.add(User(username="u_boss", role="boss", real_name="非法角色"))
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()


def test_cannot_enroll_same_course_twice(app: Flask) -> None:
    _, _, student, course, _ = _make_enrollment()
    db.session.add(Enrollment(student_id=student.id, course_id=course.id))
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()


def test_score_unique_per_exam_type_and_range(app: Flask) -> None:
    """成绩挂在选课记录上：同一考核类型不可重复，且分值必须在 0~100。"""
    admin, _, _, _, enrollment = _make_enrollment()

    db.session.add(Score(enrollment_id=enrollment.id, exam_type="期末", score=88.0,
                         updated_by=admin.id))
    db.session.commit()

    # 同一选课 + 同一考核类型重复录入 → 拒绝
    db.session.add(Score(enrollment_id=enrollment.id, exam_type="期末", score=90.0,
                         updated_by=admin.id))
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()

    # 不同考核类型可以录入
    db.session.add(Score(enrollment_id=enrollment.id, exam_type="期中", score=75.0,
                         updated_by=admin.id))
    db.session.commit()
    assert db.session.scalar(db.select(db.func.count()).select_from(Score)) == 2

    # 分数越界 → 拒绝
    db.session.add(Score(enrollment_id=enrollment.id, exam_type="平时", score=150.0,
                         updated_by=admin.id))
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()
