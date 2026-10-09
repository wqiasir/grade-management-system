"""导航菜单：按角色生成，服务端与模板共用一份定义。

对应交付物"导航栏按角色渲染"。菜单项按端点是否存在过滤，
所以在还没有 report / 后续蓝图的阶段也不会出现死链：

    - 始终显示：首页
    - admin：账号管理（/admin/users）、账号总览（/admin/）、学生管理（/admin/students）
    - teacher / student：我的课程（/score/my-courses）
    - admin / teacher / student：统计报表（/report/overview）

> 只靠这里隐藏菜单不算权限控制。每个视图上仍有 @role_required 与行级校验，
> 直接敲 URL 一样会被 403 挡住（见 tests/test_permissions.py）。
"""

from __future__ import annotations

from typing import Any

from flask import url_for
from werkzeug.routing import BuildError

#: 单个菜单项：``endpoint`` 为 None 表示"下一轮才实现"的灰显占位项
MENU_ITEMS: tuple[dict[str, Any], ...] = (
    {"key": "home", "label": "首页", "endpoint": "index", "roles": (), "pending": None},
    {
        "key": "admin_users",
        "label": "账号管理",
        "endpoint": "admin.user_list",
        "roles": ("admin",),
    },
    {
        "key": "admin_home",
        "label": "账号总览",
        "endpoint": "admin.dashboard",
        "roles": ("admin",),
    },
    {
        "key": "students",
        "label": "学生管理",
        "endpoint": "admin.student_list",
        "roles": ("admin",),
    },
    {
        "key": "my_courses",
        "label": "我的课程",
        "endpoint": "score.my_courses",
        "roles": ("teacher", "student"),
    },
    {
        "key": "report",
        "label": "统计报表",
        "endpoint": "report.overview",
        "roles": ("admin", "teacher", "student"),
    },
    # ---- 以下为后续轮次的占位项：没有端点，灰显且不可点击 ----
    {"key": "teachers", "label": "教师与课程", "endpoint": None, "roles": ("admin",), "pending": "R5"},
    {"key": "enroll", "label": "选课", "endpoint": None, "roles": ("student",), "pending": "R6"},
    {"key": "grade_entry", "label": "成绩录入", "endpoint": None, "roles": ("teacher",), "pending": "R7"},
    {"key": "my_scores", "label": "我的成绩", "endpoint": None, "roles": ("student",), "pending": "R8"},
    {"key": "excel", "label": "Excel 导入导出", "endpoint": None, "roles": ("admin",), "pending": "R10"},
)


def endpoint_exists(endpoint: str) -> bool:
    """端点是否已注册（用于过滤尚未实现的菜单项，避免死链）。

    只捕获 ``BuildError``（"端点不存在"就是这一种）；其他异常照常抛出，
    免得把真实的编程错误也悄悄吞掉。
    """
    try:
        url_for(endpoint)
    except BuildError:
        return False
    return True


def menu_for_user(user: Any | None) -> list[dict[str, Any]]:
    """返回当前用户可见的菜单项列表；未登录时只有"首页"。

    每一项都是渲染好的 ``{"key", "label", "url" 或 None, "pending", "active"}``：
    ``url`` 为 ``None`` 表示灰显占位（对应 ``pending`` 轮次）。
    """
    items: list[dict[str, Any]] = []
    for item in MENU_ITEMS:
        roles = item.get("roles") or ()
        if user is None:
            if roles:
                continue
        elif user.role not in roles:
            continue

        endpoint = item.get("endpoint")
        # 端点必须"存在且已注册"才生成链接，否则退化为灰显占位（不出死链）
        if endpoint is not None and endpoint_exists(endpoint):
            url = url_for(endpoint)
        else:
            url = None

        items.append(
            {
                "key": item["key"],
                "label": item["label"],
                "url": url,
                "pending": item.get("pending"),
            }
        )
    return items


__all__ = ["MENU_ITEMS", "endpoint_exists", "menu_for_user"]