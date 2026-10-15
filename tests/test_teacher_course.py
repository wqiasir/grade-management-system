"""R5 验证：教师与课程管理（管理员 CRUD）。

覆盖：
1. 教师管理：创建（同步建登录账号、默认密码、只存哈希）、工号/用户名唯一冲突、
   编辑同步账号与重置密码、**仍授课的教师禁止删除**、无课时可删、列表搜索；
2. 课程管理：创建（可未排课）、课程代码唯一、表单校验（学期格式 / 学分范围）、
   **容量不得小于已选人数**、删除级联选课与成绩；
3. 写操作权限：非管理员一律 403 且无副作用（GET 路由的矩阵见 test_permissions.py）；
4. 导航：admin 能看到并进入"教师管理 / 课程管理"，其他角色看不到。
"""

from __future__ import annotations

from flask import Flask
from flask.testing import FlaskClient
from sqlalchemy import func, select

from gradeapp.extensions import db
from gradeapp.models import Course, Enrollment, Score, Student, Teacher, User

PASSWORD = "pw-123456"


# --------------------------------------------------------------------------- #
# 辅助：造数据与登录（与 test_permissions.py 各自独立，避免测试间隐式耦合）
# --------------------------------------------------------------------------- #
def make_user(
    username: str,
    role: str,
    *,
    real_name: str | None = None,
) -> User:
    user = User(
        username=username,
        role=role,
        real_name=real_name or username,
    )
    user.set_password(PASSWORD)
    db.session.add(user)
    db.session.commit()
    return user


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


def make_student(username: str = "stu1", *, sno: str | None = None) -> Student:
    user = make_user(username, "student", real_name="学生" + username)
    student = Student(
        user_id=user.id,
        sno=sno or f"S{user.id:04d}",
        name=user.real_name,
        class_name="计算机2501",
        enroll_year=2025,
    )
    db.session.add(student)
    db.session.commit()
    return student


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


def enroll(student: Student, course: Course, *, score: float | None = None) -> Enrollment:
    enrollment = Enrollment(student_id=student.id, course_id=course.id)
    db.session.add(enrollment)
    db.session.commit()
    if score is not None:
        db.session.add(
            Score(enrollment_id=enrollment.id, exam_type="期末", score=score)
        )
        db.session.commit()
    return enrollment


def login(client: FlaskClient, username: str, password: str = PASSWORD):
    response = client.post("/auth/login", data={"username": username, "password": password})
    assert response.status_code == 302, "登录未成功"
    return response


def teacher_count() -> int:
    return int(db.session.scalar(select(func.count()).select_from(Teacher)) or 0)


def course_count() -> int:
    return int(db.session.scalar(select(func.count()).select_from(Course)) or 0)


# --------------------------------------------------------------------------- #
# 教师管理
# --------------------------------------------------------------------------- #
def test_teacher_create_makes_profile_and_account(app: Flask, client: FlaskClient):
    """新增教师：同步建立教师账号（用户名 = 工号），默认密码可登录且只存哈希。"""
    login(client, make_user("admin1", "admin").username)
    response = client.post(
        "/admin/teachers/create",
        data={"tno": "T9001", "name": "王建国", "title": "讲师", "department": "计算机学院", "password": ""},
    )

    assert response.status_code == 302
    teacher = db.session.scalar(select(Teacher).where(Teacher.tno == "T9001"))
    assert teacher is not None
    assert teacher.name == "王建国"
    assert teacher.user.username == "T9001"
    assert teacher.user.role == "teacher"
    # 未填密码 → 默认 123456；库中是哈希而不是明文
    assert teacher.user.check_password("123456")
    assert teacher.user.password_hash != "123456"


def test_teacher_create_rejects_duplicate_tno_and_taken_username(app: Flask, client: FlaskClient):
    """工号重复、或工号撞上已有账号的用户名，都不允许创建。"""
    admin = make_user("admin1", "admin")
    make_teacher(tno="T9001")
    # 已有学生的登录用户名占用了 "S9001"
    make_student("S9001", sno="S9001")
    login(client, admin.username)

    for tno in ("T9001", "S9001"):
        response = client.post(
            "/admin/teachers/create",
            data={"tno": tno, "name": "李四", "password": ""},
        )
        assert response.status_code == 200
        assert "已存在" in response.get_data(as_text=True)

    assert teacher_count() == 1  # 两次尝试都没有落库


def test_teacher_edit_updates_profile_account_and_password(app: Flask, client: FlaskClient):
    """编辑教师：档案与账号（用户名/姓名）同步更新，填了密码则重置。"""
    admin = make_user("admin1", "admin")
    teacher = make_teacher(tno="T9001")
    login(client, admin.username)

    response = client.post(
        f"/admin/teachers/{teacher.id}/edit",
        data={"tno": "T9002", "name": "王更新", "title": "副教授", "department": "计算机学院", "password": "newpass123"},
    )

    assert response.status_code == 302
    db.session.expire_all()
    assert teacher.tno == "T9002"
    assert teacher.name == "王更新"
    assert teacher.user.username == "T9002"
    assert teacher.user.real_name == "王更新"
    assert teacher.user.check_password("newpass123")


def test_teacher_delete_blocked_while_teaching(app: Flask, client: FlaskClient):
    """业务规则：仍授课的教师不能删除，课程也不受影响。"""
    admin = make_user("admin1", "admin")
    teacher = make_teacher(tno="T9001")
    course = make_course(teacher, code="C001")
    login(client, admin.username)

    response = client.post(f"/admin/teachers/{teacher.id}/delete", follow_redirects=True)

    assert "授课课程" in response.get_data(as_text=True)
    assert teacher_count() == 1
    db.session.expire_all()
    assert db.session.get(Course, course.id) is not None
    assert db.session.get(Course, course.id).teacher_id == teacher.id


def test_teacher_delete_removes_profile_and_account(app: Flask, client: FlaskClient):
    """无课教师可删：档案与登录账号一并删除。"""
    admin = make_user("admin1", "admin")
    teacher = make_teacher(tno="T9001")
    user_id = teacher.user_id
    login(client, admin.username)

    response = client.post(f"/admin/teachers/{teacher.id}/delete")

    assert response.status_code == 302
    assert teacher_count() == 0
    assert db.session.get(User, user_id) is None


def test_teacher_list_searches_by_keyword(app: Flask, client: FlaskClient):
    """列表按工号/姓名/职称/学院搜索。"""
    admin = make_user("admin1", "admin")
    make_teacher("tea_zhang", tno="T0001")
    other = make_teacher("tea_li", tno="T0002")
    db.session.expire_all()
    db.session.get(Teacher, other.id).name = "李四"
    db.session.commit()
    login(client, admin.username)

    html = client.get("/admin/teachers", query_string={"q": "T0001"}).get_data(as_text=True)

    assert "T0001" in html
    assert "T0002" not in html


# --------------------------------------------------------------------------- #
# 课程管理
# --------------------------------------------------------------------------- #
def test_course_create_with_and_without_teacher(app: Flask, client: FlaskClient):
    """新增课程：可指定授课教师，也可"未排课"（teacher_id=0 → NULL）。"""
    admin = make_user("admin1", "admin")
    teacher = make_teacher(tno="T9001")
    login(client, admin.username)

    response = client.post(
        "/admin/courses/create",
        data={"code": "C201", "name": "数据结构", "credit": "3", "hours": "48",
              "semester": "2025-2026-1", "capacity": "60", "teacher_id": str(teacher.id)},
    )
    assert response.status_code == 302
    course = db.session.scalar(select(Course).where(Course.code == "C201"))
    assert course is not None
    assert course.teacher_id == teacher.id

    response = client.post(
        "/admin/courses/create",
        data={"code": "C202", "name": "编译原理", "credit": "4", "hours": "64",
              "semester": "2025-2026-2", "capacity": "50", "teacher_id": "0"},
    )
    assert response.status_code == 302
    course = db.session.scalar(select(Course).where(Course.code == "C202"))
    assert course is not None and course.teacher_id is None


def test_course_create_rejects_duplicate_code(app: Flask, client: FlaskClient):
    """课程代码唯一：重复创建被拒且不落库。"""
    admin = make_user("admin1", "admin")
    make_course(None, code="C201")
    login(client, admin.username)

    response = client.post(
        "/admin/courses/create",
        data={"code": "C201", "name": "另一门课", "credit": "3", "hours": "48",
              "semester": "2025-2026-1", "capacity": "60", "teacher_id": "0"},
    )

    assert response.status_code == 200
    assert "已存在" in response.get_data(as_text=True)
    assert course_count() == 1


def test_course_create_form_validation(app: Flask, client: FlaskClient):
    """表单校验：学期格式、学分范围不合法时拒绝并提示。"""
    admin = make_user("admin1", "admin")
    login(client, admin.username)

    response = client.post(
        "/admin/courses/create",
        data={"code": "C301", "name": "操作系统", "credit": "3", "hours": "48",
              "semester": "2025学年", "capacity": "60", "teacher_id": "0"},
    )
    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "学期格式" in html

    response = client.post(
        "/admin/courses/create",
        data={"code": "C302", "name": "操作系统", "credit": "25", "hours": "48",
              "semester": "2025-2026-1", "capacity": "60", "teacher_id": "0"},
    )
    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "学分需在" in html

    assert course_count() == 0


def test_course_edit_updates_fields_and_unassigns_teacher(app: Flask, client: FlaskClient):
    """编辑课程：字段更新；授课教师改回"未排课"则 teacher_id 置空。"""
    admin = make_user("admin1", "admin")
    teacher = make_teacher(tno="T9001")
    course = make_course(teacher, code="C201", capacity=60)
    login(client, admin.username)

    response = client.post(
        f"/admin/courses/{course.id}/edit",
        data={"code": "C201", "name": "数据结构（新版）", "credit": "4", "hours": "64",
              "semester": "2025-2026-2", "capacity": "80", "teacher_id": "0"},
    )

    assert response.status_code == 302
    db.session.expire_all()
    updated = db.session.get(Course, course.id)
    assert updated.name == "数据结构（新版）"
    assert updated.credit == 4.0
    assert updated.hours == 64
    assert updated.semester == "2025-2026-2"
    assert updated.capacity == 80
    assert updated.teacher_id is None


def test_course_edit_rejects_capacity_below_enrolled(app: Flask, client: FlaskClient):
    """业务规则：容量不得小于当前已选人数。"""
    admin = make_user("admin1", "admin")
    course = make_course(None, code="C201", capacity=60)
    enroll(make_student("stu_a"), course)
    enroll(make_student("stu_b"), course)  # 已选 2 人
    login(client, admin.username)

    response = client.post(
        f"/admin/courses/{course.id}/edit",
        data={"code": "C201", "name": "课程", "credit": "3", "hours": "48",
              "semester": "2025-2026-1", "capacity": "1", "teacher_id": "0"},
    )

    assert response.status_code == 200
    assert "已选人数" in response.get_data(as_text=True)
    db.session.expire_all()
    assert db.session.get(Course, course.id).capacity == 60  # 未被改小


def test_course_edit_rejects_duplicate_code(app: Flask, client: FlaskClient):
    admin = make_user("admin1", "admin")
    course = make_course(None, code="C201")
    make_course(None, code="C202")
    login(client, admin.username)

    response = client.post(
        f"/admin/courses/{course.id}/edit",
        data={"code": "C202", "name": "课程", "credit": "3", "hours": "48",
              "semester": "2025-2026-1", "capacity": "60", "teacher_id": "0"},
    )

    assert response.status_code == 200
    assert "已被其他课程占用" in response.get_data(as_text=True)
    db.session.expire_all()
    assert db.session.get(Course, course.id).code == "C201"


def test_course_delete_cascades_enrollments_and_scores(app: Flask, client: FlaskClient):
    """删除课程：其选课记录与成绩一并删除。"""
    admin = make_user("admin1", "admin")
    course = make_course(None, code="C201")
    enrollment = enroll(make_student(), course, score=88.0)
    login(client, admin.username)

    response = client.post(f"/admin/courses/{course.id}/delete", follow_redirects=True)

    assert "选课记录" in response.get_data(as_text=True)
    assert db.session.get(Course, course.id) is None
    assert db.session.get(Enrollment, enrollment.id) is None
    assert db.session.scalar(select(func.count()).select_from(Score)) == 0


def test_course_delete_missing_is_404(app: Flask, client: FlaskClient):
    admin = make_user("admin1", "admin")
    login(client, admin.username)

    assert client.post("/admin/courses/999/delete").status_code == 404
    assert client.post("/admin/teachers/999/delete").status_code == 404


def test_course_list_search_and_columns(app: Flask, client: FlaskClient):
    """列表搜索按代码/名称/学期；行内展示授课教师与已选人数。"""
    admin = make_user("admin1", "admin")
    teacher = make_teacher(tno="T9001")
    course = make_course(teacher, code="C201", name="数据结构")
    student = make_student()
    enroll(student, course)
    make_course(None, code="C999", name="无关课程")
    login(client, admin.username)

    html = client.get("/admin/courses", query_string={"q": "C201"}).get_data(as_text=True)

    assert "C201" in html
    assert "C999" not in html
    assert "数据结构" in html
    assert "T9001" in html      # 授课教师
    assert "1 / 60" in html     # 已选 / 容量


# --------------------------------------------------------------------------- #
# 写操作权限与导航
# --------------------------------------------------------------------------- #
def test_teacher_course_writes_require_admin(app: Flask, client: FlaskClient):
    """非管理员对教师/课程做写操作 → 403，且没有副作用。"""
    teacher = make_teacher("tea1", tno="T9001")
    course = make_course(teacher, code="C201")
    student_user = make_user("student1", "student")

    # 教师尝试新增教师
    login(client, teacher.user.username)
    response = client.post("/admin/teachers/create", data={"tno": "TX", "name": "x"})
    assert response.status_code == 403
    assert teacher_count() == 1

    # 学生尝试删除课程
    login(client, student_user.username)
    response = client.post(f"/admin/courses/{course.id}/delete")
    assert response.status_code == 403
    assert course_count() == 1


def test_nav_links_to_teacher_and_course_management(app: Flask, client: FlaskClient):
    """admin 导航出现"教师管理 / 课程管理"；学生看不到这些入口。"""
    make_user("admin1", "admin")
    make_user("student1", "student")

    # 登录视图对"已登录再登录"直接跳首页，两种角色各用一个独立会话
    admin_client = app.test_client()
    student_client = app.test_client()
    login(admin_client, "admin1")
    login(student_client, "student1")

    admin_html = admin_client.get("/").get_data(as_text=True)
    assert "/admin/teachers" in admin_html
    assert "/admin/courses" in admin_html
    assert "教师管理" in admin_html
    assert "课程管理" in admin_html

    student_html = student_client.get("/").get_data(as_text=True)
    assert "/admin/teachers" not in student_html
    assert "/admin/courses" not in student_html
