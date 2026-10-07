"""R3 验证：角色权限控制（RBAC）—— 权限矩阵逐条覆盖。

对应第 7 节 R3 的完成标准：**权限矩阵测试全绿（每角色 × 每受限路由）**。

测试策略：
1. 用一张"路由 × 角色 → 期望响应"的矩阵表驱动 ``test_permission_matrix``，
   每一格都要么 200、要么 403，**不允许出现"菜单里没有但 URL 能进"**的情况；
2. 未登录访问受限路由一律 302 跳登录页并带 ``?next=``；
3. 行级校验（"是不是自己教的课"）单独覆盖：403 而不是 404；
4. 被拒的写操作必须**没有副作用**（不落库、不闪现成功提示）。

路由清单与权限矩阵（第 6 节）的对应关系见 ``ROUTES`` 的注释。
"""

from __future__ import annotations

import pytest
from flask import Flask
from flask.testing import FlaskClient

from gradeapp import decorators
from gradeapp.extensions import db
from gradeapp.models import Course, Enrollment, Score, Student, Teacher, User

PASSWORD = "pw-123456"


# --------------------------------------------------------------------------- #
# 辅助：造数据与登录
# --------------------------------------------------------------------------- #
def make_user(
    username: str,
    role: str,
    *,
    real_name: str | None = None,
    is_active: bool = True,
) -> User:
    user = User(
        username=username,
        role=role,
        real_name=real_name or username,
        is_active=is_active,
    )
    user.set_password(PASSWORD)
    db.session.add(user)
    db.session.commit()
    return user


def make_student(username: str = "stu1", *, sno: str | None = None) -> Student:
    user = make_user(username, "student", real_name="学生" + username)
    student = Student(
        user_id=user.id,
        sno=sno or f"S{user.id:04d}",
        name=user.real_name,
        gender="女",
        class_name="计算机2501",
        enroll_year=2025,
    )
    db.session.add(student)
    db.session.commit()
    return student


def make_teacher(username: str = "tea1", *, tno: str | None = None) -> Teacher:
    user = make_user(username, "teacher", real_name="教师" + username)
    teacher = Teacher(
        user_id=user.id,
        tno=tno or f"T{user.id:04d}",
        name=user.real_name,
        title="讲师",
        department="计算机学院",
    )
    db.session.add(teacher)
    db.session.commit()
    return teacher


def make_course(
    teacher: Teacher | None,
    code: str = "C001",
    *,
    name: str = "课程",
    semester: str = "2025-2026-1",
    capacity: int = 60,
) -> Course:
    course = Course(
        code=code,
        name=name,
        credit=3.0,
        hours=48,
        teacher_id=teacher.id if teacher else None,
        semester=semester,
        capacity=capacity,
    )
    db.session.add(course)
    db.session.commit()
    return course


def enroll(student: Student, course: Course, *, exam_type: str = "期末", score: float | None = None):
    enrollment = Enrollment(student_id=student.id, course_id=course.id)
    db.session.add(enrollment)
    db.session.commit()
    if score is not None:
        db.session.add(
            Score(enrollment_id=enrollment.id, exam_type=exam_type, score=score)
        )
        db.session.commit()
    return enrollment


def login(client: FlaskClient, username: str, password: str = PASSWORD):
    response = client.post("/auth/login", data={"username": username, "password": password})
    assert response.status_code == 302, "登录未成功"
    return response


# --------------------------------------------------------------------------- #
# 权限矩阵：路由 × 角色
# --------------------------------------------------------------------------- #
#: (说明, 路径, 允许的角色集合)
ROUTES: tuple[tuple[str, str, frozenset[str]], ...] = (
    # 首页：三种角色都能看（未登录也能看系统状态页）
    ("首页", "/", frozenset({"anonymous", "admin", "teacher", "student"})),
    # 第 6 节「用户账号管理」：仅 admin
    ("账号管理-列表", "/admin/users", frozenset({"admin"})),
    ("账号总览", "/admin/", frozenset({"admin"})),
    # 第 6 节「课程信息」「统计报表」：三种角色都能进，但范围不同（范围由各自测试覆盖）
    ("我的课程", "/score/my-courses", frozenset({"admin", "teacher", "student"})),
    ("统计报表", "/report/overview", frozenset({"admin", "teacher", "student"})),
)

ALL_ROLES = ("anonymous", "admin", "teacher", "student")


@pytest.fixture
def actors(app: Flask) -> dict[str, User | None]:
    """四种身份：未登录 + 三种角色（各自只有账号，不含档案）。"""
    return {
        "anonymous": None,
        "admin": make_user("admin1", "admin", real_name="管理员甲"),
        "teacher": make_user("teacher1", "teacher", real_name="教师甲"),
        "student": make_user("student1", "student", real_name="学生甲"),
    }


@pytest.mark.parametrize(("label", "path", "allowed"), ROUTES, ids=[r[0] for r in ROUTES])
@pytest.mark.parametrize("role", ALL_ROLES)
def test_permission_matrix(
    app: Flask,
    client: FlaskClient,
    actors: dict[str, User | None],
    label: str,
    path: str,
    allowed: frozenset[str],
    role: str,
) -> None:
    """权限矩阵：允许的角色得到 200，其余角色得到 403（未登录则跳登录页）。"""
    actor = actors[role]
    if actor is not None:
        login(client, actor.username)

    response = client.get(path)

    if role in allowed:
        assert response.status_code == 200, f"{role} 访问 {label}({path}) 应当被允许"
        return

    if role == "anonymous":
        assert response.status_code == 302, f"未登录访问 {label}({path}) 应当跳登录页"
        assert "/auth/login" in response.headers["Location"]
        assert f"next={path}" in response.headers["Location"]
    else:
        assert response.status_code == 403, f"{role} 访问 {label}({path}) 应当被拒绝"
        html = response.get_data(as_text=True)
        assert "403" in html
        assert "无权访问" in html


def test_forbidden_page_explains_required_role(
    app: Flask, client: FlaskClient, actors: dict[str, User | None]
) -> None:
    """403 页面要写清"你的角色"和"要求的角色"，验收时可以照着讲。"""
    login(client, "student1")
    html = client.get("/admin/users").get_data(as_text=True)

    assert "学生" in html          # 当前角色
    assert "管理员" in html        # 该功能要求的角色
    assert "HTTP 403" in html      # 明确这是服务端拦下的


def test_nav_does_not_offer_admin_links_to_student(
    app: Flask, client: FlaskClient, actors: dict[str, User | None]
) -> None:
    """导航按角色渲染：学生看不到"账号管理"入口。"""
    login(client, "student1")
    html = client.get("/").get_data(as_text=True)

    assert "/admin/users" not in html
    assert "账号管理" not in html


def test_nav_offers_admin_links_to_admin(
    app: Flask, client: FlaskClient, actors: dict[str, User | None]
) -> None:
    login(client, "admin1")
    html = client.get("/").get_data(as_text=True)

    assert "/admin/users" in html
    assert "账号管理" in html


def test_nav_shows_pending_placeholders_for_future_rounds(
    app: Flask, client: FlaskClient, actors: dict[str, User | None]
) -> None:
    """后续轮次的功能在导航里是灰显占位（没有链接，不是死链）。"""
    login(client, "student1")
    html = client.get("/").get_data(as_text=True)

    assert "我的成绩" in html          # R8 的占位项
    assert "nav-pending" in html


def test_unknown_role_name_fails_fast() -> None:
    """``@role_required`` 写错角色名要立刻报错，不能变成隐藏的权限漏洞。"""
    with pytest.raises(ValueError):

        @decorators.role_required("admin", "principle")
        def view():  # pragma: no cover - 只是用来触发装饰器构造
            return "unreachable"


# --------------------------------------------------------------------------- #
# 写操作：权限 + 副作用
# --------------------------------------------------------------------------- #
def test_non_admin_cannot_toggle_account(
    app: Flask, client: FlaskClient, actors: dict[str, User | None]
) -> None:
    """被拒的写操作不能有副作用：账号状态不变，也不能出现成功提示。"""
    target = make_user("victim", "student")
    login(client, "teacher1")

    response = client.post(f"/admin/users/{target.id}/toggle")

    assert response.status_code == 403
    db.session.refresh(target)
    assert target.is_active is True


def test_anonymous_cannot_toggle_account(
    app: Flask, client: FlaskClient, actors: dict[str, User | None]
) -> None:
    target = make_user("victim", "student")

    response = client.post(f"/admin/users/{target.id}/toggle")

    assert response.status_code == 302
    assert "/auth/login" in response.headers["Location"]
    db.session.refresh(target)
    assert target.is_active is True


def test_toggle_requires_post(
    app: Flask, client: FlaskClient, actors: dict[str, User | None]
) -> None:
    target = make_user("victim", "student")
    login(client, "admin1")

    assert client.get(f"/admin/users/{target.id}/toggle").status_code == 405


def test_admin_can_deactivate_and_reactivate_account(
    app: Flask, client: FlaskClient, actors: dict[str, User | None]
) -> None:
    target = make_user("victim", "student")
    login(client, "admin1")

    first = client.post(f"/admin/users/{target.id}/toggle")
    assert first.status_code == 302
    db.session.refresh(target)
    assert target.is_active is False

    second = client.post(f"/admin/users/{target.id}/toggle")
    assert second.status_code == 302
    db.session.refresh(target)
    assert target.is_active is True


def test_admin_cannot_deactivate_self(
    app: Flask, client: FlaskClient, actors: dict[str, User | None]
) -> None:
    """业务规则：不能停用自己（否则会把自己锁在系统外）。"""
    admin = actors["admin"]
    login(client, admin.username)

    response = client.post(f"/admin/users/{admin.id}/toggle", follow_redirects=True)

    assert response.status_code == 200
    assert "不能停用当前登录的账号" in response.get_data(as_text=True)
    db.session.refresh(admin)
    assert admin.is_active is True


def test_last_admin_cannot_be_deactivated(
    app: Flask, client: FlaskClient, actors: dict[str, User | None]
) -> None:
    """业务规则：系统至少要保留一个可用的管理员账号。

    这条规则在**模型层**验证（``User.deactivation_blocker``）：
    通过 HTTP 路由其实碰不到这个分支 —— 发请求的管理员自己必然还是可用管理员，
    所以"要停用的对象是最后一个管理员"在正常操作下不可能成立；
    它是防"运维在库层面停用了其他管理员"这类异常状态的兜底。
    """
    admin1 = actors["admin"]
    admin2 = make_user("admin2", "admin")

    # 只剩 admin2 一个可用管理员时：别人要停用他 → 被规则挡住
    admin1.is_active = False
    db.session.commit()
    assert admin2.deactivation_blocker(actor=None) == "系统必须保留至少一个可用的管理员账号。"

    # 还有别的可用管理员时：允许停用
    admin1.is_active = True
    db.session.commit()
    assert admin2.deactivation_blocker(actor=None) is None

    # 自己停用自己：走的是另一条规则（与"最后一个管理员"无关）
    assert admin1.deactivation_blocker(actor=admin1) == "不能停用当前登录的账号。"


def test_admin_can_deactivate_regular_user_through_http(
    app: Flask, client: FlaskClient, actors: dict[str, User | None]
) -> None:
    """HTTP 路径上的正常停用：最后一个可用管理员不受影响，操作应当成功。"""
    target = make_user("victim2", "student")
    login(client, "admin1")

    response = client.post(f"/admin/users/{target.id}/toggle", follow_redirects=True)

    assert response.status_code == 200
    assert "已停用账号 victim2" in response.get_data(as_text=True)
    db.session.refresh(target)
    assert target.is_active is False


def test_toggle_missing_user_returns_404(
    app: Flask, client: FlaskClient, actors: dict[str, User | None]
) -> None:
    login(client, "admin1")
    response = client.post("/admin/users/999999/toggle")
    assert response.status_code == 404
    assert "404" in response.get_data(as_text=True)


def test_user_list_filters_by_role_and_keyword(
    app: Flask, client: FlaskClient, actors: dict[str, User | None]
) -> None:
    login(client, "admin1")

    only_teachers = client.get("/admin/users?role=teacher").get_data(as_text=True)
    assert "teacher1" in only_teachers
    assert "student1" not in only_teachers

    searched = client.get("/admin/users?q=学生甲").get_data(as_text=True)
    assert "student1" in searched
    assert "teacher1" not in searched


def test_user_list_ignores_bogus_role_filter(
    app: Flask, client: FlaskClient, actors: dict[str, User | None]
) -> None:
    """非法角色值当作"不筛选"，不能变成奇怪的查询或报错。"""
    login(client, "admin1")
    response = client.get("/admin/users?role=superuser")
    assert response.status_code == 200
    assert "admin1" in response.get_data(as_text=True)


# --------------------------------------------------------------------------- #
# 行级校验：课程详情"是不是自己教的课"
# --------------------------------------------------------------------------- #
def test_admin_sees_every_course_detail(
    app: Flask, client: FlaskClient, actors: dict[str, User | None]
) -> None:
    teacher = make_teacher()
    course = make_course(teacher)
    login(client, "admin1")

    response = client.get(f"/score/courses/{course.id}")
    assert response.status_code == 200
    assert course.name in response.get_data(as_text=True)


def test_teacher_can_open_own_course_but_not_others(
    app: Flask, client: FlaskClient, actors: dict[str, User | None]
) -> None:
    """行级校验：同为教师，别人的课必须 403（不是 404，也不是空白页）。"""
    mine = make_teacher("mine")
    other = make_teacher("other")
    own_course = make_course(mine, "C100", name="我教的课")
    other_course = make_course(other, "C200", name="别人的课")

    login(client, "mine")
    assert client.get(f"/score/courses/{own_course.id}").status_code == 200

    denied = client.get(f"/score/courses/{other_course.id}")
    assert denied.status_code == 403
    assert "不在你的权限范围内" in denied.get_data(as_text=True)


def test_student_can_open_enrolled_course_but_not_unenrolled(
    app: Flask, client: FlaskClient, actors: dict[str, User | None]
) -> None:
    teacher = make_teacher()
    enrolled_course = make_course(teacher, "C300", name="我选的课")
    other_course = make_course(teacher, "C400", name="没选的课")
    student = make_student("s1")
    enroll(student, enrolled_course)

    login(client, "s1")
    assert client.get(f"/score/courses/{enrolled_course.id}").status_code == 200

    denied = client.get(f"/score/courses/{other_course.id}")
    assert denied.status_code == 403


def test_missing_course_is_404_not_403(
    app: Flask, client: FlaskClient, actors: dict[str, User | None]
) -> None:
    """不存在的课程是 404；无权访问的课程是 403 —— 两种响应要能区分。"""
    login(client, "student1")
    assert client.get("/score/courses/999999").status_code == 404


def test_my_courses_scope_by_role(
    app: Flask, client: FlaskClient, actors: dict[str, User | None]
) -> None:
    mine = make_teacher("mine")
    other = make_teacher("other")
    own_course = make_course(mine, "C500", name="我教的课")
    other_course = make_course(other, "C600", name="别人的课")

    student = make_student("s1")
    enroll(student, own_course)

    # 教师：只看到自己教的
    login(client, "mine")
    teacher_page = client.get("/score/my-courses").get_data(as_text=True)
    assert "我教的课" in teacher_page
    assert "别人的课" not in teacher_page

    # 学生：只看到自己选的
    login(client, "s1")
    student_page = client.get("/score/my-courses").get_data(as_text=True)
    assert "我教的课" in student_page
    assert "别人的课" not in student_page

    # 管理员：全部（已登录状态下再登录不会换人，必须先登出）
    client.post("/auth/logout")
    login(client, "admin1")
    admin_page = client.get("/score/my-courses").get_data(as_text=True)
    assert "我教的课" in admin_page
    assert "别人的课" in admin_page


def test_my_courses_handles_missing_profile(
    app: Flask, client: FlaskClient, actors: dict[str, User | None]
) -> None:
    """账号存在但没有学生 / 教师档案时不能 500。"""
    login(client, "teacher1")
    assert client.get("/score/my-courses").status_code == 200

    login(client, "student1")
    assert client.get("/score/my-courses").status_code == 200


# --------------------------------------------------------------------------- #
# can_view_course：行级校验原语
# --------------------------------------------------------------------------- #
def test_can_view_course_matrix(app: Flask, actors: dict[str, User | None]) -> None:
    """行级校验原语本身也要覆盖：三种角色 × 两种课程。"""
    mine = make_teacher("mine")
    other = make_teacher("other")
    own_course = make_course(mine, "C700")
    other_course = make_course(other, "C800")

    student = make_student("s1")
    enroll(student, own_course)

    admin = actors["admin"]
    assert decorators.can_view_course(admin, own_course) is True
    assert decorators.can_view_course(admin, other_course) is True

    mine_user = db.session.get(User, mine.user_id)
    assert decorators.can_view_course(mine_user, own_course) is True
    assert decorators.can_view_course(mine_user, other_course) is False

    student_user = db.session.get(User, student.user_id)
    assert decorators.can_view_course(student_user, own_course) is True
    assert decorators.can_view_course(student_user, other_course) is False

    # 边界：未登录 / 空对象一律 False
    assert decorators.can_view_course(None, own_course) is False
    assert decorators.can_view_course(student_user, None) is False


def test_role_label_helper() -> None:
    assert decorators.role_label("admin") == "管理员"
    assert decorators.role_label("teacher") == "教师"
    assert decorators.role_label("student") == "学生"
    assert decorators.role_label(None) == "未知角色"
    assert decorators.role_label("weird") == "weird"


def test_menu_filters_by_role_and_keeps_placeholders(
    app: Flask, client: FlaskClient, actors: dict[str, User | None]
) -> None:
    """菜单按角色过滤；尚未实现的轮次保留为灰显占位（无链接）。

    ``menu.MENU_ITEMS`` 里已经声明了 R4~R10 的占位项（``endpoint`` 为 None），
    所以这里可以直接验证"占位项保留、可跳转项才生成链接"这条规则。
    """
    from gradeapp import menu

    with app.test_request_context("/"):
        admin_items = {item["key"]: item for item in menu.menu_for_user(actors["admin"])}
        student_items = {item["key"]: item for item in menu.menu_for_user(actors["student"])}

    # 管理员能看到账号管理（可跳转），但看不到学生专属的"选课"
    assert admin_items["admin_users"]["url"] == "/admin/users"
    assert "enroll" not in admin_items

    # 学生看不到账号管理，但保留后续轮次的占位项（没有 url）
    assert "admin_users" not in student_items
    assert student_items["my_scores"]["url"] is None
    assert student_items["my_scores"]["pending"] == "R8"


def test_menu_drops_items_whose_endpoint_is_not_registered(
    app: Flask, monkeypatch: pytest.MonkeyPatch
) -> None:
    """端点尚未注册的菜单项要退化成灰显占位，不能生成死链或抛异常。

    （R4~R10 的占位项 ``endpoint`` 本来就是 None，这条规则是给"写了端点名但
    该蓝图还没注册"的情况兜底。）
    """
    from gradeapp import menu

    ghost = {
        "key": "ghost",
        "label": "未注册端点",
        "endpoint": "nowhere.at_all",
        "roles": ("admin",),
        "pending": None,
    }
    monkeypatch.setattr(menu, "MENU_ITEMS", (ghost,))

    admin = make_user("admin9", "admin")
    with app.test_request_context("/"):
        items = menu.menu_for_user(admin)

    assert [item["key"] for item in items] == ["ghost"]
    assert items[0]["url"] is None


def test_menu_for_anonymous_only_has_home(app: Flask) -> None:
    from gradeapp import menu

    with app.test_request_context("/"):
        items = menu.menu_for_user(None)

    assert [item["key"] for item in items] == ["home"]
    assert items[0]["url"] == "/"


def test_unknown_role_gets_empty_scope(app: Flask) -> None:
    """数据里出现未知角色时，范围类查询要返回空集合而不是 500。

    账号角色由数据库 CHECK 约束保护，正常写不进未知值；
    这里用**未入库**的对象覆盖防御分支（不入库也就不会触发 CHECK）。
    """
    from gradeapp import report, score

    user = User(username="ghost", role="inspector", real_name="未知角色")
    assert user.teacher is None and user.student is None

    assert score._course_rows_for(user) == []
    assert report._visible_course_ids(user) == []


def test_course_detail_denied_when_profile_missing(
    app: Flask, client: FlaskClient, actors: dict[str, User | None]
) -> None:
    """账号没有对应的学生 / 教师档案时，课程详情应当 403 而不是 500。"""
    teacher = make_teacher("t9")
    course = make_course(teacher, "C950")

    # teacher1 / student1 这两个账号都没有档案
    login(client, "teacher1")
    assert client.get(f"/score/courses/{course.id}").status_code == 403

    client.post("/auth/logout")
    login(client, "student1")
    assert client.get(f"/score/courses/{course.id}").status_code == 403


# --------------------------------------------------------------------------- #
# 三种角色的首页不同
# --------------------------------------------------------------------------- #
def test_admin_home_shows_account_overview(
    app: Flask, client: FlaskClient, actors: dict[str, User | None]
) -> None:
    login(client, "admin1")
    html = client.get("/").get_data(as_text=True)

    assert "管理员首页" in html
    assert "账号总数" in html


def test_teacher_home_shows_own_courses(
    app: Flask, client: FlaskClient, actors: dict[str, User | None]
) -> None:
    teacher = make_teacher("t1")
    course = make_course(teacher, "C900", name="教师首页的课")

    login(client, "admin1")  # 先登录再切到教师，确认首页按当前角色变化
    client.post("/auth/logout")

    login(client, "t1")
    html = client.get("/").get_data(as_text=True)

    assert "教师首页" in html
    assert "教师首页的课" in html


def test_student_home_shows_own_enrollments(
    app: Flask, client: FlaskClient, actors: dict[str, User | None]
) -> None:
    teacher = make_teacher("t2")
    course = make_course(teacher, "C901", name="学生首页的课")
    student = make_student("s2")
    enroll(student, course)

    login(client, "s2")
    html = client.get("/").get_data(as_text=True)

    assert "学生首页" in html
    assert "学生首页的课" in html


def test_anonymous_home_keeps_system_status(
    app: Flask, client: FlaskClient, actors: dict[str, User | None]
) -> None:
    """未登录首页仍是 R1 的系统状态页（原有断言不能因为 R3 改动而失效）。"""
    html = client.get("/").get_data(as_text=True)

    assert "系统已启动" in html
    assert "未登录" in html
    assert "管理员首页" not in html


# --------------------------------------------------------------------------- #
# 统计报表：数据范围按角色收缩
# --------------------------------------------------------------------------- #
def test_report_scopes_data_by_role(
    app: Flask, client: FlaskClient, actors: dict[str, User | None]
) -> None:
    """同一套口径，三种角色看到三个范围：全校 / 仅自授课程 / 仅本人。"""
    mine = make_teacher("mine")
    other = make_teacher("other")
    own_course = make_course(mine, "R100", name="我的课")
    other_course = make_course(other, "R200", name="别人的课")

    my_student = make_student("s_mine", sno="S1001")
    other_student = make_student("s_other", sno="S1002")
    enroll(my_student, own_course, score=90)
    enroll(other_student, other_course, score=30)

    # 管理员：全校范围，能看到两门课；两条成绩 90 / 30 → 平均分 60.0、及格率 50.0%
    login(client, "admin1")
    admin_html = client.get("/report/overview").get_data(as_text=True)
    assert "全校范围" in admin_html
    assert "我的课" in admin_html
    assert "别人的课" in admin_html
    assert "60.0" in admin_html
    assert "50.0%" in admin_html

    # 教师：仅自己授课的课程（平均分 90.0，及格率 1/1 = 100.0%）
    # 已登录状态下再登录不会换人，切换角色前必须先登出
    client.post("/auth/logout")
    login(client, "mine")
    teacher_html = client.get("/report/overview").get_data(as_text=True)
    assert "仅你授课的课程" in teacher_html
    assert "我的课" in teacher_html
    assert "别人的课" not in teacher_html
    assert "90.0" in teacher_html
    assert "100.0%" in teacher_html
    assert "50.0%" not in teacher_html

    # 学生：仅本人
    client.post("/auth/logout")
    login(client, "s_mine")
    student_html = client.get("/report/overview").get_data(as_text=True)
    assert "仅你本人的选课与成绩" in student_html
    assert "我的课" in student_html
    assert "别人的课" not in student_html
    assert "90.0" in student_html


def test_report_handles_course_without_scores(
    app: Flask, client: FlaskClient, actors: dict[str, User | None]
) -> None:
    """没有成绩时平均分显示 —，及格率 0%，不能因为除零而 500。"""
    teacher = make_teacher("t3")
    course = make_course(teacher, "R300", name="没人选的课")

    login(client, "t3")
    response = client.get("/report/overview")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "没人选的课" in html
    assert "0.0%" in html
    assert "—" in html


def test_report_with_no_courses_at_all(
    app: Flask, client: FlaskClient, actors: dict[str, User | None]
) -> None:
    login(client, "admin1")
    response = client.get("/report/overview")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "当前范围内还没有课程数据" in html


def test_teacher_report_excludes_other_teachers(
    app: Flask, client: FlaskClient, actors: dict[str, User | None]
) -> None:
    """教师看别人的课（连统计数据）都不行：范围里只有自己的课。"""
    mine = make_teacher("mine")
    other = make_teacher("other")
    make_course(other, "R400", name="别人的课")

    login(client, "mine")
    html = client.get("/report/overview").get_data(as_text=True)

    assert "别人的课" not in html
    assert "0" in html  # 课程数 0
