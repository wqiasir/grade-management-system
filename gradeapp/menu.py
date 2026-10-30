"""导航菜单：按角色生成，服务端与模板共用一份定义。"""
from __future__ import annotations

from typing import Any
from flask import url_for
from werkzeug.routing import BuildError

#: 单个菜单项：``endpoint`` 为 None 表示"下一轮才实现"的灰显占位项
MENU_ITEMS: tuple[dict[str, Any], ...] = (
    {"key": "home", "label": "首页", "endpoint": "index", "roles": (), "pending": None},
    {"key": "admin_users", "label": "账号管理", "endpoint": "admin.user_list", "roles": ("admin",)},
    {"key": "admin_home", "label": "账号总览", "endpoint": "admin.dashboard", "roles": ("admin",)},
    {"key": "students", "label": "学生管理", "endpoint": "admin.student_list", "roles": ("admin",)},
    {"key": "teachers", "label": "教师管理", "endpoint": "admin.teacher_list", "roles": ("admin",)},
    {"key": "courses", "label": "课程管理", "endpoint": "admin.course_list", "roles": ("admin",)},
    {"key": "rosters", "label": "选课名单", "endpoint": "score.my_courses", "roles": ("admin",)},
    {"key": "enroll", "label": "选课", "endpoint": "score.enroll_courses", "roles": ("student",)},
    {"key": "my_courses", "label": "我的课程", "endpoint": "score.my_courses", "roles": ("teacher", "student")},
    {"key": "report", "label": "统计报表", "endpoint": "report.overview", "roles": ("admin", "teacher", "student")},
    # ---- 以下为后续轮次的占位项：没有端点，灰显且不可点击 ----
    {"key": "grade_entry", "label": "成绩录入", "endpoint": None, "roles": ("teacher",), "pending": "R7"},
    {"key": "my_scores", "label": "我的成绩", "endpoint": None, "roles": ("student",), "pending": "R8"},
    {"key": "excel", "label": "Excel 导入导出", "endpoint": None, "roles": ("admin",), "pending": "R10"},
)


def endpoint_exists(endpoint: str) -> bool:
    """端点是否已注册（防止死链）。"""
    try:
        url_for(endpoint)
        return True
    except BuildError:
        return False


def menu_for_user(user: Any | None) -> list[dict[str, Any]]:
    """返回当前用户可见的菜单项列表。"""
    user_role = getattr(user, "role", None)
    items = []

    for item in MENU_ITEMS:
        roles = item.get("roles", ())
        # 如果菜单项指定了角色，但用户未登录，或者用户的角色不在允许列表中，则跳过
        if roles and (user is None or user_role not in roles):
            continue

        endpoint = item.get("endpoint")
        url = url_for(endpoint) if endpoint and endpoint_exists(endpoint) else None

        items.append({
            "key": item["key"],
            "label": item["label"],
            "url": url,
            "pending": item.get("pending"),
        })

    return items


__all__ = ["MENU_ITEMS", "endpoint_exists", "menu_for_user"]