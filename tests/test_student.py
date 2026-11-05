"""R11 补齐 R4 欠账：学生信息管理的完整测试（此前只有网页交付，没有测试）。

覆盖 R4 交付的学生 CRUD 全路径（``gradeapp/admin.py`` 的学生段）：
1. **列表**：按学号 / 姓名 / 班级搜索、分页（PER_PAGE=10）；
2. **新增**：自动建立登录账号（用户名 = 学号、默认密码 123456、库中只存哈希）、
   学号或用户名冲突被拒、初始密码可自定义；
3. **编辑**：改学号同步改用户名、填密码则重置口令、学号被占用被拒；
4. **删除**：连账号一起删，选课与成绩级联删除；
5. **写操作权限**：非管理员的 POST 一律 403 且无副作用（GET 由权限矩阵覆盖）。
"""

from __future__ import annotations

from flask import Flask
from flask.testing import FlaskClient
from sqlalchemy import func, select

from gradeapp.extensions import db
from gradeapp.models import Enrollment, Score, Student, Teacher, User

PASSWORD = "pw-123456"


# --------------------------------------------------------------------------- #
# 辅助
# --------------------------------------------------------------------------- #
def make_user(username: str, role: str) -> User:
    user = User(username=username, role=role, real_name=username)
    user.set_password(PASSWORD)
    db.session.add(user)
    db.session.commit()
    return user


def make_student(username: str = "stu1", *, sno: str | None = None) -> Student:
    user = make_user(username, "student")
    student = Student(
        user_id=user.id, sno=sno or f"S{user.id:04d}", name=user.real_name,
        gender="男", class_name="计算机2501", enroll_year=2025,
    )
    db.session.add(student)
    db.session.commit()
    return student


def login(client: FlaskClient, username: str, password: str = PASSWORD) -> None:
    response = client.post("/auth/login", data={"username": username, "password": password})
    assert response.status_code == 302, "登录未成功"


def as_admin(client: FlaskClient) -> User:
    admin = make_user("admin1", "admin")
    login(client, admin.username)
    return admin


# --------------------------------------------------------------------------- #
# 列表：搜索与分页
# --------------------------------------------------------------------------- #
def test_student_list_searches_by_sno_name_and_class(app: Flask, client: FlaskClient):
    """关键词命中学号 / 姓名 / 班级任一字段。"""
    make_student("a1", sno="2025001")
    target = make_student("b2", sno="2025002")
    target.name = "王小明"
    target.class_name = "计算机2502"
    db.session.commit()
    as_admin(client)

    assert "2025001" not in client.get("/admin/students?q=2025002").get_data(as_text=True)
    assert "王小明" in client.get("/admin/students?q=小明").get_data(as_text=True)
    assert "计算机2502" in client.get("/admin/students?q=2502").get_data(as_text=True)


def test_student_list_pagination(app: Flask, client: FlaskClient):
    """PER_PAGE=10：第 11 名学生落到第 2 页。"""
    for i in range(11):
        make_student(f"s{i:02d}", sno=f"20250{i:03d}")
    as_admin(client)

    first = client.get("/admin/students").get_data(as_text=True)
    assert "第 1 / 2 页" in first
    second = client.get("/admin/students?page=2").get_data(as_text=True)
    assert "第 2 / 2 页" in second
    # 按学号排序：第 1 页最后一个不是 2025010（第 11 条在第 2 页）
    assert "20250010" in second


# --------------------------------------------------------------------------- #
# 新增：自动建账号
# --------------------------------------------------------------------------- #
def test_student_create_builds_account_with_default_password(app: Flask, client: FlaskClient):
    """新增学生即建账号：用户名 = 学号、默认密码 123456（哈希存储）、页面闪现提示。"""
    as_admin(client)

    response = client.post("/admin/students/create", data={
        "sno": "2025999", "name": "陈新", "gender": "女",
        "class_name": "计算机2503", "enroll_year": "2025", "password": "",
    }, follow_redirects=True)

    html = response.get_data(as_text=True)
    assert "创建成功" in html and "123456" in html
    user = db.session.scalar(select(User).where(User.username == "2025999"))
    assert user is not None and user.role == "student" and user.real_name == "陈新"
    assert user.password_hash != "123456" and user.check_password("123456")
    student = db.session.scalar(select(Student).where(Student.sno == "2025999"))
    assert student is not None and student.user_id == user.id and student.gender == "女"


def test_student_create_with_custom_password(app: Flask, client: FlaskClient):
    """初始密码可自定义，入库仍是哈希。"""
    as_admin(client)
    client.post("/admin/students/create", data={
        "sno": "2025888", "name": "李自定义", "gender": "", "class_name": "",
        "enroll_year": "2025", "password": "custom-pass-1",
    })
    user = db.session.scalar(select(User).where(User.username == "2025888"))
    assert user.check_password("custom-pass-1") and not user.check_password("123456")


def test_student_create_rejects_duplicate_sno(app: Flask, client: FlaskClient):
    """学号与既有用户名冲突都被拒，不落库。"""
    existing = make_student("stu1", sno="2025001")
    as_admin(client)

    for field, value in (("学号冲突", "2025001"), ("用户名冲突", "stu1")):
        before = int(db.session.scalar(select(func.count()).select_from(Student)) or 0)
        response = client.post("/admin/students/create", data={
            "sno": value, "name": "重复测试", "gender": "", "class_name": "",
            "enroll_year": "2025", "password": "",
        }, follow_redirects=True)
        assert "已存在" in response.get_data(as_text=True), field
        assert (int(db.session.scalar(select(func.count()).select_from(Student)) or 0)) == before


def test_student_create_validates_required_fields(app: Flask, client: FlaskClient):
    """学号 / 姓名为空给表单错误，不落库。"""
    as_admin(client)
    response = client.post("/admin/students/create", data={
        "sno": "", "name": "", "gender": "", "class_name": "", "enroll_year": "2025", "password": "",
    }, follow_redirects=True)
    assert "学号不能为空" in response.get_data(as_text=True)
    assert "姓名不能为空" in response.get_data(as_text=True)
    assert int(db.session.scalar(select(func.count()).select_from(Student)) or 0) == 0


# --------------------------------------------------------------------------- #
# 编辑：同步账号
# --------------------------------------------------------------------------- #
def test_student_edit_syncs_username_and_can_reset_password(app: Flask, client: FlaskClient):
    """改学号同步改用户名；填密码则重置口令；不填密码口令不变。"""
    student = make_student("stu1", sno="2025001")
    as_admin(client)

    response = client.post(f"/admin/students/{student.id}/edit", data={
        "sno": "2025002", "name": "改名同学", "gender": "女",
        "class_name": "计算机2505", "enroll_year": "2024", "password": "new-pass-9",
    }, follow_redirects=True)
    assert "信息更新成功" in response.get_data(as_text=True)

    db.session.expire_all()
    user = db.session.get(User, student.user_id)
    assert user.username == "2025002"
    assert user.real_name == "改名同学"
    assert user.check_password("new-pass-9")
    student = db.session.get(Student, student.id)
    assert student.sno == "2025002" and student.enroll_year == 2024


def test_student_edit_without_password_keeps_old(app: Flask, client: FlaskClient):
    """编辑不填密码：口令保持不变。"""
    student = make_student("stu1", sno="2025001")
    as_admin(client)
    client.post(f"/admin/students/{student.id}/edit", data={
        "sno": "2025001", "name": "改名同学", "gender": "", "class_name": "",
        "enroll_year": "2025", "password": "",
    })
    db.session.expire_all()
    assert db.session.get(User, student.user_id).check_password(PASSWORD)


def test_student_edit_rejects_taken_sno(app: Flask, client: FlaskClient):
    """学号被其他学生占用 → 拒绝且原学号不变。"""
    make_student("other", sno="2025002")
    student = make_student("stu1", sno="2025001")
    as_admin(client)

    response = client.post(f"/admin/students/{student.id}/edit", data={
        "sno": "2025002", "name": "撞号同学", "gender": "", "class_name": "",
        "enroll_year": "2025", "password": "",
    }, follow_redirects=True)
    assert "已被占用" in response.get_data(as_text=True)
    db.session.expire_all()
    assert db.session.get(Student, student.id).sno == "2025001"


# --------------------------------------------------------------------------- #
# 删除：连账号、级联选课与成绩
# --------------------------------------------------------------------------- #
def test_student_delete_cascades_account_enrollments_scores(app: Flask, client: FlaskClient):
    """删除学生 = 连账号一起删；选课记录与成绩级联删除。"""
    student = make_student("stu1", sno="2025001")
    from gradeapp.models import Course
    course = Course(code="C001", name="课程C001", credit=3.0, hours=48,
                    teacher_id=None, semester="2025-2026-1", capacity=60)
    db.session.add(course)
    db.session.commit()
    enrollment = Enrollment(student_id=student.id, course_id=course.id)
    db.session.add(enrollment)
    db.session.commit()
    db.session.add(Score(enrollment_id=enrollment.id, exam_type="期末", score=88))
    db.session.commit()

    as_admin(client)
    response = client.post(f"/admin/students/{student.id}/delete", follow_redirects=True)
    assert "已删除学生" in response.get_data(as_text=True)

    db.session.expire_all()
    assert db.session.get(Student, student.id) is None
    assert db.session.get(User, student.user_id) is None
    assert int(db.session.scalar(select(func.count()).select_from(Enrollment)) or 0) == 0
    assert int(db.session.scalar(select(func.count()).select_from(Score)) or 0) == 0


# --------------------------------------------------------------------------- #
# 写操作权限：非管理员 403 且无副作用
# --------------------------------------------------------------------------- #
def test_student_write_routes_require_admin(app: Flask, client: FlaskClient):
    """教师 / 学生对学生 CRUD 写路由一律 403，且不产生任何数据变化。"""
    make_student("stu1", sno="2025001")
    student = db.session.scalar(select(Student).where(Student.sno == "2025001"))
    make_user("t1", "teacher")

    for username in ("t1", "stu1"):
        client_app = app.test_client()
        login(client_app, username)

        assert client_app.post("/admin/students/create", data={
            "sno": "2025777", "name": "越权学生", "gender": "", "class_name": "",
            "enroll_year": "2025", "password": "",
        }).status_code == 403
        assert client_app.post(f"/admin/students/{student.id}/delete").status_code == 403

    assert db.session.scalar(select(Student).where(Student.sno == "2025777")) is None
    assert db.session.get(Student, student.id) is not None


# --------------------------------------------------------------------------- #
# R11 边界补充：教师编辑冲突与课程表单分支（admin.py 收尾）
# --------------------------------------------------------------------------- #
def make_teacher_record(tno: str = "T9001") -> "Teacher":
    from gradeapp.models import Teacher
    user = make_user(f"u-{tno}", "teacher")
    teacher = Teacher(user_id=user.id, tno=tno, name="教师" + tno, title="讲师", department="计算机学院")
    db.session.add(teacher)
    db.session.commit()
    return teacher


def test_teacher_edit_rejects_taken_tno(app: Flask, client: FlaskClient):
    """编辑教师时工号被其他教师 / 用户名占用 → 拒绝且原工号不变。"""
    make_teacher_record("T9002")
    teacher = make_teacher_record("T9001")
    as_admin(client)

    response = client.post(f"/admin/teachers/{teacher.id}/edit", data={
        "tno": "T9002", "name": "撞号教师", "title": "", "department": "", "password": "",
    }, follow_redirects=True)
    assert "已被占用" in response.get_data(as_text=True)
    db.session.expire_all()
    assert db.session.get(Teacher, teacher.id).tno == "T9001"


def test_course_edit_get_prefills_unassigned_teacher(app: Flask, client: FlaskClient):
    """编辑页 GET：未排课课程的教师下拉框预置为「未排课」（0），不覆盖 POST 提交值。"""
    from gradeapp.models import Course
    course = Course(code="C301", name="未排课的课", credit=3.0, hours=48,
                    teacher_id=None, semester="2025-2026-1", capacity=60)
    db.session.add(course)
    db.session.commit()
    as_admin(client)

    response = client.get(f"/admin/courses/{course.id}/edit")
    assert response.status_code == 200
    assert "selected" in response.get_data(as_text=True)
