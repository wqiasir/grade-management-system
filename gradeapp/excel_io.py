"""Excel 导入导出蓝图（R10）。

- 导出（GET）：
  - ``/score/courses/<id>/export``      一门课程的成绩表（admin 全部 / teacher 仅自授），
    导出文件即导入模板：学号 / 姓名 / 班级 / 平时 / 期中 / 期末；
  - ``/score/my-scores/export``         学生本人成绩单（按学期分行的课程 × 考核类型）。
- 导入（POST）：
  - ``/score/courses/<id>/import``      上传 .xlsx 按表头回填成绩（admin 全部 / teacher 仅自授；
    学生 403）。逐行校验：学号必须在课程名单内、分数为 0~100 的数字、考核类型列以表头为准；
    **部分保存**——有效行照常导入，错误行逐条报告（与 R7 网页录入同一策略）；
    ``updated_by`` 记录操作人。

Excel 列与成绩唯一约束对齐：同一行同一考核类型只会产生一条 ``score`` 记录
（``uq_score_enrollment_exam_type``），重复导入 = 更新。
"""
from __future__ import annotations

import io
from datetime import datetime, timezone

from flask import Blueprint, Response, flash, g, redirect, render_template, request, url_for
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from .decorators import guard_course_access, login_required, role_label, role_required
from .extensions import db
from .models import EXAM_TYPES, Course, Enrollment, Score, Student

bp = Blueprint("excel", __name__, url_prefix="/score")

#: 导出 / 导入共用的列定义（前 3 列是身份信息，其后是各考核类型）
EXPORT_COLUMNS: tuple[str, ...] = ("学号", "姓名", "班级") + EXAM_TYPES

_HEADER_FILL = PatternFill("solid", fgColor="1D4ED8")
_HEADER_FONT = Font(color="FFFFFF", bold=True)


def _styled_header_row(ws, columns) -> None:
    for col, title in enumerate(columns, start=1):
        cell = ws.cell(row=1, column=col, value=title)
        cell.fill = _HEADER_FILL
        cell.font = _HEADER_FONT
        cell.alignment = Alignment(horizontal="center")
        ws.column_dimensions[get_column_letter(col)].width = max(len(title) * 2 + 2, 12)
    ws.freeze_panes = "A2"


def _score_value(score_map: dict[tuple[int, str], Score], enrollment_id: int, exam_type: str):
    """取某选课记录某考核类型的分数；无则返回 None（单元格留白，openpyxl 空串也存为 None）。"""
    record = score_map.get((enrollment_id, exam_type))
    if record is None:
        return None
    value = record.score
    return int(value) if value == int(value) else value


def _workbook_response(wb: Workbook, filename: str) -> Response:
    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M")
    return Response(
        buffer.getvalue(),
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{filename}_{timestamp}.xlsx"},
    )


# --------------------------------------------------------------------------- #
# 导出：课程成绩表（即导入模板）
# --------------------------------------------------------------------------- #
@bp.get("/courses/<int:course_id>/export")
@role_required("admin", "teacher")
@login_required
def export_course(course_id: int):
    """导出一门课程的成绩表（空成绩也导名单，作为导入模板）。"""
    course = db.get_or_404(Course, course_id)
    if denial := guard_course_access(course):
        return denial

    enrollments = db.session.scalars(
        select(Enrollment)
        .options(selectinload(Enrollment.student))
        .where(Enrollment.course_id == course.id)
        .order_by(Enrollment.student_id)
    ).all()
    score_map = {
        (s.enrollment_id, s.exam_type): s
        for s in db.session.scalars(
            select(Score).join(Enrollment, Score.enrollment_id == Enrollment.id).where(Enrollment.course_id == course.id)
        ).all()
    }

    wb = Workbook()
    ws = wb.active
    ws.title = "成绩"
    _styled_header_row(ws, EXPORT_COLUMNS)
    for index, e in enumerate(enrollments, start=2):
        student = e.student
        ws.cell(row=index, column=1, value=student.sno if student else "")
        ws.cell(row=index, column=2, value=student.name if student else "")
        ws.cell(row=index, column=3, value=student.class_name if student else "")
        for offset, exam_type in enumerate(EXAM_TYPES, start=4):
            ws.cell(row=index, column=offset, value=_score_value(score_map, e.id, exam_type))

    return _workbook_response(wb, f"成绩_{course.code}_{course.name}")


# --------------------------------------------------------------------------- #
# 导出：学生本人成绩单
# --------------------------------------------------------------------------- #
@bp.get("/my-scores/export")
@role_required("student")
@login_required
def export_my_scores():
    """学生导出本人成绩单（Excel 导出矩阵里 student 的"仅本人"）。"""
    student = g.user.student
    if not student:
        flash("当前账号没有关联的学生档案，无法导出成绩单。", "error")
        return redirect(url_for("score.my_scores"))

    enrollments = db.session.scalars(
        select(Enrollment)
        .options(selectinload(Enrollment.course).selectinload(Course.teacher), selectinload(Enrollment.scores))
        .join(Course, Enrollment.course_id == Course.id)
        .where(Enrollment.student_id == student.id)
        .order_by(Course.semester.desc(), Course.code)
    ).all()

    wb = Workbook()
    ws = wb.active
    ws.title = "我的成绩单"
    columns = ("学期", "课程代码", "课程名称", "授课教师", "学分") + EXAM_TYPES
    _styled_header_row(ws, columns)
    for index, e in enumerate(enrollments, start=2):
        course = e.course
        ws.cell(row=index, column=1, value=course.semester)
        ws.cell(row=index, column=2, value=course.code)
        ws.cell(row=index, column=3, value=course.name)
        ws.cell(row=index, column=4, value=course.teacher.name if course.teacher else "待安排")
        ws.cell(row=index, column=5, value=course.credit)
        by_type = {s.exam_type: s.score for s in e.scores}
        for offset, exam_type in enumerate(EXAM_TYPES, start=6):
            value = by_type.get(exam_type)
            if value is not None:
                ws.cell(row=index, column=offset, value=int(value) if value == int(value) else value)

    return _workbook_response(wb, f"成绩单_{student.sno}_{student.name}")


# --------------------------------------------------------------------------- #
# 导入：课程成绩
# --------------------------------------------------------------------------- #
@bp.post("/courses/<int:course_id>/import")
@role_required("admin", "teacher")
@login_required
def import_course(course_id: int):
    """从 Excel 导入成绩：部分保存 + 逐条错误报告（与 R7 网页录入同一策略）。"""
    course = db.get_or_404(Course, course_id)
    if denial := guard_course_access(course):
        return denial

    back_url = url_for("score.course_detail", course_id=course.id)

    upload = request.files.get("file")
    if upload is None or not upload.filename:
        flash("请选择要上传的 Excel 文件（.xlsx）。", "error")
        return redirect(back_url)
    if not upload.filename.lower().endswith(".xlsx"):
        flash("只支持 .xlsx 文件，请用「导出成绩」生成的文件填写后上传。", "error")
        return redirect(back_url)

    try:
        sheet = load_workbook(upload, read_only=True, data_only=True).active
        rows = list(sheet.iter_rows(values_only=True))
    except Exception:
        flash("Excel 文件解析失败：请确认没有加密，且是从「导出成绩」下载的文件。", "error")
        return redirect(back_url)

    if not rows:
        flash("Excel 文件是空的。", "error")
        return redirect(back_url)

    header = [str(cell).strip() if cell is not None else "" for cell in rows[0]]
    try:
        sno_col = header.index("学号")
    except ValueError:
        flash("表头缺少「学号」列：请用「导出成绩」生成的文件填写后上传。", "error")
        return redirect(back_url)
    exam_cols = {col: header[col] for col in range(len(header)) if header[col] in EXAM_TYPES}

    enrollments = {
        e.student.sno: e
        for e in db.session.scalars(
            select(Enrollment).options(selectinload(Enrollment.student)).where(Enrollment.course_id == course.id)
        ).all()
        if e.student
    }
    existing = {
        (s.enrollment_id, s.exam_type): s
        for s in db.session.scalars(
            select(Score).join(Enrollment, Score.enrollment_id == Enrollment.id).where(Enrollment.course_id == course.id)
        ).all()
    }

    imported, errors = 0, []
    for line, row in enumerate(rows[1:], start=2):
        if row is None or all(cell is None or str(cell).strip() == "" for cell in row):
            continue  # 跳过整行空白
        sno = str(row[sno_col]).strip() if sno_col < len(row) and row[sno_col] is not None else ""
        enrollment = enrollments.get(sno)
        if enrollment is None:
            errors.append(f"第 {line} 行：学号 {sno or '(空)'} 不在本课程名单内")
            continue

        for col, exam_type in exam_cols.items():
            raw = row[col] if col < len(row) else None
            if raw is None or str(raw).strip() == "":
                continue  # 留空 = 不修改
            try:
                value = float(str(raw).strip())
            except ValueError:
                errors.append(f"第 {line} 行 {exam_type}：'{raw}' 不是有效数字")
                continue
            if not (0 <= value <= 100):
                errors.append(f"第 {line} 行 {exam_type}：{value:g} 不在 0~100 范围内")
                continue

            record = existing.get((enrollment.id, exam_type))
            if record is None:
                db.session.add(Score(enrollment_id=enrollment.id, exam_type=exam_type, score=value, updated_by=g.user.id))
            else:
                record.score = value
                record.updated_by = g.user.id
            imported += 1

    db.session.commit()
    if errors:
        shown = "；".join(errors[:5]) + ("……" if len(errors) > 5 else "")
        flash(f"导入完成：成功 {imported} 条，失败 {len(errors)} 条。{shown}", "error")
    elif imported:
        flash(f"导入完成：成功 {imported} 条成绩。", "success")
    else:
        flash("导入完成：文件里没有需要导入的成绩（分数列全为空）。", "error")
    return redirect(back_url)


# --------------------------------------------------------------------------- #
# 页面：管理员 Excel 入口（课程列表即入口，导入在课程详情页内完成）
# --------------------------------------------------------------------------- #
@bp.get("/excel")
@role_required("admin")
@login_required
def excel_guide():
    """Excel 导入导出指引页：告诉管理员各课程的导出 / 导入入口在哪。"""
    courses = db.session.scalars(
        select(Course).options(selectinload(Course.teacher)).order_by(Course.semester.desc(), Course.code)
    ).all()
    return render_template(
        "score/excel.html",
        courses=courses,
        exam_types=EXAM_TYPES,
        role_label=role_label(g.user.role),
    )


__all__ = ["bp", "EXPORT_COLUMNS"]
