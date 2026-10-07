"""视图装饰器与访问被拒响应。

R2 交付：``@login_required`` —— 未登录访问受保护视图时跳转登录页。
R3 交付：``@role_required(*roles)`` —— 角色鉴权 + 统一渲染 ``errors/403.html``。

约定（重要）：装饰器只负责"拦不拦得住"，
**"这条数据是不是他自己的"必须在每个视图内做行级校验**，仅靠装饰器不算权限控制。
例如 R7 的成绩录入，``@role_required("teacher")`` 只说明"是教师"，
"这门课是不是他教的"仍要在视图里查一次。R3 的 ``forbidden()`` 与 ``can_view_course()``
就是给后续轮次做行级校验准备的两个原语。
"""

from __future__ import annotations

from collections.abc import Callable
from functools import wraps
from typing import Any, TypeVar

from flask import Response, flash, g, redirect, render_template, request, url_for

from .models import ROLES

F = TypeVar("F", bound=Callable[..., Any])

#: 角色中文名（导航、403 页面、首页共用）
ROLE_LABELS: dict[str, str] = {"admin": "管理员", "teacher": "教师", "student": "学生"}


def role_label(role: str | None) -> str:
    """角色中文名；未知角色原样返回，便于发现数据问题。"""
    return ROLE_LABELS.get(role or "", role or "未知角色")


def login_required(view: F) -> F:
    """要求当前会话已登录；未登录则跳转登录页，并在 ``?next=`` 里带上原地址。

    依赖 ``gradeapp.auth`` 注册的 ``before_app_request`` 钩子把当前用户放入 ``g.user``。
    """

    @wraps(view)
    def wrapped_view(*args: Any, **kwargs: Any) -> Any:
        if g.get("user") is None:
            flash("请先登录后再访问该页面。", "error")
            # 保留完整路径与查询串，登录成功后回到原处
            return redirect(url_for("auth.login", next=request.full_path.rstrip("?")))
        return view(*args, **kwargs)

    return wrapped_view  # type: ignore[return-value]


def role_required(*roles: str) -> Callable[[F], F]:
    """要求当前用户的角色在 ``roles`` 之内，否则渲染 403 页面。

    覆盖第 6 节权限矩阵的"角色维度"：管理员专属功能传 ``"admin"``，
    教师与学生都可访问的功能传 ``"teacher", "student"``。

    行为：
    - 未登录（``g.user`` 为空）→ 与 ``@login_required`` 一致，跳登录页；
    - 已登录但角色不符 → 返回 **403** 并渲染 ``errors/403.html``（不是 404，也不是静默跳转）。

    与 ``@login_required`` 的使用顺序：**``@role_required`` 放外层**，
    这样未登录用户得到的是"跳登录页"而不是 403：

        @bp.route("/admin/users")
        @role_required("admin")
        @login_required
        def user_list(): ...
    """
    unknown = [role for role in roles if role not in ROLES]
    if unknown:
        # 写错角色名时立刻报错，而不是变成"谁都进不去"的隐藏权限漏洞
        raise ValueError(f"未知角色：{unknown}；合法角色为 {list(ROLES)}")
    allowed = frozenset(roles)

    def decorator(view: F) -> F:
        @wraps(view)
        def wrapped_view(*args: Any, **kwargs: Any) -> Any:
            user = g.get("user")
            if user is None:
                flash("请先登录后再访问该页面。", "error")
                return redirect(url_for("auth.login", next=request.full_path.rstrip("?")))
            if user.role not in allowed:
                return forbidden(required_roles=roles)
            return view(*args, **kwargs)

        return wrapped_view  # type: ignore[return-value]

    return decorator


def forbidden(
    required_roles: tuple[str, ...] | list[str] = (),
    *,
    message: str | None = None,
) -> tuple[str, int]:
    """渲染 403 页面并带上 HTTP 403 状态码。

    视图内做行级校验失败时（例如"不是自己教的课"）也调用本函数，
    保证被拒的响应与装饰器拦截的响应完全一致。
    """
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
    """行级校验原语：当前用户是否有权查看这门课程。

    - admin：全部课程；
    - teacher：仅自己授课的课程；
    - student：仅自己已选的课程。

    后续轮次（R6 选课 / R7 成绩录入 / R8 成绩查询）统一复用它，
    避免每个视图各写一套"是不是他的"判断而产生权限漏洞。
    """
    if user is None or course is None:
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
    """行级校验的快捷写法：无权访问时直接返回 403 响应，有权则返回 ``None``。

    视图里这样用：

        denial = guard_course_access(course)
        if denial is not None:
            return denial
    """
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
