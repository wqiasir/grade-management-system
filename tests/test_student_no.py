"""学号规则单元测试：解析 / 生成 / 校验 / 班级号提取。"""
from __future__ import annotations

import pytest

from gradeapp.student_no import (
    COLLEGE_CODE,
    class_no_from_name,
    format_student_no,
    parse_student_no,
    student_number_error,
)


def test_parse_and_format_new_student_number():
    parsed = parse_student_no("25010204")

    assert parsed is not None
    assert parsed.year_short == 25
    assert parsed.enroll_year == 2025
    assert parsed.college_code == COLLEGE_CODE
    assert parsed.class_no == "02"
    assert parsed.seq == "04"
    assert parsed.class_seq == "0204"
    assert format_student_no(2025, "02", 4) == "25010204"
    assert format_student_no(2026, 1, 1) == "26010101"
    assert class_no_from_name("计算机2502") == "02"
    assert class_no_from_name("计算机2502班") == "02"
    assert class_no_from_name("未分班") is None


def test_student_number_error_cases():
    assert "不能为空" in (student_number_error("") or "")
    assert "8 位数字" in (student_number_error("202501001") or "")  # 旧 9 位
    assert "8 位数字" in (student_number_error("2501020a") or "")
    assert "8 位数字" in (student_number_error("２５０１０２０４") or "")  # 全角数字
    assert "学院编号" in (student_number_error("25020204") or "")
    assert "班级号" in (student_number_error("25010004") or "")
    assert "班内序号" in (student_number_error("25010200") or "")
    assert student_number_error("25010204") is None


def test_format_student_no_rejects_invalid_arguments():
    with pytest.raises(ValueError):
        format_student_no(2025, 0, 1)
    with pytest.raises(ValueError):
        format_student_no(2025, 1, 100)
    with pytest.raises(ValueError):
        format_student_no(1800, 1, 1)
    with pytest.raises(ValueError):
        format_student_no(2025, 1, 1, college_code="1")
