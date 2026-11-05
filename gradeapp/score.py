"""选课与成绩蓝图（精简重构版）。"""
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
from .models import EXAM_TYPES, Course, Enrollment, Score, Student

bp = Blueprint("score", __name__, url_prefix="/score")


class ActionForm(FlaskForm):
    """仅生成 CSRF token 的空表单。"""


class RosterAddForm(FlaskForm):
    """管理员将学生加入课程表单。"""
    student_id = SelectField(
        "学生",
        coerce=int,
        validators=[DataRequired(message="请选择要加入课程的学生")],
        validate_choice=False,
    )


# --------------------------------------------------------------------------- #
# 通用查询与校验小工具
# --------------------------------------------------------------------------- #
def _enrolled_count(course_id: int) -> int:
    return int(db.session.scalar(select(func.count()).select_from(Enrollment).where(Enrollment.course_id == course_id)) or 0)


def _score_count(enrollment_id: int) -> int:
    return int(db.session.scalar(select(func.count()).select_from(Score).where(Score.enrollment_id == enrollment_id)) or 0)


def _capacity_reached(course: Course, enrolled: int) -> bool:
    return course.capacity > 0 and enrolled >= course.capacity


def _remaining_seats(course: Course, enrolled: int) -> int | None:
    return None if course.capacity <= 0 else max(course.capacity - enrolled, 0)


def _find_enrollment(student_id: int, course_id: int) -> Enrollment | None:
    return db.session.scalar(select(Enrollment).where(Enrollment.student_id == student_id, Enrollment.course_id == course_id))


def _safe_next(default: str) -> str:
    target = (request.form.get("next") or "").strip()
    parts = urlsplit(target)
    if target.startswith("/") and not target.startswith("//") and not parts.scheme and not parts.netloc and "\\" not in target:
        return target
    return default


def _addable_student_choices(course: Course) -> list[tuple[int, str]]:
    enrolled_ids = set(db.session.scalars(select(Enrollment.student_id).where(Enrollment.course_id == course.id)).all())
    students = db.session.scalars(select(Student).order_by(Student.sno)).all()
    return [(0, "—— 选择学生 ——")] + [(s.id, f"{s.name}（{s.sno}）") for s in students if s.id not in enrolled_ids]


# --------------------------------------------------------------------------- #
# 我的课程
# --------------------------------------------------------------------------- #
def _course_rows_for(user) -> list[dict]:
    """按角色取出"我的课程"，并附上选课人数与已录成绩条数。

    学生额外带 ``my_enrollment`` / ``my_score_count``，用于判断"能不能退课"；
    教师与管理员不需要这两个字段（它们为 ``None`` / 0）。
    """
    stmt = select(Course).options(selectinload(Course.teacher)).order_by(Course.semester, Course.code)

    if user.role == "teacher":
        if not user.teacher: return []
        stmt = stmt.where(Course.teacher_id == user.teacher.id)
    elif user.role == "student":
        if not user.student: return []
        stmt = stmt.join(Enrollment, Enrollment.course_id == Course.id).where(Enrollment.student_id == user.student.id)
    elif user.role != "admin":
        return []

    rows = []
    for course in db.session.scalars(stmt).unique().all():
        enrolled = _enrolled_count(course.id)
        graded = int(db.session.scalar(select(func.count()).select_from(Score).join(Enrollment, Score.enrollment_id == Enrollment.id).where(Enrollment.course_id == course.id)) or 0)

        my_enrollment, my_score_count = None, 0
        if user.role == "student" and user.student:
            if my_enrollment := _find_enrollment(user.student.id, course.id):
                my_score_count = _score_count(my_enrollment.id)

        rows.append({"course": course, "enrolled": enrolled, "graded": graded, "my_enrollment": my_enrollment, "my_score_count": my_score_count})

    return rows


@bp.get("/my-courses")
@role_required("admin", "teacher", "student")
@login_required
def my_courses():
    user = g.user
    return render_template("score/my_courses.html", rows=_course_rows_for(user), role_label=role_label(user.role), role_labels=ROLE_LABELS, action_form=ActionForm())


# --------------------------------------------------------------------------- #
# 学生选课与退课
# --------------------------------------------------------------------------- #
@bp.get("/enroll")
@role_required("student")
@login_required
def enroll_courses():
    keyword = (request.args.get("q") or "").strip()
    semester = (request.args.get("semester") or "").strip()
    semesters = list(db.session.scalars(select(Course.semester).distinct().order_by(Course.semester.desc())).all())

    stmt = select(Course).options(selectinload(Course.teacher)).order_by(Course.semester.desc(), Course.code)
    if keyword: stmt = stmt.where(or_(Course.code.like(f"%{keyword}%"), Course.name.like(f"%{keyword}%")))
    if semester in semesters: stmt = stmt.where(Course.semester == semester)
    else: semester = ""

    student = g.user.student
    my_enrollments = {e.course_id: e for e in db.session.scalars(select(Enrollment).where(Enrollment.student_id == student.id)).all()} if student else {}

    rows = []
    for course in db.session.scalars(stmt).all():
        enrolled = _enrolled_count(course.id)
        rows.append({
            "course": course, "enrolled": enrolled, "remaining": _remaining_seats(course, enrolled),
            "my_enrollment": my_enrollments.get(course.id), "is_full": _capacity_reached(course, enrolled)
        })

    return render_template("score/enroll_courses.html", rows=rows, keyword=keyword, semester=semester, semesters=semesters, student=student, selected_count=len(my_enrollments), action_form=ActionForm())


@bp.post("/enroll/<int:course_id>")
@role_required("student")
@login_required
def enroll(course_id: int):
    course = db.get_or_404(Course, course_id)
    student = g.user.student
    fallback = _safe_next(url_for("score.enroll_courses"))

    if not student:
        flash("当前账号没有关联的学生档案，无法选课。", "error")
        return redirect(fallback)

    if _find_enrollment(student.id, course.id):
        flash(f"你已经选过课程 [{course.code}] {course.name}，不能重复选课。", "error")
        return redirect(fallback)

    if _capacity_reached(course, _enrolled_count(course.id)):
        flash(f"课程 [{course.code}] {course.name} 已满，无法选课。", "error")
        return redirect(fallback)

    db.session.add(Enrollment(student_id=student.id, course_id=course.id))
    try:
        db.session.commit()
        flash(f"已选上课程 [{course.code}] {course.name}。", "success")
    except IntegrityError:
        db.session.rollback()
        flash(f"你已经选过课程 [{course.code}] {course.name}，不能重复选课。", "error")
    
    return redirect(fallback)


@bp.post("/enrollments/<int:enrollment_id>/drop")
@role_required("admin", "student")
@login_required
def drop_enrollment(enrollment_id: int):
    enrollment = db.get_or_404(Enrollment, enrollment_id)
    course = enrollment.course
    code, name = (course.code, course.name) if course else ("?", "?")

    if g.user.role == "student" and (not g.user.student or enrollment.student_id != g.user.student.id):
        return forbidden(message="只能退选你自己的课程。")

    return_url = _safe_next(url_for("score.course_detail", course_id=enrollment.course_id) if g.user.role == "admin" and enrollment.course_id else url_for("score.my_courses"))

    if _score_count(enrollment.id) > 0:
        flash(f"课程 [{code}] {name} 已有成绩，已出成绩的课程不允许退课。", "error")
        return redirect(return_url)

    db.session.delete(enrollment)
    db.session.commit()
    flash(f"已退选课程 [{code}] {name}。", "success")
    return redirect(return_url)


# --------------------------------------------------------------------------- #
# 课程详情与选课名单管理
# --------------------------------------------------------------------------- #
@bp.get("/courses/<int:course_id>")
@role_required("admin", "teacher", "student")
@login_required
def course_detail(course_id: int):
    course = db.get_or_404(Course, course_id)
    if denial := guard_course_access(course): return denial

    enrollments = db.session.scalars(select(Enrollment).options(selectinload(Enrollment.student)).where(Enrollment.course_id == course.id).order_by(Enrollment.student_id)).all()
    score_map, exam_scores = {}, {}
    for item in db.session.scalars(select(Score).join(Enrollment, Score.enrollment_id == Enrollment.id).where(Enrollment.course_id == course.id)).all():
        score_map.setdefault(item.enrollment_id, []).append(item)
        exam_scores.setdefault(item.enrollment_id, {})[item.exam_type] = item

    # R7 成绩录入：当前正在录入的考核类型（?exam= 切换，缺省为期末）
    grade_exam = (request.args.get("exam") or "期末").strip()
    if grade_exam not in EXAM_TYPES:
        grade_exam = "期末"

    my_enrollment_id = None
    if g.user.role == "student" and g.user.student:
        my_enrollment_id = next((e.id for e in enrollments if e.student_id == g.user.student.id), None)

    add_form = None
    if g.user.role == "admin":
        add_form = RosterAddForm()
        add_form.student_id.choices = _addable_student_choices(course)

    enrolled_count = len(enrollments)
    return render_template(
        "score/course_detail.html", course=course, enrollments=enrollments, score_map=score_map,
        exam_scores=exam_scores, grade_exam=grade_exam, exam_types=EXAM_TYPES,
        enrolled_count=enrolled_count, remaining=_remaining_seats(course, enrolled_count),
        my_enrollment_id=my_enrollment_id, add_form=add_form, action_form=ActionForm(),
        role_label=role_label(g.user.role), back_url=url_for("score.my_courses")
    )


@bp.post("/courses/<int:course_id>/enroll")
@role_required("admin")
@login_required
def roster_add(course_id: int):
    course = db.get_or_404(Course, course_id)
    form = RosterAddForm()
    form.student_id.choices = _addable_student_choices(course)

    if not form.validate_on_submit():
        message = "；".join(error for errors in form.errors.values() for error in errors)
        flash(message or "请选择要加入课程的学生。", "error")
        return redirect(url_for("score.course_detail", course_id=course.id))

    student = db.session.get(Student, form.student_id.data)
    if student is None:
        abort(404)

    if _find_enrollment(student.id, course.id):
        flash(f"学生 [{student.sno}] {student.name} 已经选过课程 [{course.code}] {course.name}，不能重复添加。", "error")
        return redirect(url_for("score.course_detail", course_id=course.id))

    if _capacity_reached(course, _enrolled_count(course.id)):
        flash(f"课程 [{course.code}] {course.name} 已满，无法添加。", "error")
        return redirect(url_for("score.course_detail", course_id=course.id))

    db.session.add(Enrollment(student_id=student.id, course_id=course.id))
    try:
        db.session.commit()
        flash(f"已将学生 [{student.sno}] {student.name} 加入课程。", "success")
    except IntegrityError:
        db.session.rollback()
        flash(f"学生已经选过该课程，不能重复添加。", "error")

    return redirect(url_for("score.course_detail", course_id=course.id))

# --------------------------------------------------------------------------- #
# 成绩查询（R8）：学生本人成绩单 + 管理员查任意学生
# --------------------------------------------------------------------------- #
def _transcript_groups_for(student_id: int) -> list[dict]:
    """一名学生的成绩单：按学期倒序分组的课程与各考核类型成绩。

    每行带 ``scores``（按 平时/期中/期末 排序的成绩列表）与 ``graded``（是否已出成绩）。
    """
    enrollments = db.session.scalars(
        select(Enrollment)
        .options(
            selectinload(Enrollment.course).selectinload(Course.teacher),
            selectinload(Enrollment.scores),
        )
        .join(Course, Enrollment.course_id == Course.id)
        .where(Enrollment.student_id == student_id)
        .order_by(Course.semester.desc(), Course.code)
    ).all()

    groups: dict[str, dict] = {}
    for e in enrollments:
        course = e.course
        group = groups.setdefault(course.semester, {"semester": course.semester, "rows": []})
        scores = sorted(
            e.scores,
            key=lambda s: EXAM_TYPES.index(s.exam_type) if s.exam_type in EXAM_TYPES else len(EXAM_TYPES),
        )
        group["rows"].append({"enrollment": e, "course": course, "scores": scores, "graded": bool(scores)})
    return [groups[key] for key in sorted(groups, reverse=True)]


def _render_transcript(student, back_url: str):
    """渲染成绩单模板（学生本人与管理员查询共用一份）。"""
    groups = _transcript_groups_for(student.id)
    course_total = sum(len(group["rows"]) for group in groups)
    graded_total = sum(1 for group in groups for row in group["rows"] if row["graded"])
    return render_template(
        "score/my_scores.html",
        student=student,
        groups=groups,
        course_total=course_total,
        graded_total=graded_total,
        exam_types=EXAM_TYPES,
        action_form=ActionForm(),
        role_label=role_label(g.user.role),
        back_url=back_url,
    )


@bp.get("/my-scores")
@role_required("student")
@login_required
def my_scores():
    """学生本人成绩单（R8）：按学期分组，仅本人（无参数可查别人）。"""
    student = g.user.student
    if not student:
        return render_template(
            "score/my_scores.html", student=None, groups=[], course_total=0, graded_total=0,
            exam_types=EXAM_TYPES, action_form=ActionForm(),
            role_label=role_label(g.user.role), back_url=url_for("score.my_courses"),
        )
    return _render_transcript(student, back_url=url_for("score.my_courses"))


@bp.get("/students/<int:student_id>/scores")
@role_required("admin")
@login_required
def student_scores(student_id: int):
    """管理员查看任意学生的成绩单（R8）；教师查自己课程走课程详情，学生仅可查本人。"""
    student = db.get_or_404(Student, student_id)
    return _render_transcript(student, back_url=url_for("admin.student_list"))


# --------------------------------------------------------------------------- #
# 教师成绩录入与管理（R7）
# --------------------------------------------------------------------------- #
@bp.post("/courses/<int:course_id>/scores")
@role_required("admin", "teacher")
@login_required
def scores_add(course_id: int):
    """批量录入 / 修改成绩。

    - 考核类型（平时 / 期中 / 期末）由表单下拉框指定，一次保存同一类型的一批分数；
    - 分数留空 = 该生该类型**不修改**（不会误删已有成绩）；
    - 数字格式与 0~100 范围在视图层校验（数据库 CHECK 约束兜底）；
      无效行跳过并逐条报告，其余照常保存；
    - ``updated_by`` 记录操作人，便于追溯谁改的分数。
    """
    course = db.get_or_404(Course, course_id)
    if denial := guard_course_access(course):
        return denial

    exam_type = (request.form.get("exam_type") or "").strip()
    if exam_type not in EXAM_TYPES:
        flash("考核类型不合法，请从下拉框中选择。", "error")
        return redirect(url_for("score.course_detail", course_id=course.id))

    enrollments = db.session.scalars(
        select(Enrollment).options(selectinload(Enrollment.student)).where(Enrollment.course_id == course.id)
    ).all()
    existing = {
        (s.enrollment_id, s.exam_type): s
        for s in db.session.scalars(
            select(Score).join(Enrollment, Score.enrollment_id == Enrollment.id).where(Enrollment.course_id == course.id)
        ).all()
    }

    saved, rejected = 0, []
    for enrollment in enrollments:
        raw = (request.form.get(f"score_{enrollment.id}") or "").strip()
        if not raw:
            continue  # 留空 = 不修改

        who = enrollment.student.name if enrollment.student else f"选课记录#{enrollment.id}"
        try:
            value = float(raw)
        except ValueError:
            rejected.append(f"{who}：'{raw}' 不是有效数字")
            continue
        if not (0 <= value <= 100):
            rejected.append(f"{who}：{value:g} 不在 0~100 范围内")
            continue

        record = existing.get((enrollment.id, exam_type))
        if record is None:
            db.session.add(Score(enrollment_id=enrollment.id, exam_type=exam_type, score=value, updated_by=g.user.id))
        else:
            record.score = value
            record.updated_by = g.user.id
        saved += 1

    db.session.commit()
    if rejected:
        flash(f"已保存 {saved} 条「{exam_type}」成绩；{len(rejected)} 条未保存：{'；'.join(rejected)}。", "error")
    else:
        flash(f"已保存 {saved} 条「{exam_type}」成绩。", "success")
    return redirect(url_for("score.course_detail", course_id=course.id, exam=exam_type))


__all__ = ["bp"]