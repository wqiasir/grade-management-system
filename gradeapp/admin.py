"""管理员蓝图（R3 起）。

R3 交付（对应第 6 节权限矩阵的"用户账号管理"一行）：
1. ``/admin/``            —— 管理员首页仪表盘（按角色分流的首页之一）
2. ``/admin/users``       —— 账号列表（按角色筛选、按用户名/姓名搜索、分页）
3. ``/admin/users/<id>/toggle`` —— 停用 / 启用账号（POST + CSRF）

**为什么 R3 先做"账号管理"这一块**：权限矩阵里管理员独占的第一项就是
"用户账号管理"，它天然需要 403 保护，正好用来验证 RBAC 真的在服务端生效。
其余管理功能按计划在后续轮次补：
  - R4 学生信息管理（增删改查）
  - R5 教师与课程管理（增删改查）
"""

from __future__ import annotations

from typing import Any

from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for
from flask_wtf import FlaskForm
from sqlalchemy import func, or_, select
from sqlalchemy.orm import selectinload

from .decorators import ROLE_LABELS, login_required, role_label, role_required
from .extensions import db
from .models import Course, Enrollment, Student, Teacher, User

bp = Blueprint("admin", __name__, url_prefix="/admin")

#: 账号列表每页条数
PER_PAGE = 10


class ActionForm(FlaskForm):
    """只用来在模板里生成 ``csrf_token`` 的空表单（停用 / 启用按钮走 POST）。"""


def _display_name(user: User) -> str:
    """账号对应的档案姓名：学生看 student.name，教师看 teacher.name，管理员只有 real_name。"""
    if user.role == "student" and user.student is not None:
        return user.student.name
    if user.role == "teacher" and user.teacher is not None:
        return user.teacher.name
    return user.real_name


def _profile_no(user: User) -> str:
    """学号 / 工号，管理员没有。"""
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
    """管理员首页：账号与基础数据的整体情况。"""

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
# 账号列表
# --------------------------------------------------------------------------- #
@bp.get("/users")
@role_required("admin")
@login_required
def user_list():
    """账号列表：支持按角色筛选、按用户名/姓名搜索、分页。"""
    role = (request.args.get("role") or "").strip()
    keyword = (request.args.get("q") or "").strip()
    page = request.args.get("page", 1, type=int)
    page = max(page, 1)

    stmt = select(User)
    if role in ROLE_LABELS:
        stmt = stmt.where(User.role == role)
    else:
        role = ""  # 非法角色值一律当作"不筛选"，避免拼出奇怪的查询
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
    """停用 / 启用账号。服务端校验"不能停用自己、不能停用最后一个管理员"。"""
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


__all__ = ["bp"]
