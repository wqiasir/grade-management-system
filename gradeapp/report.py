"""统计报表蓝图（R3 起）。

R3 交付（第 6 节权限矩阵的"统计报表"一行，先落地**数据口径与服务端范围**）：
1. ``/report/overview`` —— 统计概览：
   - admin：全校范围；
   - teacher：**仅自己授课的课程**；
   - student：**仅本人**（自己的选课与成绩）。
2. 口径（R9 会补 Chart.js 图表，本轮先把口径固定在代码里，避免验收时口径争议）：
   - 平均分 = 全部已录入成绩的算术平均（保留 2 位小数）；
   - 及格率 = 已录入成绩中 ``>= 60`` 的条数 ÷ 已录入成绩总条数（保留 1 位小数）；
   - 没有成绩的课程平均分显示为 ``—``、及格率为 0%，且不计入汇总的平均分样本。

R9 将在本蓝图补教师课程统计页、管理员全校概览页与图表。
"""

from __future__ import annotations

from flask import Blueprint, g, render_template
from sqlalchemy import case, func, select

from .decorators import ROLE_LABELS, login_required, role_label, role_required
from .extensions import db
from .models import Course, Enrollment, Score, Student, Teacher

bp = Blueprint("report", __name__, url_prefix="/report")

#: 及格线（口径写死在这里，R9 若要可配置再抽到 config）
PASS_SCORE = 60.0

#: 空范围的占位值：``IN ()`` 在部分数据库上不合法，用一个不存在的 id 代替
NO_COURSE_ID = -1


def _visible_course_ids(user) -> list[int] | None:
    """当前用户在报表里能看到的课程 id 列表；``None`` 表示不限制（全校）。"""
    if user.role == "admin":
        return None
    if user.role == "teacher":
        teacher = user.teacher
        if teacher is None:
            return []
        return list(
            db.session.scalars(select(Course.id).where(Course.teacher_id == teacher.id))
        )
    if user.role == "student":
        student = user.student
        if student is None:
            return []
        return list(
            db.session.scalars(
                select(Enrollment.course_id).where(Enrollment.student_id == student.id)
            )
        )
    return []


@bp.get("/overview")
@role_required("admin", "teacher", "student")
@login_required
def overview():
    """统计概览：按角色收缩数据范围后，用同一套口径计算。"""
    user = g.user
    visible = _visible_course_ids(user)
    scope_ids = [NO_COURSE_ID] if visible == [] else visible

    course_stmt = select(Course).order_by(Course.semester, Course.code)
    if scope_ids is not None:
        course_stmt = course_stmt.where(Course.id.in_(scope_ids))
    courses = db.session.scalars(course_stmt).all()

    # 每门课程：选课人数、已录成绩条数、平均分、及格条数（一次分组查询算完，避免 N+1）
    stat_map: dict[int, dict] = {}
    enrolled_map: dict[int, int] = {}
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
        for course_id, enrolled, graded, avg_score, passed in rows:
            graded = int(graded or 0)
            passed = int(passed or 0)
            enrolled_map[course_id] = int(enrolled or 0)
            stat_map[course_id] = {
                "graded": graded,
                "average": round(float(avg_score), 2) if avg_score is not None else None,
                "pass_rate": round(passed / graded * 100, 1) if graded else 0.0,
            }

    course_stats = [
        {
            "course": course,
            "enrolled": enrolled_map.get(course.id, 0),
            "graded": stat_map.get(course.id, {}).get("graded", 0),
            "average": stat_map.get(course.id, {}).get("average"),
            "pass_rate": stat_map.get(course.id, {}).get("pass_rate", 0.0),
        }
        for course in courses
    ]

    # 汇总口径：范围与上面一致，只对"已录入的成绩"取平均与及格率
    score_scope = select(Score.score).join(
        Enrollment, Score.enrollment_id == Enrollment.id
    )
    if scope_ids is not None:
        score_scope = score_scope.where(Enrollment.course_id.in_(scope_ids))
    sub = score_scope.subquery()
    graded_total, avg_total = db.session.execute(
        select(func.count(sub.c.score), func.avg(sub.c.score))
    ).one()
    graded_total = int(graded_total or 0)
    passed_total = int(
        db.session.scalar(
            select(func.count()).select_from(sub).where(sub.c.score >= PASS_SCORE)
        )
        or 0
    )

    # 学生维度计数：管理员看全校，教师看自己课程里的学生，学生看自己
    if user.role == "admin":
        student_count = int(db.session.scalar(select(func.count()).select_from(Student)) or 0)
        teacher_count = int(db.session.scalar(select(func.count()).select_from(Teacher)) or 0)
    elif user.role == "teacher":
        student_count = int(
            db.session.scalar(
                select(func.count(func.distinct(Enrollment.student_id))).where(
                    Enrollment.course_id.in_(scope_ids or [NO_COURSE_ID])
                )
            )
            or 0
        )
        teacher_count = 1 if user.teacher is not None else 0
    else:  # student
        student_count = 1 if user.student is not None else 0
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
