"""按角色准备首页数据。

R3 交付物"三种角色各自的首页"：同一个 ``/`` 地址，登录角色不同，
首页顶部展示的内容不同：

| 角色 | 首页展示 |
| --- | --- |
| 未登录 | 系统状态 + 登录入口 |
| admin | 账号数 / 学生 / 教师 / 课程 / 选课 / 成绩总览 + 最近账号 |
| teacher | 我的授课课程 + 选课人数 + 已录成绩条数 |
| student | 我的选课列表 + 已出成绩条数 |

所有数字都实时查库，不缓存。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from .extensions import db
from .models import Course, Enrollment, Score, Student, Teacher, User

#: 首页"最近账号"展示条数
RECENT_LIMIT = 5


def _count(model: Any, *conditions: Any) -> int:
    """``SELECT count(*)`` 小工具。"""
    stmt = select(func.count()).select_from(model)
    if conditions:
        stmt = stmt.where(*conditions)
    return int(db.session.scalar(stmt) or 0)


def _course_rows(user: Any) -> list[dict]:
    """"我的课程"：教师看自己授课，学生看自己已选，管理员看不到这个卡片。"""
    stmt = select(Course).options(selectinload(Course.teacher)).order_by(Course.semester, Course.code)

    if user.role == "teacher":
        teacher = user.teacher
        if teacher is None:
            return []
        stmt = stmt.where(Course.teacher_id == teacher.id)
    elif user.role == "student":
        student = user.student
        if student is None:
            return []
        stmt = stmt.join(Enrollment, Enrollment.course_id == Course.id).where(
            Enrollment.student_id == student.id
        )
    else:
        return []

    rows: list[dict] = []
    for course in db.session.scalars(stmt).unique().all():
        rows.append(
            {
                "course": course,
                "enrolled": _count(Enrollment, Enrollment.course_id == course.id),
                "graded": int(
                    db.session.scalar(
                        select(func.count())
                        .select_from(Score)
                        .join(Enrollment, Score.enrollment_id == Enrollment.id)
                        .where(Enrollment.course_id == course.id)
                    )
                    or 0
                ),
            }
        )
    return rows


def dashboard_context(user: Any) -> dict:
    """首页模板需要的、按角色变化的上下文。"""
    base = {
        "recent": [],
        "stats": {},
        "course_rows": [],
        "graded_mine": 0,
        "enrolled_mine": 0,
    }

    if user.role == "admin":
        base["stats"] = {
            "user": _count(User),
            "active_user": _count(User, User.is_active.is_(True)),
            "student": _count(Student),
            "teacher": _count(Teacher),
            "course": _count(Course),
            "enrollment": _count(Enrollment),
            "score": _count(Score),
        }
        base["recent"] = db.session.scalars(
            select(User).order_by(User.id.desc()).limit(RECENT_LIMIT)
        ).all()
        return base

    if user.role == "teacher":
        teacher = user.teacher
        if teacher is None:
            return base
        course_ids = list(
            db.session.scalars(select(Course.id).where(Course.teacher_id == teacher.id))
        )
        scope = course_ids or [-1]
        base["course_rows"] = _course_rows(user)
        base["stats"] = {
            "course": len(course_ids),
            "student": int(
                db.session.scalar(
                    select(func.count(func.distinct(Enrollment.student_id))).where(
                        Enrollment.course_id.in_(scope)
                    )
                )
                or 0
            ),
            "graded": int(
                db.session.scalar(
                    select(func.count())
                    .select_from(Score)
                    .join(Enrollment, Score.enrollment_id == Enrollment.id)
                    .where(Enrollment.course_id.in_(scope))
                )
                or 0
            ),
        }
        return base

    if user.role == "student":
        student = user.student
        if student is None:
            return base
        base["course_rows"] = _course_rows(user)
        base["enrolled_mine"] = _count(Enrollment, Enrollment.student_id == student.id)
        base["graded_mine"] = int(
            db.session.scalar(
                select(func.count())
                .select_from(Score)
                .join(Enrollment, Score.enrollment_id == Enrollment.id)
                .where(Enrollment.student_id == student.id)
            )
            or 0
        )
        base["stats"] = {
            "course": base["enrolled_mine"],
            "graded": base["graded_mine"],
        }
        return base

    return base


__all__ = ["RECENT_LIMIT", "dashboard_context"]
