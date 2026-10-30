"""管理员蓝图"""
from __future__ import annotations

from typing import Any
from datetime import datetime
from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for
from flask_wtf import FlaskForm
from wtforms import FloatField, IntegerField, PasswordField, SelectField, StringField
from wtforms.validators import DataRequired, InputRequired, Length, NumberRange, Optional, Regexp
from sqlalchemy import func, or_, select
from sqlalchemy.orm import selectinload

from .decorators import ROLE_LABELS, login_required, role_label, role_required
from .extensions import db
from .models import Course, Enrollment, Student, Teacher, User

bp = Blueprint("admin", __name__, url_prefix="/admin")
PER_PAGE = 10

# --------------------------------------------------------------------------- #
# 1. Blueprint 级统一鉴权（替代所有路由上的重复装饰器）
# --------------------------------------------------------------------------- #
@bp.before_request
@login_required
@role_required("admin")
def before_request():
    pass


# --------------------------------------------------------------------------- #
# 2. 公共工具函数（消除分页与档案解析冗余）
# --------------------------------------------------------------------------- #
def _paginate(stmt) -> tuple[int, int, int]:
    """计算分页：返回 (page, pages, total)"""
    page = max(request.args.get("page", 1, type=int), 1)
    total = int(db.session.scalar(select(func.count()).select_from(stmt.subquery())) or 0)
    pages = max((total + PER_PAGE - 1) // PER_PAGE, 1)
    return min(page, pages), pages, total


def _display_name(user: User) -> str:
    return user.student.name if user.role == "student" and user.student else \
           (user.teacher.name if user.role == "teacher" and user.teacher else user.real_name)


def _profile_no(user: User) -> str:
    return user.student.sno if user.role == "student" and user.student else \
           (user.teacher.tno if user.role == "teacher" and user.teacher else "—")


# --------------------------------------------------------------------------- #
# 表单定义 (WTForms)
# --------------------------------------------------------------------------- #
class ActionForm(FlaskForm):
    """仅生成 csrf_token 的空表单"""

class StudentForm(FlaskForm):
    sno = StringField("学号", validators=[DataRequired("学号不能为空"), Length(max=32)])
    name = StringField("姓名", validators=[DataRequired("姓名不能为空"), Length(max=64)])
    gender = SelectField("性别", choices=[("", "未选择"), ("男", "男"), ("女", "女")], default="")
    class_name = StringField("班级", validators=[Optional(), Length(max=64)])
    enroll_year = IntegerField("入学年份", validators=[Optional()], default=datetime.now().year)
    password = PasswordField("初始密码", validators=[Optional(), Length(min=6, message="密码至少需要6个字符")])

class TeacherForm(FlaskForm):
    tno = StringField("工号", validators=[DataRequired("工号不能为空"), Length(max=32)])
    name = StringField("姓名", validators=[DataRequired("姓名不能为空"), Length(max=64)])
    title = StringField("职称", validators=[Optional(), Length(max=32)])
    department = StringField("所在学院", validators=[Optional(), Length(max=64)])
    password = PasswordField("初始密码", validators=[Optional(), Length(min=6, message="密码至少需要6个字符")])

class CourseForm(FlaskForm):
    code = StringField("课程代码", validators=[DataRequired("课程代码不能为空"), Length(max=32)])
    name = StringField("课程名称", validators=[DataRequired("课程名称不能为空"), Length(max=128)])
    credit = FloatField("学分", validators=[DataRequired("学分不能为空"), NumberRange(0.5, 20)])
    hours = IntegerField("学时", validators=[DataRequired("学时不能为空"), NumberRange(1, 999)])
    semester = StringField("开课学期", validators=[DataRequired("开课学期不能为空"), Length(max=32), Regexp(r"^\d{4}-\d{4}-\d{1,2}$", message="格式如 2025-2026-1")])
    capacity = IntegerField("容量", validators=[InputRequired("容量不能为空"), NumberRange(0, 10000)])
    teacher_id = SelectField("授课教师", coerce=int, choices=[], validators=[Optional()])


# --------------------------------------------------------------------------- #
# 管理员首页
# --------------------------------------------------------------------------- #
@bp.get("/")
def dashboard():
    count = lambda m: int(db.session.scalar(select(func.count()).select_from(m)) or 0)
    role_counts = {role: int(total) for role, total in db.session.execute(select(User.role, func.count()).group_by(User.role)).all()}
    
    stats = {
        "user": count(User), "active_user": int(db.session.scalar(select(func.count()).select_from(User).where(User.is_active.is_(True))) or 0),
        "student": count(Student), "teacher": count(Teacher), "course": count(Course), "enrollment": count(Enrollment)
    }
    recent = db.session.scalars(select(User).order_by(User.id.desc()).limit(5)).all()
    return render_template("admin/dashboard.html", stats=stats, role_counts=role_counts, role_labels=ROLE_LABELS, recent=recent, display_name=_display_name)


# --------------------------------------------------------------------------- #
# 账号管理
# --------------------------------------------------------------------------- #
@bp.get("/users")
def user_list():
    role = request.args.get("role", "").strip()
    keyword = request.args.get("q", "").strip()

    stmt = select(User)
    if role in ROLE_LABELS: stmt = stmt.where(User.role == role)
    else: role = ""
    if keyword: stmt = stmt.where(or_(User.username.like(f"%{keyword}%"), User.real_name.like(f"%{keyword}%")))

    page, pages, total = _paginate(stmt)
    users = db.session.scalars(stmt.options(selectinload(User.student), selectinload(User.teacher)).order_by(User.role, User.id).offset((page - 1) * PER_PAGE).limit(PER_PAGE)).all()

    return render_template("admin/user_list.html", users=users, role=role, keyword=keyword, page=page, pages=pages, total=total, per_page=PER_PAGE, role_labels=ROLE_LABELS, display_name=_display_name, profile_no=_profile_no, toggle_form=ActionForm())


@bp.post("/users/<int:user_id>/toggle")
def toggle_user(user_id: int):
    # 【已修改】去掉了多余的 .session
    user = db.get_or_404(User, user_id)
    if user.is_active and (reason := user.deactivation_blocker(actor=g.user)):
        flash(reason, "error")
    else:
        user.is_active = not user.is_active
        db.session.commit()
        status = "启用" if user.is_active else "停用"
        flash(f"已{status}账号 {user.username}（{role_label(user.role)}）。", "success")
    return redirect(url_for("admin.user_list", role=user.role or None))


# --------------------------------------------------------------------------- #
# 学生管理
# --------------------------------------------------------------------------- #
@bp.get("/students")
def student_list():
    keyword = request.args.get("q", "").strip()
    stmt = select(Student).join(Student.user)
    if keyword:
        stmt = stmt.where(or_(Student.sno.like(f"%{keyword}%"), Student.name.like(f"%{keyword}%"), Student.class_name.like(f"%{keyword}%")))
    
    page, pages, total = _paginate(stmt)
    students = db.session.scalars(stmt.options(selectinload(Student.user)).order_by(Student.sno).offset((page - 1) * PER_PAGE).limit(PER_PAGE)).all()
    return render_template("admin/student_list.html", students=students, keyword=keyword, page=page, pages=pages, total=total, action_form=ActionForm())


@bp.route("/students/create", methods=["GET", "POST"])
def student_create():
    form = StudentForm()
    if form.validate_on_submit():
        sno = form.sno.data.strip()
        if db.session.scalar(select(Student).where(Student.sno == sno)) or db.session.scalar(select(User).where(User.username == sno)):
            flash(f"学号或用户名 '{sno}' 已存在！", "error")
        else:
            user = User(username=sno, real_name=form.name.data.strip(), role="student", is_active=True)
            raw_pwd = form.password.data or "123456"
            user.set_password(raw_pwd)
            db.session.add(user)
            db.session.flush()

            student = Student(user_id=user.id, sno=sno, name=user.real_name, gender=form.gender.data or None, class_name=form.class_name.data.strip() or None, enroll_year=form.enroll_year.data)
            db.session.add(student)
            db.session.commit()
            flash(f"学生 [{sno}] {user.real_name} 创建成功！（初始密码: {raw_pwd}）", "success")
            return redirect(url_for("admin.student_list"))
            
    return render_template("admin/student_form.html", form=form, title="新增学生")


@bp.route("/students/<int:student_id>/edit", methods=["GET", "POST"])
def student_edit(student_id: int):
    student = db.get_or_404(Student, student_id)
    form = StudentForm(obj=student)
    if form.validate_on_submit():
        new_sno = form.sno.data.strip()
        if new_sno != student.sno and (db.session.scalar(select(Student).where(Student.sno == new_sno, Student.id != student.id)) or db.session.scalar(select(User).where(User.username == new_sno, User.id != student.user_id))):
            flash(f"学号或用户名 '{new_sno}' 已被占用！", "error")
        else:
            student.sno = new_sno
            student.name = student.user.real_name = form.name.data.strip()
            student.gender = form.gender.data or None
            student.class_name = form.class_name.data.strip() or None
            student.enroll_year = form.enroll_year.data
            student.user.username = new_sno
            if form.password.data: student.user.set_password(form.password.data)
            
            db.session.commit()
            flash(f"学生 [{new_sno}] 信息更新成功！", "success")
            return redirect(url_for("admin.student_list"))
            
    return render_template("admin/student_form.html", form=form, title="编辑学生", student=student)


@bp.post("/students/<int:student_id>/delete")
def student_delete(student_id: int):
    student = db.get_or_404(Student, student_id)
    db.session.delete(student.user)  # 级联删除
    db.session.commit()
    flash(f"已删除学生 [{student.sno}] {student.name} 及其关联账号。", "success")
    return redirect(url_for("admin.student_list"))


# --------------------------------------------------------------------------- #
# 教师管理
# --------------------------------------------------------------------------- #
@bp.get("/teachers")
def teacher_list():
    keyword = request.args.get("q", "").strip()
    stmt = select(Teacher)
    if keyword:
        stmt = stmt.where(or_(Teacher.tno.like(f"%{keyword}%"), Teacher.name.like(f"%{keyword}%"), Teacher.title.like(f"%{keyword}%"), Teacher.department.like(f"%{keyword}%")))
    
    page, pages, total = _paginate(stmt)
    teachers = db.session.scalars(stmt.options(selectinload(Teacher.user)).order_by(Teacher.tno).offset((page - 1) * PER_PAGE).limit(PER_PAGE)).all()
    return render_template("admin/teacher_list.html", teachers=teachers, keyword=keyword, page=page, pages=pages, total=total, action_form=ActionForm())


@bp.route("/teachers/create", methods=["GET", "POST"])
def teacher_create():
    form = TeacherForm()
    if form.validate_on_submit():
        tno = form.tno.data.strip()
        if db.session.scalar(select(Teacher).where(Teacher.tno == tno)) or db.session.scalar(select(User).where(User.username == tno)):
            flash(f"工号或用户名 '{tno}' 已存在！", "error")
        else:
            user = User(username=tno, real_name=form.name.data.strip(), role="teacher", is_active=True)
            raw_pwd = form.password.data or "123456"
            user.set_password(raw_pwd)
            db.session.add(user)
            db.session.flush()

            teacher = Teacher(user_id=user.id, tno=tno, name=user.real_name, title=form.title.data.strip() or None, department=form.department.data.strip() or None)
            db.session.add(teacher)
            db.session.commit()
            flash(f"教师 [{tno}] {user.real_name} 创建成功！（初始密码: {raw_pwd}）", "success")
            return redirect(url_for("admin.teacher_list"))
            
    return render_template("admin/teacher_form.html", form=form, title="新增教师")


@bp.route("/teachers/<int:teacher_id>/edit", methods=["GET", "POST"])
def teacher_edit(teacher_id: int):
    # 【已修改】去掉了多余的 .session
    teacher = db.get_or_404(Teacher, teacher_id)
    form = TeacherForm(obj=teacher)
    if form.validate_on_submit():
        new_tno = form.tno.data.strip()
        if new_tno != teacher.tno and (db.session.scalar(select(Teacher).where(Teacher.tno == new_tno, Teacher.id != teacher.id)) or db.session.scalar(select(User).where(User.username == new_tno, User.id != teacher.user_id))):
            flash(f"工号或用户名 '{new_tno}' 已被占用！", "error")
        else:
            teacher.tno = new_tno
            teacher.name = teacher.user.real_name = form.name.data.strip()
            teacher.title = form.title.data.strip() or None
            teacher.department = form.department.data.strip() or None
            teacher.user.username = new_tno
            if form.password.data: teacher.user.set_password(form.password.data)
            
            db.session.commit()
            flash(f"教师 [{new_tno}] 信息更新成功！", "success")
            return redirect(url_for("admin.teacher_list"))
            
    return render_template("admin/teacher_form.html", form=form, title="编辑教师", teacher=teacher)


@bp.post("/teachers/<int:teacher_id>/delete")
def teacher_delete(teacher_id: int):
    teacher = db.get_or_404(Teacher, teacher_id)
    if course_count := int(db.session.scalar(select(func.count()).select_from(Course).where(Course.teacher_id == teacher.id)) or 0):
        flash(f"教师 [{teacher.tno}] 仍有 {course_count} 门授课课程，无法删除！", "error")
        return redirect(url_for("admin.teacher_list"))
        
    db.session.delete(teacher.user)
    db.session.commit()
    flash(f"已删除教师 [{teacher.tno}] {teacher.name} 及其关联账号。", "success")
    return redirect(url_for("admin.teacher_list"))


# --------------------------------------------------------------------------- #
# 课程管理
# --------------------------------------------------------------------------- #
def _teacher_choices() -> list[tuple[int, str]]:
    teachers = db.session.scalars(select(Teacher).order_by(Teacher.tno)).all()
    return [(0, "—— 未排课 ——")] + [(t.id, f"{t.name}（{t.tno}）") for t in teachers]


@bp.get("/courses")
def course_list():
    keyword = request.args.get("q", "").strip()
    stmt = select(Course)
    if keyword:
        stmt = stmt.where(or_(Course.code.like(f"%{keyword}%"), Course.name.like(f"%{keyword}%"), Course.semester.like(f"%{keyword}%")))
    
    page, pages, total = _paginate(stmt)
    courses = db.session.scalars(stmt.options(selectinload(Course.teacher), selectinload(Course.enrollments)).order_by(Course.code).offset((page - 1) * PER_PAGE).limit(PER_PAGE)).all()
    return render_template("admin/course_list.html", courses=courses, keyword=keyword, page=page, pages=pages, total=total, action_form=ActionForm())


@bp.route("/courses/create", methods=["GET", "POST"])
def course_create():
    form = CourseForm()
    form.teacher_id.choices = _teacher_choices()
    if form.validate_on_submit():
        code = form.code.data.strip()
        if db.session.scalar(select(Course).where(Course.code == code)):
            flash(f"课程代码 '{code}' 已存在！", "error")
        else:
            course = Course(code=code, name=form.name.data.strip(), credit=form.credit.data, hours=form.hours.data, teacher_id=form.teacher_id.data or None, semester=form.semester.data.strip(), capacity=form.capacity.data)
            db.session.add(course)
            db.session.commit()
            flash(f"课程 [{code}] 创建成功！", "success")
            return redirect(url_for("admin.course_list"))
            
    return render_template("admin/course_form.html", form=form, title="新增课程")


@bp.route("/courses/<int:course_id>/edit", methods=["GET", "POST"])
def course_edit(course_id: int):
    course = db.get_or_404(Course, course_id)
    form = CourseForm(obj=course)
    form.teacher_id.choices = _teacher_choices()
    if request.method == "GET":
        form.teacher_id.data = course.teacher_id or 0

    if form.validate_on_submit():
        new_code = form.code.data.strip()
        if new_code != course.code and db.session.scalar(select(Course).where(Course.code == new_code, Course.id != course.id)):
            flash(f"课程代码 '{new_code}' 已被占用！", "error")
        elif form.capacity.data > 0 and form.capacity.data < (enrolled := len(course.enrollments)):
            flash(f"容量不能小于当前已选人数（{enrolled} 人）！", "error")
        else:
            course.code = new_code
            course.name = form.name.data.strip()
            course.credit = form.credit.data
            course.hours = form.hours.data
            course.teacher_id = form.teacher_id.data or None
            course.semester = form.semester.data.strip()
            course.capacity = form.capacity.data
            
            db.session.commit()
            flash(f"课程 [{new_code}] 更新成功！", "success")
            return redirect(url_for("admin.course_list"))
            
    return render_template("admin/course_form.html", form=form, title="编辑课程", course=course)


@bp.post("/courses/<int:course_id>/delete")
def course_delete(course_id: int):
    course = db.get_or_404(Course, course_id)
    enrolled = len(course.enrollments)
    db.session.delete(course)
    db.session.commit()
    
    detail = f"及其 {enrolled} 条选课记录" if enrolled else ""
    flash(f"已删除课程 [{course.code}] {course.name}{detail}。", "success")
    return redirect(url_for("admin.course_list"))


__all__ = ["bp"]