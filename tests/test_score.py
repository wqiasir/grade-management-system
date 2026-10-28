"""R6 验证：选课管理（学生选课 / 退课，管理员与教师查看名单）。

覆盖计划第 7 节 R6 的完成标准：
1. **选课**：学生选上课程并落库；一次选两门（演示路径）；
2. **重复选课**：同一门课第二次被拒，不产生第二条记录；
3. **容量上限**：已满课程拒绝选课；``capacity <= 0`` 视为不限容量；
4. **退课**：学生只退自己的；管理员可退任意一条；教师不能退课（403）；
5. **已出成绩不允许退课**：学生与管理员都退不掉，选课记录保留；
6. **选课名单**：管理员/教师能看，管理员可代学生加课 / 移出课程；教师只读；
7. **页面与导航**：选课页状态（已选/已满/可选）、关键词与学期筛选、各角色导航入口。

写操作被拒时还要验证**没有副作用**（记录数不变），避免"页面提示失败但数据已经改了"。
"""

from __future__ import annotations

from flask import Flask
from flask.testing import FlaskClient
from sqlalchemy import func, select

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
) -> User:
    user = User(username=username, role=role, real_name=real_name or username)
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


def enrollment_count() -> int:
    return int(db.session.scalar(select(func.count()).select_from(Enrollment)) or 0)


def enrollment_of(student: Student, course: Course) -> Enrollment | None:
    return db.session.scalar(
        select(Enrollment).where(
            Enrollment.student_id == student.id,
            Enrollment.course_id == course.id,
        )
    )


# --------------------------------------------------------------------------- #
# 选课：成功 / 重复 / 容量
# --------------------------------------------------------------------------- #
def test_student_can_enroll_and_choose_two_courses(app: Flask, client: FlaskClient):
    """演示路径：学生选 2 门课，都能在"我的课程"里看到。"""
    teacher = make_teacher()
    first = make_course(teacher, "C001", name="数据结构")
    second = make_course(teacher, "C002", name="操作系统")
    student = make_student("s1")
    login(client, student.user.username)

    for course in (first, second):
        response = client.post(
            f"/score/enroll/{course.id}",
            data={"next": "/score/enroll"},
            follow_redirects=True,
        )
        assert response.status_code == 200
        assert "已选上课程" in response.get_data(as_text=True)

    assert enrollment_count() == 2
    assert enrollment_of(student, first) is not None
    assert enrollment_of(student, second) is not None

    html = client.get("/score/my-courses").get_data(as_text=True)
    assert "数据结构" in html
    assert "操作系统" in html
    assert "已选 2 门" in html or "（2 门）" in html


def test_duplicate_enrollment_is_rejected_without_side_effect(
    app: Flask, client: FlaskClient
):
    """重复选同一门课：提示"不能重复选课"，记录数仍为 1。"""
    course = make_course(make_teacher(), "C001", name="数据结构")
    student = make_student("s1")
    enroll(student, course)
    login(client, student.user.username)

    response = client.post(
        f"/score/enroll/{course.id}", follow_redirects=True
    )

    assert response.status_code == 200
    assert "不能重复选课" in response.get_data(as_text=True)
    assert enrollment_count() == 1


def test_full_course_rejects_enrollment(app: Flask, client: FlaskClient):
    """容量上限：已选人数达到容量后，后续选课被拒且不落库。"""
    course = make_course(make_teacher(), "C001", name="只有 1 个名额", capacity=1)
    enrolled_student = make_student("s1")
    enroll(enrolled_student, course)
    late_student = make_student("s2")
    login(client, late_student.user.username)

    response = client.post(f"/score/enroll/{course.id}", follow_redirects=True)

    assert response.status_code == 200
    assert "已满" in response.get_data(as_text=True)
    assert enrollment_count() == 1
    assert enrollment_of(late_student, course) is None


def test_capacity_zero_means_unlimited(app: Flask, client: FlaskClient):
    """容量口径：``capacity <= 0`` 表示不限容量，可以被多名学生选满。"""
    course = make_course(make_teacher(), "C001", name="不限容量", capacity=0)
    first = make_student("s1")
    second = make_student("s2")

    login(client, first.user.username)
    assert client.post(f"/score/enroll/{course.id}").status_code == 302
    client.post("/auth/logout")
    login(client, second.user.username)
    assert client.post(f"/score/enroll/{course.id}").status_code == 302

    assert enrollment_count() == 2


def test_admin_can_edit_capacity_to_zero_with_enrolled_students(
    app: Flask, client: FlaskClient
):
    """R5 的"容量不得小于已选人数"只约束正数容量；0 = 不限，不应被它挡住。"""
    course = make_course(make_teacher(), "C001", capacity=2)
    enroll(make_student("s1"), course)
    enroll(make_student("s2"), course)
    login(client, make_user("admin1", "admin").username)

    response = client.post(
        f"/admin/courses/{course.id}/edit",
        data={
            "code": "C001",
            "name": "课程",
            "credit": "3",
            "hours": "48",
            "semester": "2025-2026-1",
            "capacity": "0",
            "teacher_id": "0",
        },
    )

    assert response.status_code == 302
    db.session.expire_all()
    assert db.session.get(Course, course.id).capacity == 0


def test_enroll_missing_course_is_404(app: Flask, client: FlaskClient):
    student = make_student("s1")
    login(client, student.user.username)
    assert client.post("/score/enroll/999999").status_code == 404


def test_enroll_requires_student_role(app: Flask, client: FlaskClient):
    """教师 / 管理员没有"给自己选课"的场景；未登录跳登录页。"""
    course = make_course(make_teacher(), "C001")
    admin = make_user("admin1", "admin")
    teacher = make_teacher("tea2")

    login(client, admin.username)
    assert client.post(f"/score/enroll/{course.id}").status_code == 403

    client.post("/auth/logout")
    login(client, teacher.user.username)
    assert client.post(f"/score/enroll/{course.id}").status_code == 403

    client.post("/auth/logout")
    anonymous = client.post(f"/score/enroll/{course.id}")
    assert anonymous.status_code == 302
    assert "/auth/login" in anonymous.headers["Location"]

    assert enrollment_count() == 0


def test_student_without_profile_gets_friendly_error(app: Flask, client: FlaskClient):
    """账号存在但缺学生档案：页面与选课动作都不能 500。"""
    course = make_course(make_teacher(), "C001")
    login(client, make_user("student1", "student").username)

    page = client.get("/score/enroll")
    assert page.status_code == 200
    assert "没有关联的学生档案" in page.get_data(as_text=True)

    response = client.post(f"/score/enroll/{course.id}", follow_redirects=True)
    assert response.status_code == 200
    assert "没有关联的学生档案" in response.get_data(as_text=True)
    assert enrollment_count() == 0


# --------------------------------------------------------------------------- #
# 退课：本人 / 他人 / 成绩保护
# --------------------------------------------------------------------------- #
def test_student_can_drop_own_enrollment(app: Flask, client: FlaskClient):
    course = make_course(make_teacher(), "C001", name="可退课")
    student = make_student("s1")
    enrollment = enroll(student, course)
    login(client, student.user.username)

    response = client.post(
        f"/score/enrollments/{enrollment.id}/drop",
        data={"next": "/score/my-courses"},
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert "已退选课程" in response.get_data(as_text=True)
    assert enrollment_count() == 0


def test_drop_is_blocked_when_score_exists(app: Flask, client: FlaskClient):
    """业务规则：已出成绩的课程不允许退课（学生与管理员都一样）。"""
    course = make_course(make_teacher(), "C001", name="已出成绩")
    student = make_student("s1")
    enrollment = enroll(student, course, score=88.0)

    login(client, student.user.username)
    student_response = client.post(
        f"/score/enrollments/{enrollment.id}/drop", follow_redirects=True
    )
    assert student_response.status_code == 200
    assert "不允许退课" in student_response.get_data(as_text=True)
    assert enrollment_count() == 1

    client.post("/auth/logout")
    login(client, make_user("admin1", "admin").username)
    admin_response = client.post(
        f"/score/enrollments/{enrollment.id}/drop", follow_redirects=True
    )
    assert admin_response.status_code == 200
    assert "不允许退课" in admin_response.get_data(as_text=True)
    assert enrollment_count() == 1


def test_student_cannot_drop_someone_elses_enrollment(app: Flask, client: FlaskClient):
    """行级校验：换一个 enrollment id 也退不了别人的课。"""
    course = make_course(make_teacher(), "C001")
    owner = make_student("s1")
    other = make_student("s2")
    enrollment = enroll(owner, course)
    login(client, other.user.username)

    response = client.post(f"/score/enrollments/{enrollment.id}/drop")

    assert response.status_code == 403
    assert "只能退选你自己的课程" in response.get_data(as_text=True)
    assert enrollment_count() == 1


def test_admin_can_drop_any_enrollment(app: Flask, client: FlaskClient):
    course = make_course(make_teacher(), "C001")
    enrollment = enroll(make_student("s1"), course)
    login(client, make_user("admin1", "admin").username)

    response = client.post(f"/score/enrollments/{enrollment.id}/drop")

    assert response.status_code == 302
    assert enrollment_count() == 0


def test_teacher_cannot_drop_enrollment(app: Flask, client: FlaskClient):
    """权限矩阵：选课 / 退课 teacher ❌ —— 即使是自己教的课也不行。"""
    teacher = make_teacher()
    course = make_course(teacher, "C001")
    enrollment = enroll(make_student("s1"), course)
    login(client, teacher.user.username)

    response = client.post(f"/score/enrollments/{enrollment.id}/drop")

    assert response.status_code == 403
    assert enrollment_count() == 1


def test_drop_missing_enrollment_is_404(app: Flask, client: FlaskClient):
    login(client, make_user("admin1", "admin").username)
    assert client.post("/score/enrollments/999999/drop").status_code == 404


def test_drop_ignores_offsite_next(app: Flask, client: FlaskClient):
    """``next=//evil.com`` 不能变成开放重定向。"""
    course = make_course(make_teacher(), "C001")
    student = make_student("s1")
    enrollment = enroll(student, course)
    login(client, student.user.username)

    response = client.post(
        f"/score/enrollments/{enrollment.id}/drop",
        data={"next": "//evil.com"},
    )

    assert response.status_code == 302
    assert response.headers["Location"] == "/score/my-courses"
    assert enrollment_count() == 0


def test_post_only_actions_reject_get(app: Flask, client: FlaskClient):
    course = make_course(make_teacher(), "C001")
    enrollment = enroll(make_student("s1"), course)
    login(client, "s1")

    assert client.get(f"/score/enroll/{course.id}").status_code == 405
    assert client.get(f"/score/enrollments/{enrollment.id}/drop").status_code == 405
    assert client.get(f"/score/courses/{course.id}/enroll").status_code in (403, 405)


# --------------------------------------------------------------------------- #
# 选课名单：管理员代选 / 移出，教师只读
# --------------------------------------------------------------------------- #
def test_admin_can_add_student_to_course(app: Flask, client: FlaskClient):
    course = make_course(make_teacher(), "C001", name="数据结构")
    student = make_student("s1")
    login(client, make_user("admin1", "admin").username)

    response = client.post(
        f"/score/courses/{course.id}/enroll",
        data={"student_id": str(student.id)},
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert "已将学生" in response.get_data(as_text=True)
    assert enrollment_of(student, course) is not None


def test_roster_add_rejects_duplicate(app: Flask, client: FlaskClient):
    course = make_course(make_teacher(), "C001")
    student = make_student("s1")
    enroll(student, course)
    login(client, make_user("admin1", "admin").username)

    response = client.post(
        f"/score/courses/{course.id}/enroll",
        data={"student_id": str(student.id)},
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert "不能重复添加" in response.get_data(as_text=True)
    assert enrollment_count() == 1


def test_roster_add_rejects_full_course(app: Flask, client: FlaskClient):
    course = make_course(make_teacher(), "C001", capacity=1)
    enroll(make_student("s1"), course)
    late = make_student("s2")
    login(client, make_user("admin1", "admin").username)

    response = client.post(
        f"/score/courses/{course.id}/enroll",
        data={"student_id": str(late.id)},
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert "已满" in response.get_data(as_text=True)
    assert enrollment_count() == 1


def test_roster_add_requires_admin(app: Flask, client: FlaskClient):
    course = make_course(make_teacher(), "C001")
    student = make_student("s1")

    teacher = make_teacher("tea2")
    login(client, teacher.user.username)
    assert (
        client.post(
            f"/score/courses/{course.id}/enroll",
            data={"student_id": str(student.id)},
        ).status_code
        == 403
    )

    client.post("/auth/logout")
    login(client, student.user.username)
    assert (
        client.post(
            f"/score/courses/{course.id}/enroll",
            data={"student_id": str(student.id)},
        ).status_code
        == 403
    )
    assert enrollment_count() == 0


def test_roster_add_unknown_student_is_404(app: Flask, client: FlaskClient):
    course = make_course(make_teacher(), "C001")
    login(client, make_user("admin1", "admin").username)

    response = client.post(
        f"/score/courses/{course.id}/enroll", data={"student_id": "999999"}
    )

    assert response.status_code == 404


def test_roster_add_missing_course_is_404(app: Flask, client: FlaskClient):
    login(client, make_user("admin1", "admin").username)
    assert client.post("/score/courses/999999/enroll", data={"student_id": "1"}).status_code == 404


def test_roster_add_requires_student_selection(app: Flask, client: FlaskClient):
    """未选择学生（0 / 空值）时给出表单错误，不落库。"""
    course = make_course(make_teacher(), "C001")
    login(client, make_user("admin1", "admin").username)

    response = client.post(
        f"/score/courses/{course.id}/enroll",
        data={"student_id": "0"},
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert "请选择要加入课程的学生" in response.get_data(as_text=True)
    assert enrollment_count() == 0


def test_duplicate_enrollment_race_falls_back_to_unique_constraint(
    app: Flask, client: FlaskClient, monkeypatch
):
    """并发重复提交：绕过视图里的存在性检查后，仍由数据库唯一约束兜底。

    这里把 ``_find_enrollment`` 临时改成"永远查不到"，模拟两个请求同时通过
    存在性检查的竞态；第二次 ``commit`` 会触发 ``IntegrityError``，视图应回滚并提示。
    """
    from gradeapp import score as score_module

    course = make_course(make_teacher(), "C001")
    student = make_student("s1")
    enroll(student, course)
    login(client, student.user.username)
    monkeypatch.setattr(score_module, "_find_enrollment", lambda *args, **kwargs: None)

    response = client.post(f"/score/enroll/{course.id}", follow_redirects=True)

    assert response.status_code == 200
    assert "不能重复选课" in response.get_data(as_text=True)
    assert enrollment_count() == 1


def test_course_detail_is_roster_page_for_admin_and_teacher(
    app: Flask, client: FlaskClient
):
    """选课名单页：管理员看到"添加学生 / 移出课程"，教师只读。"""
    teacher = make_teacher()
    course = make_course(teacher, "C001", name="数据结构")
    student = make_student("s1")
    enrollment = enroll(student, course)

    login(client, make_user("admin1", "admin").username)
    admin_html = client.get(f"/score/courses/{course.id}").get_data(as_text=True)
    assert "选课名单" in admin_html
    assert "添加学生" in admin_html
    assert "移出课程" in admin_html
    assert student.name in admin_html
    assert f"/score/enrollments/{enrollment.id}/drop" in admin_html

    client.post("/auth/logout")
    login(client, teacher.user.username)
    teacher_html = client.get(f"/score/courses/{course.id}").get_data(as_text=True)
    assert "选课名单" in teacher_html
    assert "添加学生" not in teacher_html
    assert "移出课程" not in teacher_html
    assert "只读" in teacher_html


def test_student_roster_shows_only_own_drop_action(app: Flask, client: FlaskClient):
    """学生能看名单，但操作列只有自己那条有"退课"。"""
    course = make_course(make_teacher(), "C001")
    me = make_student("s1")
    other = make_student("s2")
    mine = enroll(me, course)
    theirs = enroll(other, course)
    login(client, me.user.username)

    html = client.get(f"/score/courses/{course.id}").get_data(as_text=True)

    assert f"/score/enrollments/{mine.id}/drop" in html
    assert f"/score/enrollments/{theirs.id}/drop" not in html


# --------------------------------------------------------------------------- #
# 选课页 / 我的课程 / 导航
# --------------------------------------------------------------------------- #
def test_enroll_page_lists_status_and_filters(app: Flask, client: FlaskClient):
    teacher = make_teacher()
    selected = make_course(teacher, "C001", name="数据结构", semester="2025-2026-1")
    available = make_course(teacher, "C002", name="操作系统", semester="2025-2026-2")
    student = make_student("s1")
    enroll(student, selected)
    login(client, student.user.username)

    html = client.get("/score/enroll").get_data(as_text=True)
    assert "数据结构" in html and "操作系统" in html
    assert "已选" in html and "可选" in html
    assert f"/score/enrollments/" in html  # 已选课程有退课入口

    filtered = client.get("/score/enroll", query_string={"q": "C002"}).get_data(as_text=True)
    assert "操作系统" in filtered
    assert "数据结构" not in filtered

    by_semester = client.get(
        "/score/enroll", query_string={"semester": "2025-2026-1"}
    ).get_data(as_text=True)
    assert "数据结构" in by_semester
    assert "操作系统" not in by_semester
    assert available.code not in by_semester


def test_full_course_is_marked_on_enroll_page(app: Flask, client: FlaskClient):
    course = make_course(make_teacher(), "C001", name="满员课", capacity=1)
    enroll(make_student("s1"), course)
    login(client, make_student("s2").user.username)

    html = client.get("/score/enroll").get_data(as_text=True)

    assert "已满" in html
    assert "名额已满" in html
    assert f"/score/enroll/{course.id}" not in html


def test_my_courses_shows_drop_state_for_student(app: Flask, client: FlaskClient):
    teacher = make_teacher()
    droppable = make_course(teacher, "C001", name="可退课")
    graded = make_course(teacher, "C002", name="已出成绩")
    student = make_student("s1")
    drop_enrollment = enroll(student, droppable)
    graded_enrollment = enroll(student, graded, score=90.0)
    login(client, student.user.username)

    html = client.get("/score/my-courses").get_data(as_text=True)

    assert "我的成绩" in html
    assert f"/score/enrollments/{drop_enrollment.id}/drop" in html
    assert f"/score/enrollments/{graded_enrollment.id}/drop" not in html
    assert "已有成绩，不可退课" in html


def test_r6_nav_entries_by_role(app: Flask):
    """学生看到「选课」，管理员看到「选课名单」，教师看不到学生选课入口。"""
    make_student("s1")
    make_teacher("t1")
    make_user("admin1", "admin")

    student_client = app.test_client()
    login(student_client, "s1")
    student_html = student_client.get("/").get_data(as_text=True)
    assert "/score/enroll" in student_html
    assert "选课" in student_html

    admin_client = app.test_client()
    login(admin_client, "admin1")
    admin_html = admin_client.get("/").get_data(as_text=True)
    assert "选课名单" in admin_html
    assert "/score/my-courses" in admin_html
    assert "/score/enroll" not in admin_html

    teacher_client = app.test_client()
    login(teacher_client, "t1")
    teacher_html = teacher_client.get("/").get_data(as_text=True)
    assert "/score/my-courses" in teacher_html
    assert "/score/enroll" not in teacher_html
