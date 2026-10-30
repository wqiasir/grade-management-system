"""按角色准备首页数据（精简优化版）"""
from __future__ import annotations

from typing import Any
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from .extensions import db
from .models import Course, Enrollment, Score, Student, Teacher, User

#: 首页"最近账号"展示条数
RECENT_LIMIT = 5


def _count(model: Any, *conditions: Any) -> int:
    """通用 count 工具"""
    return int(db.session.scalar(select(func.count()).select_from(model).where(*conditions)) or 0)


def dashboard_context(user: Any) -> dict:
    """首页模板需要的、按角色变化的上下文。"""
    base = {"recent": [], "stats": {}, "course_rows": [], "graded_mine": 0, "enrolled_mine": 0}
    role = getattr(user, "role", None)

    # 1. Admin 管理员角色
    if role == "admin":
        base["stats"] = {
            "user": _count(User),
            "active_user": _count(User, User.is_active.is_(True)),
            "student": _count(Student),
            "teacher": _count(Teacher),
            "course": _count(Course),
            "enrollment": _count(Enrollment),
            "score": _count(Score),
        }
        base["recent"] = db.session.scalars(select(User).order_by(User.id.desc()).limit(RECENT_LIMIT)).all()
        return base

    # 2. Teacher 教师或 Student 学生角色
    if role == "teacher" and user.teacher:
        teacher_id = user.teacher.id
        stmt = select(Course).options(selectinload(Course.teacher)).where(Course.teacher_id == teacher_id)
        
        # 教师面板统计
        course_ids = db.session.scalars(select(Course.id).where(Course.teacher_id == teacher_id)).all()
        scope = course_ids or [-1]
        base["stats"] = {
            "course": len(course_ids),
            "student": int(db.session.scalar(select(func.count(func.distinct(Enrollment.student_id))).where(Enrollment.course_id.in_(scope))) or 0),
            "graded": int(db.session.scalar(select(func.count()).select_from(Score).join(Enrollment, Score.enrollment_id == Enrollment.id).where(Enrollment.course_id.in_(scope))) or 0),
        }

    elif role == "student" and user.student:
        student_id = user.student.id
        stmt = select(Course).options(selectinload(Course.teacher)).join(Enrollment, Enrollment.course_id == Course.id).where(Enrollment.student_id == student_id)
        
        # 学生面板统计
        base["enrolled_mine"] = _count(Enrollment, Enrollment.student_id == student_id)
        base["graded_mine"] = int(db.session.scalar(select(func.count()).select_from(Score).join(Enrollment, Score.enrollment_id == Enrollment.id).where(Enrollment.student_id == student_id)) or 0)
        base["stats"] = {"course": base["enrolled_mine"], "graded": base["graded_mine"]}
    else:
        return base  # 未登录或其他情况返回空 base

    # 3. 统一加载教师/学生的课程及附带的选课数与成绩数（消灭 N+1 查询）
    courses = db.session.scalars(stmt.order_by(Course.semester, Course.code)).unique().all()
    if courses:
        c_ids = [c.id for c in courses]
        
        # 批量获取每门课的选课人数
        enrolled_map = dict(db.session.execute(
            select(Enrollment.course_id, func.count()).where(Enrollment.course_id.in_(c_ids)).group_by(Enrollment.course_id)
        ).all())
        
        # 批量获取每门课的已录成绩数
        graded_map = dict(db.session.execute(
            select(Enrollment.course_id, func.count())
            .select_from(Score)
            .join(Enrollment, Score.enrollment_id == Enrollment.id)
            .where(Enrollment.course_id.in_(c_ids))
            .group_by(Enrollment.course_id)
        ).all())

        base["course_rows"] = [
            {"course": c, "enrolled": enrolled_map.get(c.id, 0), "graded": graded_map.get(c.id, 0)}
            for c in courses
        ]

    return base


__all__ = ["RECENT_LIMIT", "dashboard_context"]