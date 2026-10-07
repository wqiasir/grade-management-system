"""成绩与选课蓝图（R3 起）。

R3 交付（按计划"一轮一功能"，本轮只落地"能看见什么"，写操作留给后续轮次）：
1. ``/score/my-courses``   —— **按角色分流的"我的课程"**：
   - teacher：自己授课的课程（权限矩阵：课程信息 👁 仅自己授课）
   - student：自己已选的课程（权限矩阵：课程信息 👁 已选课程）
   - admin：全部课程（权限矩阵：课程信息 ✅ 全部）
2. ``/score/courses/<id>`` —— 课程详情 + 选课名单（只读），
   内含**行级校验**：教师的非自授课程返回 403，学生的未选课程返回 403。

后续轮次在本蓝图继续补：
  - R6 选课 / 退课（``/score/enroll`` 等）
  - R7 成绩录入（``/score/courses/<id>/grades``）
  - R8 成绩查询（``/score/my-scores`` 等）
"""

from __future__ import annotations

from flask import Blueprint, abort, g, render_template, url_for
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from .decorators import (
    ROLE_LABELS,
    guard_course_access,
    login_required,
    role_label,
    role_required,
)
from .extensions import db
from .models import Course, Enrollment, Score

bp = Blueprint("score", __name__, url_prefix="/score")


def _course_rows_for(user) -> list[dict]:
    """按角色取出"我的课程"，并附上选课人数与已录成绩条数。"""
    stmt = (
        select(Course)
        .options(selectinload(Course.teacher))
        .order_by(Course.semester, Course.code)
    )

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
    elif user.role != "admin":
        return []

    rows: list[dict] = []
    for course in db.session.scalars(stmt).unique().all():
        enrolled = int(
            db.session.scalar(
                select(func.count())
                .select_from(Enrollment)
                .where(Enrollment.course_id == course.id)
            )
            or 0
        )
        graded = int(
            db.session.scalar(
                select(func.count())
                .select_from(Score)
                .join(Enrollment, Score.enrollment_id == Enrollment.id)
                .where(Enrollment.course_id == course.id)
            )
            or 0
        )
        rows.append({"course": course, "enrolled": enrolled, "graded": graded})
    return rows


@bp.get("/my-courses")
@role_required("admin", "teacher", "student")
@login_required
def my_courses():
    """我的课程：同一个地址，三种角色看到三种范围。"""
    rows = _course_rows_for(g.user)
    return render_template(
        "score/my_courses.html",
        rows=rows,
        role_label=role_label(g.user.role),
        role_labels=ROLE_LABELS,
    )


@bp.get("/courses/<int:course_id>")
@role_required("admin", "teacher", "student")
@login_required
def course_detail(course_id: int):
    """课程详情与选课名单（只读）。

    **行级校验**：``guard_course_access`` 会拦住"教师看别人的课"与"学生看没选的课"，
    返回 403 而不是 404 —— 权限矩阵要求的"是不是自己教的课"必须在这里落实。
    """
    course = db.session.get(Course, course_id)
    if course is None:
        abort(404)

    denial = guard_course_access(course)
    if denial is not None:
        return denial

    enrollments = db.session.scalars(
        select(Enrollment)
        .options(selectinload(Enrollment.student))
        .where(Enrollment.course_id == course.id)
        .order_by(Enrollment.student_id)
    ).all()

    score_map: dict[int, list[Score]] = {}
    for item in db.session.scalars(
        select(Score)
        .join(Enrollment, Score.enrollment_id == Enrollment.id)
        .where(Enrollment.course_id == course.id)
    ).all():
        score_map.setdefault(item.enrollment_id, []).append(item)

    return render_template(
        "score/course_detail.html",
        course=course,
        enrollments=enrollments,
        score_map=score_map,
        role_label=role_label(g.user.role),
        back_url=url_for("score.my_courses"),
    )


__all__ = ["bp"]
