"""管理员蓝图。

已实现功能：
1. /admin/                    —— 管理员首页仪表盘
2. /admin/users              —— 账号列表（按角色筛选、搜索、分页）
3. /admin/users/<id>/toggle   —— 停用/启用账号（POST + CSRF）
4. /admin/students           —— 学生列表与搜索（R4）
5. /admin/students/create    —— 新增学生与关联账号（R4）
6. /admin/students/<id>/edit  —— 编辑学生信息（R4）
7. /admin/students/<id>/delete—— 删除学生及关联账号（R4）
"""

from __future__ import annotations

from typing import Any

from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for
from flask_wtf import FlaskForm
from wtforms import IntegerField, PasswordField, SelectField, StringField
from wtforms.validators import DataRequired, Length, Optional, Regexp
from sqlalchemy import func, or_, select
from sqlalchemy.orm import selectinload

from .decorators import ROLE_LABELS, login_required, role_label, role_required
from .extensions import db
from .models import Course, Enrollment, Student, Teacher, User

bp = Blueprint("admin", __name__, url_prefix="/admin")

#: 列表每页条数
PER_PAGE = 10


# --------------------------------------------------------------------------- #
# 表单定义 (WTForms)
# --------------------------------------------------------------------------- #
class ActionForm(FlaskForm):
    """用于仅生成 csrf_token 的空表单（POST 动作防护）。"""


class StudentForm(FlaskForm):
    """学生信息新增/编辑表单。"""
    sno = StringField(
        "学号",
        validators=[
            DataRequired(message="学号不能为空"),
            Length(max=32, message="学号不能超过32位"),
        ],
    )
    name = StringField(
        "姓名",
        validators=[
            DataRequired(message="姓名不能为空"),
            Length(max=64, message="姓名不能超过64字"),
        ],
    )
    gender = SelectField(
        "性别",
        choices=[("", "未选择"), ("男", "男"), ("女", "女")],
        default="",
    )
    class_name = StringField("班级", validators=[Optional(), Length(max=64)])
    enroll_year = IntegerField("入学年份", validators=[Optional()])
    password = PasswordField(
        "初始密码",
        validators=[
            Optional(),
            Length(min=6, message="密码至少需要6个字符"),
        ],
    )


def _display_name(user: User) -> str:
    """账号对应的档案姓名。"""
    if user.role == "student" and user.student is not None:
        return user.student.name
    if user.role == "teacher" and user.teacher is not None:
        return user.teacher.name
    return user.real_name


def _profile_no(user: User) -> str:
    """学号 / 工号。"""
    if user.role == "student" and user.student is not None:
        return user.student.sno
    if user.role == "teacher" and user.teacher is not None:
        return user.teacher.tno
    return "—"


# --------------------------------------------------------------------------- #
# 管理员首页
# --------------------------------------------------------------------------- #
@bp.get("/")
@role_required("admin")
@login_required
def dashboard():
    """管理员首页。"""
    def count(model: Any) -> int:
        return int(db.session.scalar(select(func.count()).select_from(model)) or 0)

    role_rows = db.session.execute(
        select(User.role, func.count()).group_by(User.role)
    ).all()
    role_counts = {role: int(total) for role, total in role_rows}

    stats = {
        "user": count(User),
        "active_user": int(
            db.session.scalar(
                select(func.count()).select_from(User).where(User.is_active.is_(True))
            )
            or 0
        ),
        "student": count(Student),
        "teacher": count(Teacher),
        "course": count(Course),
        "enrollment": count(Enrollment),
    }
    recent = db.session.scalars(
        select(User).order_by(User.id.desc()).limit(5)
    ).all()

    return render_template(
        "admin/dashboard.html",
        stats=stats,
        role_counts=role_counts,
        role_labels=ROLE_LABELS,
        recent=recent,
        display_name=_display_name,
    )


# --------------------------------------------------------------------------- #
# 账号管理
# --------------------------------------------------------------------------- #
@bp.get("/users")
@role_required("admin")
@login_required
def user_list():
    """账号列表。"""
    role = (request.args.get("role") or "").strip()
    keyword = (request.args.get("q") or "").strip()
    page = request.args.get("page", 1, type=int)
    page = max(page, 1)

    stmt = select(User)
    if role in ROLE_LABELS:
        stmt = stmt.where(User.role == role)
    else:
        role = ""

    if keyword:
        like = f"%{keyword}%"
        stmt = stmt.where(or_(User.username.like(like), User.real_name.like(like)))

    total = int(
        db.session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    )
    pages = max((total + PER_PAGE - 1) // PER_PAGE, 1)
    page = min(page, pages)

    users = db.session.scalars(
        stmt.options(selectinload(User.student), selectinload(User.teacher))
        .order_by(User.role, User.id)
        .offset((page - 1) * PER_PAGE)
        .limit(PER_PAGE)
    ).all()

    return render_template(
        "admin/user_list.html",
        users=users,
        role=role,
        keyword=keyword,
        page=page,
        pages=pages,
        total=total,
        per_page=PER_PAGE,
        role_labels=ROLE_LABELS,
        display_name=_display_name,
        profile_no=_profile_no,
        toggle_form=ActionForm(),
    )


@bp.post("/users/<int:user_id>/toggle")
@role_required("admin")
@login_required
def toggle_user(user_id: int):
    """停用 / 启用账号。"""
    user = db.session.get(User, user_id)
    if user is None:
        abort(404)

    if user.is_active:
        reason = user.deactivation_blocker(actor=g.user)
        if reason is not None:
            flash(reason, "error")
            return redirect(url_for("admin.user_list", role=user.role or None))
        user.is_active = False
        db.session.commit()
        flash(f"已停用账号 {user.username}（{role_label(user.role)}）。", "success")
    else:
        user.is_active = True
        db.session.commit()
        flash(f"已启用账号 {user.username}（{role_label(user.role)}）。", "success")

    return redirect(url_for("admin.user_list", role=user.role or None))


# --------------------------------------------------------------------------- #
# 学生管理（R4 扩展：增删改查）
# --------------------------------------------------------------------------- #
@bp.get("/students")
@role_required("admin")
@login_required
def student_list():
    """学生列表：支持按学号/姓名/班级搜索和分页。"""
    keyword = (request.args.get("q") or "").strip()
    page = max(request.args.get("page", 1, type=int), 1)

    stmt = select(Student).join(Student.user)
    if keyword:
        like = f"%{keyword}%"
        stmt = stmt.where(
            or_(
                Student.sno.like(like),
                Student.name.like(like),
                Student.class_name.like(like),
            )
        )

    total = int(db.session.scalar(select(func.count()).select_from(stmt.subquery())) or 0)
    pages = max((total + PER_PAGE - 1) // PER_PAGE, 1)
    page = min(page, pages)

    students = db.session.scalars(
        stmt.options(selectinload(Student.user))
        .order_by(Student.sno)
        .offset((page - 1) * PER_PAGE)
        .limit(PER_PAGE)
    ).all()

    return render_template(
        "admin/student_list.html",
        students=students,
        keyword=keyword,
        page=page,
        pages=pages,
        total=total,
        action_form=ActionForm(),
    )


@bp.route("/students/create", methods=["GET", "POST"])
@role_required("admin")
@login_required
def student_create():
    """新增学生：自动建立关联的 User 登录账号。"""
    form = StudentForm()
    if form.validate_on_submit():
        sno = form.sno.data.strip()
        
        # 1. 唯一性检查（学号和用户名）
        existing_sno = db.session.scalar(select(Student).where(Student.sno == sno))
        existing_user = db.session.scalar(select(User).where(User.username == sno))
        if existing_sno or existing_user:
            flash(f"学号或用户名 '{sno}' 已存在！", "error")
            return render_template("admin/student_form.html", form=form, title="新增学生")

        # 2. 创建关联 User 账号
        user = User(
            username=sno,
            real_name=form.name.data.strip(),
            role="student",
            is_active=True,
        )
        raw_pwd = form.password.data or "123456"  # 未填则赋予默认密码
        user.set_password(raw_pwd)  # 安全哈希存储
        db.session.add(user)
        db.session.flush()  # 获取 user.id

        # 3. 创建 Student 档案
        student = Student(
            user_id=user.id,
            sno=sno,
            name=form.name.data.strip(),
            gender=form.gender.data or None,
            class_name=form.class_name.data.strip() if form.class_name.data else None,
            enroll_year=form.enroll_year.data,
        )
        db.session.add(student)
        db.session.commit()

        flash(f"学生 [{student.sno}] {student.name} 创建成功！（初始密码: {raw_pwd}）", "success")
        return redirect(url_for("admin.student_list"))

    return render_template("admin/student_form.html", form=form, title="新增学生")


@bp.route("/students/<int:student_id>/edit", methods=["GET", "POST"])
@role_required("admin")
@login_required
def student_edit(student_id: int):
    """编辑学生信息及同步更新对应账号信息。"""
    student = db.session.get(Student, student_id)
    if student is None:
        abort(404)

    form = StudentForm(obj=student)

    if form.validate_on_submit():
        new_sno = form.sno.data.strip()

        # 如果修改了学号，需检查是否与其他学生冲撞
        if new_sno != student.sno:
            conflict_sno = db.session.scalar(
                select(Student).where(Student.sno == new_sno, Student.id != student.id)
            )
            conflict_user = db.session.scalar(
                select(User).where(User.username == new_sno, User.id != student.user_id)
            )
            if conflict_sno or conflict_user:
                flash(f"学号或用户名 '{new_sno}' 已被其他账号占用！", "error")
                return render_template("admin/student_form.html", form=form, title="编辑学生", student=student)

        # 更新档案
        student.sno = new_sno
        student.name = form.name.data.strip()
        student.gender = form.gender.data or None
        student.class_name = form.class_name.data.strip() if form.class_name.data else None
        student.enroll_year = form.enroll_year.data

        # 同步更新账号
        student.user.username = new_sno
        student.user.real_name = student.name
        if form.password.data:  # 若提供了新密码则重置
            student.user.set_password(form.password.data)

        db.session.commit()
        flash(f"学生 [{student.sno}] {student.name} 信息更新成功！", "success")
        return redirect(url_for("admin.student_list"))

    return render_template("admin/student_form.html", form=form, title="编辑学生", student=student)


@bp.post("/students/<int:student_id>/delete")
@role_required("admin")
@login_required
def student_delete(student_id: int):
    """删除学生及其关联账号。"""
    student = db.session.get(Student, student_id)
    if student is None:
        abort(404)

    name = student.name
    sno = student.sno
    user = student.user

    # 直接删除 User，对应的 Student、Enrollment、Score 将触发级联删除
    db.session.delete(user)
    db.session.commit()

    flash(f"已删除学生 [{sno}] {name} 及其关联账号。", "success")
    return redirect(url_for("admin.student_list"))


__all__ = ["bp"]