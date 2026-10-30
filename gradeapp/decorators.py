"""视图装饰器与访问被拒响应（精简重构版）。"""
from __future__ import annotations

from collections.abc import Callable
from functools import wraps
from typing import Any, TypeVar

from flask import Response, flash, g, redirect, render_template, request, url_for

from .models import ROLES

F = TypeVar("F", bound=Callable[..., Any])

ROLE_LABELS: dict[str, str] = {"admin": "管理员", "teacher": "教师", "student": "学生"}


def role_label(role: str | None) -> str:
    """角色中文名；未知角色原样返回。"""
    return ROLE_LABELS.get(role or "", role or "未知角色")


def login_required(view: F) -> F:
    """要求当前会话已登录；未登录则跳转登录页，带上 ?next= 原地址。"""
    @wraps(view)
    def wrapped_view(*args: Any, **kwargs: Any) -> Any:
        if g.get("user") is None:
            flash("请先登录后再访问该页面。", "error")
            return redirect(url_for("auth.login", next=request.full_path.rstrip("?")))
        return view(*args, **kwargs)
    return wrapped_view  # type: ignore[return-value]


def role_required(*roles: str) -> Callable[[F], F]:
    """要求当前用户的角色在 roles 之内，否则渲染 403 页面。"""
    if unknown := [r for r in roles if r not in ROLES]:
        raise ValueError(f"未知角色：{unknown}；合法角色为 {list(ROLES)}")
    allowed = frozenset(roles)

    def decorator(view: F) -> F:
        @wraps(view)
        @login_required  # 直接复用 login_required 装饰器，消除未登录重定向逻辑重复
        def wrapped_view(*args: Any, **kwargs: Any) -> Any:
            if g.user.role not in allowed:
                return forbidden(required_roles=roles)
            return view(*args, **kwargs)
        return wrapped_view  # type: ignore[return-value]

    return decorator


def forbidden(
    required_roles: tuple[str, ...] | list[str] = (),
    *,
    message: str | None = None,
) -> tuple[str, int]:
    """渲染 403 页面并带上 HTTP 403 状态码。"""
    return (
        render_template(
            "errors/403.html",
            required_roles=tuple(required_roles),
            message=message,
            current_role_label=role_label(getattr(g.get("user"), "role", None)),
        ),
        403,
    )


def can_view_course(user: Any, course: Any) -> bool:
    """行级校验原语：当前用户是否有权查看这门课程。"""
    if not user or not course:
        return False
    if user.role == "admin":
        return True
    if user.role == "teacher":
        teacher = getattr(user, "teacher", None)
        return teacher is not None and course.teacher_id == teacher.id
    if user.role == "student":
        student = getattr(user, "student", None)
        return student is not None and any(e.course_id == course.id for e in student.enrollments)
    return False


def guard_course_access(course: Any) -> Response | tuple[str, int] | None:
    """行级校验快捷写法：无权访问时返回 403，有权则返回 None。"""
    if can_view_course(g.get("user"), course):
        return None
    return forbidden(message="这门课程不在你的权限范围内。")


__all__ = [
    "ROLE_LABELS",
    "can_view_course",
    "forbidden",
    "guard_course_access",
    "login_required",
    "role_label",
    "role_required",
]