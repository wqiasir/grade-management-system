"""R10 验证：Excel 导入导出。

覆盖计划第 6 节 R10 的完成标准：
1. **导出**：课程成绩表（含空成绩名单，可当导入模板）与学生本人成绩单；
   文件是合法的 .xlsx，表头与内容正确；
2. **导入**：按表头回填成绩，部分保存 + 逐条错误报告；留空 = 不修改；
   同考核类型重复导入 = 更新；
3. **校验**：学号不在名单内、非数字、超范围逐条拒绝；非 .xlsx 文件被拒；
4. **权限**：Excel 导入导出走同一套行级校验——teacher 仅自授课程、student 仅导出本人成绩单、
   写接口一律 POST + 行内 403 无副作用。

openpyxl 在测试里同时当"写入方"（构造上传文件）与"读取方"（断言导出内容）。
"""

from __future__ import annotations

import io

from flask import Flask
from flask.testing import FlaskClient
from openpyxl import Workbook, load_workbook
from sqlalchemy import func, select

from gradeapp.extensions import db
from gradeapp.models import Course, Enrollment, Score, Student, Teacher, User

PASSWORD = "pw-123456"


# --------------------------------------------------------------------------- #
# 辅助：造数据 / 登录 / 构造 Excel
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
        class_name="计算机2501", enroll_year=2025,
    )
    db.session.add(student)
    db.session.commit()
    return student


def make_teacher(username: str = "tea1") -> Teacher:
    user = make_user(username, "teacher")
    teacher = Teacher(user_id=user.id, tno=f"T{user.id:04d}", name=user.real_name, title="讲师", department="计算机学院")
    db.session.add(teacher)
    db.session.commit()
    return teacher


def make_course(teacher: Teacher | None, code: str = "C001") -> Course:
    course = Course(code=code, name="课程" + code, credit=3.0, hours=48,
                    teacher_id=teacher.id if teacher else None, semester="2025-2026-1", capacity=60)
    db.session.add(course)
    db.session.commit()
    return course


def enroll(student: Student, course: Course) -> Enrollment:
    enrollment = Enrollment(student_id=student.id, course_id=course.id)
    db.session.add(enrollment)
    db.session.commit()
    return enrollment


def score_count() -> int:
    return int(db.session.scalar(select(func.count()).select_from(Score)) or 0)


def login(client: FlaskClient, username: str, password: str = PASSWORD) -> None:
    response = client.post("/auth/login", data={"username": username, "password": password})
    assert response.status_code == 302, "登录未成功"


def build_xlsx(rows: list[list], header: list[str] | None = None) -> io.BytesIO:
    """构造上传用的 .xlsx 内存文件（header 缺省为导出模板表头）。"""
    wb = Workbook()
    ws = wb.active
    ws.append(header or ["学号", "姓名", "班级", "平时", "期中", "期末"])
    for row in rows:
        ws.append(row)
    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    return buffer


def upload(client: FlaskClient, url: str, buffer: io.BytesIO | None, filename: str = "grades.xlsx"):
    data = {"file": (buffer, filename)} if buffer is not None else {}
    return client.post(url, data=data, content_type="multipart/form-data", follow_redirects=True)


# --------------------------------------------------------------------------- #
# 导出
# --------------------------------------------------------------------------- #
def test_teacher_exports_course_sheet_with_scores(app: Flask, client: FlaskClient):
    """教师导出自授课程：表头正确、名单齐全、已有成绩回填到对应考核类型列。"""
    teacher = make_teacher("t1")
    course = make_course(teacher, "C001")
    s1, s2 = make_student("s1", sno="2025001"), make_student("s2", sno="2025002")
    e1, e2 = enroll(s1, course), enroll(s2, course)
    db.session.add(Score(enrollment_id=e1.id, exam_type="期末", score=88.5))
    db.session.add(Score(enrollment_id=e1.id, exam_type="平时", score=90))
    db.session.commit()
    login(client, "t1")

    response = client.get(f"/score/courses/{course.id}/export")

    assert response.status_code == 200
    assert response.mimetype == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    assert "attachment" in response.headers["Content-Disposition"]
    assert ".xlsx" in response.headers["Content-Disposition"]

    ws = load_workbook(io.BytesIO(response.data)).active
    assert [c.value for c in ws[1][:6]] == ["学号", "姓名", "班级", "平时", "期中", "期末"]
    body = {row[0]: row for row in ws.iter_rows(min_row=2, values_only=True)}
    assert body["2025001"][3] == 90 and body["2025001"][5] == 88.5 and body["2025001"][4] is None  # 期中留白
    assert body["2025002"][3] is None and body["2025002"][4] is None and body["2025002"][5] is None


def test_teacher_cannot_export_others_course(app: Flask, client: FlaskClient):
    """教师导出他人课程 → 403；学生导出课程成绩 → 403。"""
    owner, other = make_teacher("owner"), make_teacher("other")
    course = make_course(owner, "C001")
    enroll(make_student("s1"), course)

    other_client = app.test_client()
    login(other_client, "other")
    assert other_client.get(f"/score/courses/{course.id}/export").status_code == 403

    student_client = app.test_client()
    login(student_client, "s1")
    assert student_client.get(f"/score/courses/{course.id}/export").status_code == 403


def test_admin_exports_any_course(app: Flask, client: FlaskClient):
    """管理员可导出任意课程；未排课（无教师）的课程也允许。"""
    make_teacher("t1")
    course = make_course(None, "C201")
    login(client, make_user("admin1", "admin").username)

    response = client.get(f"/score/courses/{course.id}/export")
    assert response.status_code == 200
    ws = load_workbook(io.BytesIO(response.data)).active
    assert ws.max_row == 1  # 没有学生选课：只有表头


def test_student_exports_own_transcript(app: Flask, client: FlaskClient):
    """学生导出本人成绩单：包含学期 / 课程 / 各考核类型成绩。"""
    teacher = make_teacher("t1")
    c1 = make_course(teacher, "C001")
    c2 = make_course(teacher, "C002")
    me = make_student("s1", sno="2025001")
    enroll(me, c2, )  # 未出成绩
    e1 = enroll(me, c1)
    db.session.add(Score(enrollment_id=e1.id, exam_type="期末", score=77))
    db.session.commit()
    login(client, "s1")

    response = client.get("/score/my-scores/export")

    assert response.status_code == 200
    ws = load_workbook(io.BytesIO(response.data)).active
    header = [c.value for c in ws[1]]
    assert header[:5] == ["学期", "课程代码", "课程名称", "授课教师", "学分"]
    rows = list(ws.iter_rows(min_row=2, values_only=True))
    assert len(rows) == 2
    graded = next(r for r in rows if r[1] == "C001")
    assert graded[7] == 77  # 第 8 列 = 期末（前 5 列身份信息 + 平时/期中/期末）
    ungraded = next(r for r in rows if r[1] == "C002")
    assert ungraded[7] is None  # 未出成绩留白（openpyxl 空单元格读回 None）


def test_student_transcript_export_requires_profile(app: Flask, client: FlaskClient):
    """无学生档案的账号导出成绩单 → 友好提示并回成绩页，不 500。"""
    make_user("ghost", "student")
    login(client, "ghost")

    response = client.get("/score/my-scores/export", follow_redirects=True)
    assert "没有关联的学生档案" in response.get_data(as_text=True)


def test_student_cannot_use_course_excel_routes(app: Flask, client: FlaskClient):
    """学生不能导入课程成绩（POST 403 无副作用），也没有教师视角的导出。"""
    teacher = make_teacher("t1")
    course = make_course(teacher, "C001")
    student = make_student("s1")
    enroll(student, course)
    login(client, "s1")

    response = upload(client, f"/score/courses/{course.id}/import",
                      build_xlsx([[student.sno, student.name, "计算机2501", "", "", "100"]]))
    assert response.status_code == 403
    assert score_count() == 0



# --------------------------------------------------------------------------- #
# 导入
# --------------------------------------------------------------------------- #
def test_import_grades_from_exported_template(app: Flask, client: FlaskClient):
    """导出 → 填分数 → 导入：成绩落库且 updated_by 记录操作人。"""
    teacher = make_teacher("t1")
    course = make_course(teacher, "C001")
    s1, s2 = make_student("s1", sno="2025001"), make_student("s2", sno="2025002")
    e1, e2 = enroll(s1, course), enroll(s2, course)
    login(client, "t1")

    # 先导出拿模板，再原样改分上传
    template = client.get(f"/score/courses/{course.id}/export").data
    wb = load_workbook(io.BytesIO(template))
    ws = wb.active
    ws.cell(row=2, column=6, value=92)     # s1 期末
    ws.cell(row=3, column=4, value=85)     # s2 平时
    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)

    response = upload(client, f"/score/courses/{course.id}/import", buffer)

    html = response.get_data(as_text=True)
    assert "成功 2 条" in html
    rows = {r.enrollment_id: r for r in db.session.scalars(select(Score)).all()}
    assert rows[e1.id].score == 92 and rows[e1.id].exam_type == "期末"
    assert rows[e2.id].score == 85 and rows[e2.id].exam_type == "平时"
    assert {r.updated_by for r in rows.values()} == {teacher.user_id}


def test_import_reports_row_errors_and_keeps_valid_rows(app: Flask, client: FlaskClient):
    """学号不在名单 / 非数字 / 超范围逐条报告；有效行照常导入（部分保存）。"""
    teacher = make_teacher("t1")
    course = make_course(teacher, "C001")
    s1 = make_student("s1", sno="2025001")
    e1 = enroll(s1, course)
    login(client, "t1")

    buffer = build_xlsx([
        ["2025001", s1.name, "计算机2501", "", "", "95"],    # 有效
        ["9999999", "陌生人", "无", "", "", "66"],           # 学号不在名单
        ["2025001", s1.name, "计算机2501", "abc", "", ""],   # 非数字
        ["2025001", s1.name, "计算机2501", "", "", "120"],   # 超范围
    ])
    response = upload(client, f"/score/courses/{course.id}/import", buffer)

    html = response.get_data(as_text=True)
    assert "成功 1 条" in html and "失败 3 条" in html
    assert "不在本课程名单内" in html
    assert "不是有效数字" in html
    assert "不在 0~100 范围内" in html
    saved = list(db.session.scalars(select(Score)).all())
    assert len(saved) == 1 and saved[0].enrollment_id == e1.id and saved[0].score == 95


def test_import_blank_cells_and_reimport_updates(app: Flask, client: FlaskClient):
    """留空不修改；同一考核类型再次导入 = 更新而不是新增。"""
    teacher = make_teacher("t1")
    course = make_course(teacher, "C001")
    s1 = make_student("s1", sno="2025001")
    e1 = enroll(s1, course)
    db.session.add(Score(enrollment_id=e1.id, exam_type="期末", score=60))
    db.session.commit()
    login(client, "t1")

    # 全部留空：什么都不改
    response = upload(client, f"/score/courses/{course.id}/import",
                      build_xlsx([["2025001", s1.name, "计算机2501", "", "", ""]]))
    assert "没有需要导入的成绩" in response.get_data(as_text=True)
    assert score_count() == 1

    # 期末改 99：更新原记录，不新增
    upload(client, f"/score/courses/{course.id}/import",
           build_xlsx([["2025001", s1.name, "计算机2501", "", "", "99"]]))
    rows = list(db.session.scalars(select(Score)).all())
    assert len(rows) == 1 and rows[0].score == 99 and rows[0].exam_type == "期末"


def test_import_rejects_non_xlsx_and_bad_files(app: Flask, client: FlaskClient):
    """非 .xlsx 后缀与损坏文件被拒绝并提示，不落库。"""
    teacher = make_teacher("t1")
    course = make_course(teacher, "C001")
    enroll(make_student("s1", sno="2025001"), course)
    login(client, "t1")

    response = upload(client, f"/score/courses/{course.id}/import",
                      io.BytesIO(b"not an excel file"), filename="notes.csv")
    assert "只支持 .xlsx" in response.get_data(as_text=True)

    response = upload(client, f"/score/courses/{course.id}/import",
                      io.BytesIO(b"fake-bytes"), filename="fake.xlsx")
    assert "解析失败" in response.get_data(as_text=True)

    response = upload(client, f"/score/courses/{course.id}/import", None)
    assert "请选择要上传的 Excel 文件" in response.get_data(as_text=True)

    # 表头缺学号列
    response = upload(client, f"/score/courses/{course.id}/import",
                      build_xlsx([["2025001", "1", "1", "1", "1", "1"]], header=["序号", "a", "b", "c", "d", "e"]))
    assert "表头缺少「学号」列" in response.get_data(as_text=True)

    assert score_count() == 0


def test_import_is_row_level_checked(app: Flask, client: FlaskClient):
    """教师只能导入自己课程的 Excel：他人课程 403 且无副作用。"""
    owner, other = make_teacher("owner"), make_teacher("other")
    course = make_course(owner, "C001")
    s1 = make_student("s1", sno="2025001")
    enroll(s1, course)
    login(other_client := app.test_client(), "other")

    response = upload(other_client, f"/score/courses/{course.id}/import",
                      build_xlsx([["2025001", s1.name, "计算机2501", "", "", "88"]]))
    assert response.status_code == 403
    assert score_count() == 0


def test_excel_guide_page_lists_courses(app: Flask, client: FlaskClient):
    """管理员指引页列出课程与快捷导出入口；教师与学生无该页。"""
    teacher = make_teacher("t1")
    course = make_course(teacher, "C001")
    make_student("s1")
    login(client, make_user("admin1", "admin").username)

    html = client.get("/score/excel").get_data(as_text=True)
    assert course.code in html
    assert f"/score/courses/{course.id}/export" in html

    teacher_client = app.test_client()
    login(teacher_client, "t1")
    assert teacher_client.get("/score/excel").status_code == 403

    student_client = app.test_client()
    login(student_client, "s1")
    assert student_client.get("/score/excel").status_code == 403
