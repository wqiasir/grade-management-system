"""R9 验证：统计报表（Chart.js 图表数据 / 分数段分布 / 班级排名）。

覆盖计划第 6 节 R9 的完成标准：
1. **分数段分布**：固定分箱 <60 / 60~69 / 70~79 / 80~89 / 90~100，边界值归箱正确；
2. **图表数据**：各课程平均分只含已出成绩的课程；页面渲染出图表容器与回退表格；
3. **班级排名**：按平均分排序、及格率口径与汇总一致、未分班有兜底名称；
4. **范围收缩**：admin 全校 / teacher 仅自授 / student 仅本人（学生无班级排名）。

图表的前端渲染不进测试（无 JS 环境）；测试断言的是**服务端算出的数据**与页面上的回退表格。
"""

from __future__ import annotations

import pytest
from flask import Flask
from flask.testing import FlaskClient
from sqlalchemy import select

from gradeapp.extensions import db
from gradeapp.models import Course, Enrollment, Score, Student, Teacher, User
from gradeapp.report import _distribution

PASSWORD = "pw-123456"


# --------------------------------------------------------------------------- #
# 辅助：造数据与登录
# --------------------------------------------------------------------------- #
def make_user(username: str, role: str, *, real_name: str | None = None) -> User:
    user = User(username=username, role=role, real_name=real_name or username)
    user.set_password(PASSWORD)
    db.session.add(user)
    db.session.commit()
    return user


def make_student(username: str = "stu1", *, class_name: str | None = "计算机2501") -> Student:
    user = make_user(username, "student", real_name="学生" + username)
    student = Student(
        user_id=user.id,
        sno=f"S{user.id:04d}",
        name=user.real_name,
        class_name=class_name,
        enroll_year=2025,
    )
    db.session.add(student)
    db.session.commit()
    return student


def make_teacher(username: str = "tea1") -> Teacher:
    user = make_user(username, "teacher", real_name="教师" + username)
    teacher = Teacher(
        user_id=user.id,
        tno=f"T{user.id:04d}",
        name=user.real_name,
        title="讲师",
        department="计算机学院",
    )
    db.session.add(teacher)
    db.session.commit()
    return teacher


def make_course(teacher: Teacher | None, code: str = "C001", *, name: str = "课程") -> Course:
    course = Course(
        code=code, name=name, credit=3.0, hours=48,
        teacher_id=teacher.id if teacher else None,
        semester="2025-2026-1", capacity=60,
    )
    db.session.add(course)
    db.session.commit()
    return course


def enroll(student: Student, course: Course, *, scores: dict[str, float] | None = None) -> Enrollment:
    enrollment = Enrollment(student_id=student.id, course_id=course.id)
    db.session.add(enrollment)
    db.session.commit()
    for exam_type, value in (scores or {}).items():
        db.session.add(Score(enrollment_id=enrollment.id, exam_type=exam_type, score=value))
    db.session.commit()
    return enrollment


def login(client: FlaskClient, username: str, password: str = PASSWORD) -> None:
    response = client.post("/auth/login", data={"username": username, "password": password})
    assert response.status_code == 302, "登录未成功"


# --------------------------------------------------------------------------- #
# 分数段分箱
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("value", "bin_label"),
    [
        (0, "<60"), (59.9, "<60"), (59.999, "<60"),
        (60, "60~69"), (69.999, "60~69"),
        (70, "70~79"), (79.999, "70~79"),
        (80, "80~89"), (89.999, "80~89"),
        (90, "90~100"), (100, "90~100"),
    ],
)
def test_distribution_bins_boundary_values(value: float, bin_label: str) -> None:
    """分箱左闭右开（最后一箱含 100）：60 归 60~69、90 与 100 归 90~100。"""
    result = _distribution([value])
    by_label = {item["label"]: item["count"] for item in result}
    assert by_label[bin_label] == 1
    assert sum(item["count"] for item in result) == 1


def test_distribution_counts_multiple_values() -> None:
    """一批分数的分箱计数与总条数守恒。"""
    values = [45, 55, 60, 65, 75, 85, 95, 100, 99]
    result = _distribution(values)
    assert [item["count"] for item in result] == [2, 2, 1, 1, 3]
    assert sum(item["count"] for item in result) == len(values)


# --------------------------------------------------------------------------- #
# 页面：图表数据与班级排名
# --------------------------------------------------------------------------- #
def test_overview_renders_chart_data_and_fallback_table(
    app: Flask, client: FlaskClient
):
    """报表页渲染图表容器、分数段回退表格与课程平均分表格。"""
    teacher = make_teacher()
    c1 = make_course(teacher, "C001", name="数据结构")
    c2 = make_course(teacher, "C002", name="操作系统")
    s1, s2, s3 = make_student("s1"), make_student("s2"), make_student("s3")
    enroll(s1, c1, scores={"期末": 55})
    enroll(s2, c1, scores={"期末": 95})
    enroll(s3, c2, scores={"期末": 75})
    login(client, make_user("admin1", "admin").username)

    html = client.get("/report/overview").get_data(as_text=True)

    assert 'id="distChart"' in html          # Chart.js 画布
    assert 'id="courseChart"' in html
    assert "chart.js" in html.lower()        # CDN 引入
    assert "&lt;60" in html and "90~100" in html  # <60 会被 HTML 转义
    assert "C001" in html and "C002" in html  # 课程平均分数据
    assert "班级排名（按平均分）" in html
    assert "计算机2501" in html


def test_overview_class_ranking_orders_by_average(app: Flask, client: FlaskClient):
    """班级排名按平均分降序，两名（无成绩）班级垫底；未分班有兜底名称。"""
    teacher = make_teacher()
    course = make_course(teacher, "C001")
    class_a = make_student("s1", class_name="计算机2501")
    class_b = make_student("s2", class_name="计算机2502")
    nobody = make_student("s3", class_name=None)
    enroll(class_a, course, scores={"期末": 90})
    enroll(class_b, course, scores={"期末": 60})
    enroll(nobody, course, scores={"期末": 70})
    login(client, make_user("admin1", "admin").username)

    html = client.get("/report/overview").get_data(as_text=True)

    first = html.index("计算机2501")          # 平均 90，第 1
    second = html.index("未分班")             # 平均 70，第 2
    third = html.index("计算机2502")          # 平均 60，第 3
    assert first < second < third
    assert "90.0" in html and "60.0" in html


def test_overview_scope_shrinks_by_role(app: Flask, client: FlaskClient):
    """范围收缩：教师只看到自授课程的统计；学生看到本人范围且没有班级排名。"""
    mine = make_teacher("mine")
    other = make_teacher("other")
    my_course = make_course(mine, "CMY01", name="我的课")
    other_course = make_course(other, "COTH", name="别人的课")
    s1, s2 = make_student("s1"), make_student("s2")
    enroll(s1, my_course, scores={"期末": 80})
    enroll(s2, other_course, scores={"期末": 90})

    teacher_client = app.test_client()
    login(teacher_client, "mine")
    html = teacher_client.get("/report/overview").get_data(as_text=True)
    assert "CMY01" in html and "COTH" not in html
    assert "我的课" in html and "别人的课" not in html

    student_client = app.test_client()
    login(student_client, "s1")
    html = student_client.get("/report/overview").get_data(as_text=True)
    assert "仅你本人的选课与成绩" in html
    assert "班级排名（按平均分）" not in html  # 学生视角不提供班级排名
    assert "80.0" in html


def test_overview_without_any_scores_renders_empty_charts(
    app: Flask, client: FlaskClient
):
    """范围内没有任何成绩时：分布全 0、课程平均分图表缺省、页面不报错。"""
    make_teacher()
    make_course(None, "C001")
    make_student("s1")
    login(client, make_user("admin1", "admin").username)

    html = client.get("/report/overview").get_data(as_text=True)

    assert 'id="distChart"' in html
    assert "各课程平均分" not in html       # 无成绩课程不进图
    assert "班级排名（按平均分）" not in html
    assert "当前范围内还没有课程数据。" not in html  # 课程存在，只是没有成绩
