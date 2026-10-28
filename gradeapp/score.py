"""选课与成绩蓝图。

R3 交付（只读）：
1. ``/score/my-courses``   —— **按角色分流的"我的课程"**：
   - teacher：自己授课的课程（权限矩阵：课程信息 👁 仅自己授课）
   - student：自己已选的课程（权限矩阵：课程信息 👁 已选课程）
   - admin：全部课程（权限矩阵：课程信息 ✅ 全部）
2. ``/score/courses/<id>`` —— 课程详情 + 选课名单（只读），
   内含**行级校验**：教师的非自授课程返回 403，学生的未选课程返回 403。

R6 交付（选课管理）：
3. ``GET  /score/enroll``                      —— 学生可选课程列表（搜索 / 学期筛选 / 容量状态）
4. ``POST /score/enroll/<course_id>``          —— 学生选课（重复选课、容量上限校验）
5. ``POST /score/enrollments/<id>/drop``       —— 退课（学生仅本人；管理员全部；已出成绩不可退）
6. ``POST /score/courses/<id>/enroll``         —— 管理员把学生加入课程（权限矩阵"选课/退课 ✅ 全部"）
7. ``/score/courses/<id>`` 升级为**选课名单页**：管理员可加人 / 移人，教师只读，
   学生可退选自己的记录。

后续轮次在本蓝图继续补：
  - R7 成绩录入（``/score/courses/<id>/grades``）
  - R8 成绩查询（``/score/my-scores`` 等）

容量口径：``capacity <= 0`` 视为**不限容量**（R5 的课程表单允许填 0，默认也是 0）；
容量为正数时，已选人数达到容量即不可再选。该口径写在 ``_capacity_reached`` 一处，
选课与管理员代选共用，避免两处判断不一致。
"""

from __future__ import annotations

from urllib.parse import urlsplit

from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for
from flask_wtf import FlaskForm
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload
from wtforms import SelectField
from wtforms.validators import DataRequired

from .decorators import (
    ROLE_LABELS,
    forbidden,
    guard_course_access,
    login_required,
    role_label,
    role_required,
)
from .extensions import db
from .models import Course, Enrollment, Score, Student

bp = Blueprint("score", __name__, url_prefix="/score")


# --------------------------------------------------------------------------- #
# 表单
# --------------------------------------------------------------------------- #
class ActionForm(FlaskForm):
    """空表单：只为给"选课 / 退课"这类无字段的 POST 动作生成 CSRF token。"""


class RosterAddForm(FlaskForm):
    """管理员把学生加入课程：下拉框只列尚未选该课的学生。

    ``validate_choice=False``：即使提交的 id 不在当前下拉选项里（例如学生刚被
    另一请求选入），也交给视图给出"已经选过"这类准确提示，而不是笼统的表单错误。
    合法学生 id 都大于 0，因此 ``DataRequired`` 能挡住"未选择"的 0。
    """

    student_id = SelectField(
        "学生",
        coerce=int,
        validators=[DataRequired(message="请选择要加入课程的学生")],
        validate_choice=False,
    )


# --------------------------------------------------------------------------- #
# 查询小工具
# --------------------------------------------------------------------------- #
def _enrolled_count(course_id: int) -> int:
    """某门课的已选人数。"""
    return int(
        db.session.scalar(
            select(func.count())
            .select_from(Enrollment)
            .where(Enrollment.course_id == course_id)
        )
        or 0
    )


def _score_count(enrollment_id: int) -> int:
    """某条选课记录下已录的成绩条数（>0 即"已出成绩"）。"""
    return int(
        db.session.scalar(
            select(func.count())
            .select_from(Score)
            .where(Score.enrollment_id == enrollment_id)
        )
        or 0
    )


def _capacity_reached(course: Course, enrolled: int) -> bool:
    """课程是否已满。

    **口径**：``capacity <= 0`` 表示不限容量（课程表单允许 0，默认也是 0，
    新建课程不至于因为忘了填容量而完全无法选课）；正数容量按"已选 >= 容量"判定。
    """
    return course.capacity > 0 and enrolled >= course.capacity


def _remaining_seats(course: Course, enrolled: int) -> int | None:
    """剩余名额；``None`` 表示不限容量（模板里显示"不限"）。"""
    if course.capacity <= 0:
        return None
    return max(course.capacity - enrolled, 0)


def _find_enrollment(student_id: int, course_id: int) -> Enrollment | None:
    return db.session.scalar(
        select(Enrollment).where(
            Enrollment.student_id == student_id,
            Enrollment.course_id == course_id,
        )
    )


def _safe_next(default: str) -> str:
    """只接受站内相对地址，防止 ``next=//evil.com`` 造成开放重定向。"""
    target = (request.form.get("next") or "").strip()
    parts = urlsplit(target)
    if (
        target.startswith("/")
        and not target.startswith("//")
        and not parts.scheme
        and not parts.netloc
        and "\\" not in target
    ):
        return target
    return default


def _addable_student_choices(course: Course) -> list[tuple[int, str]]:
    """管理员"加入课程"下拉框：只列还没有选这门课的学生。"""
    enrolled_ids = set(
        db.session.scalars(
            select(Enrollment.student_id).where(Enrollment.course_id == course.id)
        ).all()
    )
    students = db.session.scalars(select(Student).order_by(Student.sno)).all()
    return [(0, "—— 选择学生 ——")] + [
        (student.id, f"{student.name}（{student.sno}）")
        for student in students
        if student.id not in enrolled_ids
    ]


# --------------------------------------------------------------------------- #
# "我的课程"：三种角色三种范围
# --------------------------------------------------------------------------- #
def _course_rows_for(user) -> list[dict]:
    """按角色取出"我的课程"，并附上选课人数与已录成绩条数。

    学生额外带 ``my_enrollment`` / ``my_score_count``，用于判断"能不能退课"；
    教师与管理员不需要这两个字段（它们为 ``None`` / 0）。
    """
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
        enrolled = _enrolled_count(course.id)
        graded = int(
            db.session.scalar(
                select(func.count())
                .select_from(Score)
                .join(Enrollment, Score.enrollment_id == Enrollment.id)
                .where(Enrollment.course_id == course.id)
            )
            or 0
        )

        my_enrollment: Enrollment | None = None
        my_score_count = 0
        if user.role == "student" and user.student is not None:
            my_enrollment = _find_enrollment(user.student.id, course.id)
            if my_enrollment is not None:
                my_score_count = _score_count(my_enrollment.id)

        rows.append(
            {
                "course": course,
                "enrolled": enrolled,
                "graded": graded,
                "my_enrollment": my_enrollment,
                "my_score_count": my_score_count,
            }
        )
    return rows


@bp.get("/my-courses")
@role_required("admin", "teacher", "student")
@login_required
def my_courses():
    """我的课程：同一个地址，三种角色看到三种范围。

    管理员这一页同时充当"选课名单入口"：看到全部课程 + 已选人数，
    点进课程详情即可查看/维护名单。
    """
    rows = _course_rows_for(g.user)
    return render_template(
        "score/my_courses.html",
        rows=rows,
        role_label=role_label(g.user.role),
        role_labels=ROLE_LABELS,
        action_form=ActionForm(),
    )


# --------------------------------------------------------------------------- #
# R6：学生选课 / 退课
# --------------------------------------------------------------------------- #
@bp.get("/enroll")
@role_required("student")
@login_required
def enroll_courses():
    """可选课程列表：支持关键词与学期筛选，并标出"已选 / 已满 / 可选"。"""
    keyword = (request.args.get("q") or "").strip()
    semester = (request.args.get("semester") or "").strip()

    semesters = list(
        db.session.scalars(
            select(Course.semester).distinct().order_by(Course.semester.desc())
        ).all()
    )

    stmt = select(Course).options(selectinload(Course.teacher)).order_by(
        Course.semester.desc(), Course.code
    )
    if keyword:
        like = f"%{keyword}%"
        stmt = stmt.where(or_(Course.code.like(like), Course.name.like(like)))
    if semester in semesters:
        stmt = stmt.where(Course.semester == semester)
    else:
        semester = ""

    student = g.user.student
    my_enrollments: dict[int, Enrollment] = {}
    if student is not None:
        my_enrollments = {
            enrollment.course_id: enrollment
            for enrollment in db.session.scalars(
                select(Enrollment).where(Enrollment.student_id == student.id)
            ).all()
        }

    rows: list[dict] = []
    for course in db.session.scalars(stmt).all():
        enrolled = _enrolled_count(course.id)
        my_enrollment = my_enrollments.get(course.id)
        rows.append(
            {
                "course": course,
                "enrolled": enrolled,
                "remaining": _remaining_seats(course, enrolled),
                "my_enrollment": my_enrollment,
                "is_full": _capacity_reached(course, enrolled),
            }
        )

    return render_template(
        "score/enroll_courses.html",
        rows=rows,
        keyword=keyword,
        semester=semester,
        semesters=semesters,
        student=student,
        selected_count=len(my_enrollments),
        action_form=ActionForm(),
    )


@bp.post("/enroll/<int:course_id>")
@role_required("student")
@login_required
def enroll(course_id: int):
    """学生选课：重复选课与容量上限都拒绝，并回到原页面提示。"""
    course = db.session.get(Course, course_id)
    if course is None:
        abort(404)

    student = g.user.student
    if student is None:
        flash("当前账号没有关联的学生档案，无法选课，请联系管理员。", "error")
        return redirect(_safe_next(url_for("score.enroll_courses")))

    existing = _find_enrollment(student.id, course.id)
    if existing is not None:
        flash(
            f"你已经选过课程 [{course.code}] {course.name}，不能重复选课。",
            "error",
        )
        return redirect(_safe_next(url_for("score.enroll_courses")))

    enrolled = _enrolled_count(course.id)
    if _capacity_reached(course, enrolled):
        flash(
            f"课程 [{course.code}] {course.name} 已满"
            f"（{enrolled}/{course.capacity}），无法选课。",
            "error",
        )
        return redirect(_safe_next(url_for("score.enroll_courses")))

    db.session.add(Enrollment(student_id=student.id, course_id=course.id))
    try:
        db.session.commit()
    except IntegrityError:
        # 并发下两个请求同时通过上面的存在性检查时，靠 UNIQUE(student_id, course_id) 兜底
        db.session.rollback()
        flash(
            f"你已经选过课程 [{course.code}] {course.name}，不能重复选课。",
            "error",
        )
        return redirect(_safe_next(url_for("score.enroll_courses")))

    flash(f"已选上课程 [{course.code}] {course.name}。", "success")
    return redirect(_safe_next(url_for("score.enroll_courses")))


@bp.post("/enrollments/<int:enrollment_id>/drop")
@role_required("admin", "student")
@login_required
def drop_enrollment(enrollment_id: int):
    """退课：学生只能退自己的，管理员可以退任意一条。

    业务规则：**已出成绩的课程不允许退课**，避免成绩记录失去选课载体。
    """
    enrollment = db.session.get(Enrollment, enrollment_id)
    if enrollment is None:
        abort(404)

    course = enrollment.course
    code = course.code if course is not None else "?"
    name = course.name if course is not None else "?"

    if g.user.role == "student":
        student = g.user.student
        if student is None or enrollment.student_id != student.id:
            return forbidden(message="只能退选你自己的课程。")

    # 删除后对象不可再访问关系属性，回跳地址必须提前算好
    return_url = _drop_return(enrollment)

    if _score_count(enrollment.id) > 0:
        flash(
            f"课程 [{code}] {name} 已有成绩，已出成绩的课程不允许退课。",
            "error",
        )
        return redirect(return_url)

    db.session.delete(enrollment)
    db.session.commit()
    flash(f"已退选课程 [{code}] {name}。", "success")
    return redirect(return_url)


def _drop_return(enrollment: Enrollment) -> str:
    """退课后的回跳地址：管理员回课程名单，学生回原页面（默认为"我的课程"）。"""
    default = url_for("score.my_courses")
    if g.user.role == "admin" and enrollment.course_id is not None:
        default = url_for("score.course_detail", course_id=enrollment.course_id)
    return _safe_next(default)


# --------------------------------------------------------------------------- #
# R6：选课名单（管理员可维护，教师只读）
# --------------------------------------------------------------------------- #
@bp.get("/courses/<int:course_id>")
@role_required("admin", "teacher", "student")
@login_required
def course_detail(course_id: int):
    """课程详情与选课名单。

    **行级校验**：``guard_course_access`` 会拦住"教师看别人的课"与"学生看没选的课"，
    返回 403 而不是 404 —— 权限矩阵要求的"是不是自己教的课"必须在这里落实。

    R6 起这一页就是"选课名单页"：
    - 管理员：可把学生加入课程、可移出（已有成绩的除外）；
    - 教师：只读名单（权限矩阵：教师不能选课/退课）；
    - 学生：可退选自己的记录（已有成绩的除外）。
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

    my_enrollment_id: int | None = None
    if g.user.role == "student" and g.user.student is not None:
        my_enrollment_id = next(
            (
                enrollment.id
                for enrollment in enrollments
                if enrollment.student_id == g.user.student.id
            ),
            None,
        )

    add_form: RosterAddForm | None = None
    if g.user.role == "admin":
        add_form = RosterAddForm()
        add_form.student_id.choices = _addable_student_choices(course)

    enrolled_count = len(enrollments)
    return render_template(
        "score/course_detail.html",
        course=course,
        enrollments=enrollments,
        score_map=score_map,
        enrolled_count=enrolled_count,
        remaining=_remaining_seats(course, enrolled_count),
        my_enrollment_id=my_enrollment_id,
        add_form=add_form,
        action_form=ActionForm(),
        role_label=role_label(g.user.role),
        back_url=url_for("score.my_courses"),
    )


@bp.post("/courses/<int:course_id>/enroll")
@role_required("admin")
@login_required
def roster_add(course_id: int):
    """管理员把一名学生加入课程（权限矩阵：选课/退课 admin ✅ 全部）。"""
    course = db.session.get(Course, course_id)
    if course is None:
        abort(404)

    form = RosterAddForm()
    form.student_id.choices = _addable_student_choices(course)

    if not form.validate_on_submit():
        message = "；".join(
            error for errors in form.errors.values() for error in errors
        )
        flash(message or "请选择要加入课程的学生。", "error")
        return redirect(url_for("score.course_detail", course_id=course.id))

    student = db.session.get(Student, form.student_id.data)
    if student is None:
        abort(404)

    existing = _find_enrollment(student.id, course.id)
    if existing is not None:
        flash(
            f"学生 [{student.sno}] {student.name} 已经选过课程 "
            f"[{course.code}] {course.name}，不能重复添加。",
            "error",
        )
        return redirect(url_for("score.course_detail", course_id=course.id))

    enrolled = _enrolled_count(course.id)
    if _capacity_reached(course, enrolled):
        flash(
            f"课程 [{course.code}] {course.name} 已满"
            f"（{enrolled}/{course.capacity}），无法再加入学生。",
            "error",
        )
        return redirect(url_for("score.course_detail", course_id=course.id))

    db.session.add(Enrollment(student_id=student.id, course_id=course.id))
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        flash(
            f"学生 [{student.sno}] {student.name} 已经选过课程 "
            f"[{course.code}] {course.name}，不能重复添加。",
            "error",
        )
        return redirect(url_for("score.course_detail", course_id=course.id))

    flash(
        f"已将学生 [{student.sno}] {student.name} 加入课程 [{course.code}] {course.name}。",
        "success",
    )
    return redirect(url_for("score.course_detail", course_id=course.id))


__all__ = ["bp"]
