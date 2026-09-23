"""视图装饰器。

R2 交付：``@login_required`` —— 未登录访问受保护视图时跳转登录页。
R3 将在本模块补 ``@role_required(*roles)``（角色鉴权），与第 6 节权限矩阵对应。

约定（重要）：装饰器只负责"拦不拦得住"，
**"这条数据是不是他自己的"必须在每个视图内做行级校验**，仅靠装饰器不算权限控制。
"""

from __future__ import annotations

from collections.abc import Callable
from functools import wraps
from typing import Any, TypeVar

from flask import flash, g, redirect, request, url_for

F = TypeVar("F", bound=Callable[..., Any])


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


__all__ = ["login_required"]
