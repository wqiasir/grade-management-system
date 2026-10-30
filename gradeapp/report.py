"""统计报表蓝图（精简优化版）。"""
from __future__ import annotations

from flask import Blueprint, g, render_template
from sqlalchemy import case, func, select

from .decorators import ROLE_LABELS, login_required, role_label, role_required
from .extensions import db
from .models import Course, Enrollment, Score, Student, Teacher

bp = Blueprint("report", __name__, url_prefix="/report")

PASS_SCORE = 60.0
NO_COURSE_ID = -1


def _visible_course_ids(user) -> list[int] | None:
    """获取当前用户可见的课程 id 列表；None 表示全校不限制。"""
    if user.role == "admin":
        return None
    if user.role == "teacher" and user.teacher:
        return list(db.session.scalars(select(Course.id).where(Course.teacher_id == user.teacher.id)))
    if user.role == "student" and user.student:
        return list(db.session.scalars(select(Enrollment.course_id).where(Enrollment.student_id == user.student.id)))
    return []


@bp.get("/overview")
@role_required("admin", "teacher", "student")
@login_required
def overview():
    user = g.user
    visible = _visible_course_ids(user)
    scope_ids = [NO_COURSE_ID] if visible == [] else visible

    # 1. 课程列表查询
    course_stmt = select(Course).order_by(Course.semester, Course.code)
    if scope_ids is not None:
        course_stmt = course_stmt.where(Course.id.in_(scope_ids))
    courses = db.session.scalars(course_stmt).all()

    # 2. 单课统计数据（一次分组查询算完）
    stat_map, enrolled_map = {}, {}
    if courses:
        course_ids = [c.id for c in courses]
        rows = db.session.execute(
            select(
                Enrollment.course_id,
                func.count(func.distinct(Enrollment.id)),
                func.count(Score.id),
                func.avg(Score.score),
                func.sum(case((Score.score >= PASS_SCORE, 1), else_=0)),
            )
            .select_from(Enrollment)
            .outerjoin(Score, Score.enrollment_id == Enrollment.id)
            .where(Enrollment.course_id.in_(course_ids))
            .group_by(Enrollment.course_id)
        ).all()
        
        for cid, enrolled, graded, avg_score, passed in rows:
            g_cnt, p_cnt = int(graded or 0), int(passed or 0)
            enrolled_map[cid] = int(enrolled or 0)
            stat_map[cid] = {
                "graded": g_cnt,
                "average": round(float(avg_score), 2) if avg_score is not None else None,
                "pass_rate": round(p_cnt / g_cnt * 100, 1) if g_cnt else 0.0,
            }

    course_stats = [
        {
            "course": c,
            "enrolled": enrolled_map.get(c.id, 0),
            "graded": (s := stat_map.get(c.id, {})).get("graded", 0),
            "average": s.get("average"),
            "pass_rate": s.get("pass_rate", 0.0),
        }
        for c in courses
    ]

    # 3. 汇总口径（基于已录入成绩计算）
    score_stmt = select(Score.score).join(Enrollment, Score.enrollment_id == Enrollment.id)
    if scope_ids is not None:
        score_stmt = score_stmt.where(Enrollment.course_id.in_(scope_ids))
    
    sub = score_stmt.subquery()
    graded_total, avg_total = db.session.execute(
        select(func.count(sub.c.score), func.avg(sub.c.score))
    ).one()
    
    graded_total = int(graded_total or 0)
    passed_total = int(db.session.scalar(select(func.count()).select_from(sub).where(sub.c.score >= PASS_SCORE)) or 0)

    # 4. 人数维度统计
    if user.role == "admin":
        student_count = int(db.session.scalar(select(func.count()).select_from(Student)) or 0)
        teacher_count = int(db.session.scalar(select(func.count()).select_from(Teacher)) or 0)
    elif user.role == "teacher":
        student_count = int(db.session.scalar(
            select(func.count(func.distinct(Enrollment.student_id))).where(Enrollment.course_id.in_(scope_ids or [NO_COURSE_ID]))
        ) or 0)
        teacher_count = 1 if user.teacher else 0
    else:
        student_count = 1 if user.student else 0
        teacher_count = len({c.teacher_id for c in courses if c.teacher_id})

    summary = {
        "courses": len(courses),
        "students": student_count,
        "teachers": teacher_count,
        "graded": graded_total,
        "average": round(float(avg_total), 2) if avg_total is not None else None,
        "pass_rate": round(passed_total / graded_total * 100, 1) if graded_total else 0.0,
        "pass_score": PASS_SCORE,
    }

    scope_hint = {
        "admin": "全校范围",
        "teacher": "仅你授课的课程",
        "student": "仅你本人的选课与成绩",
    }.get(user.role, "无可见范围")

    return render_template(
        "report/overview.html",
        summary=summary,
        course_stats=course_stats,
        scope_hint=scope_hint,
        role_label=role_label(user.role),
        role_labels=ROLE_LABELS,
    )


__all__ = ["PASS_SCORE", "bp"]