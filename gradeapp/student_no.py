"""学生学号规则（2026-11 起启用）。

学号为 **8 位数字**：``[年份后两位][2 位学院编号][2 位班级号][2 位班内序号]``。

- 学院编号固定为 ``01``（计算机学院）——系统当前只服务计算机学院；
- 班级号与班内序号均为 ``01~99``；
- 例：``25010204`` 表示 2025 年入学、计算机学院 2 班第 4 位学生。

学号同时是学生的登录用户名（创建 / 编辑学生时自动同步），因此这里的校验
既服务于表单，也约束批量数据（如 ``seed_grade_data.py``）的生成口径。
"""
from __future__ import annotations

import re
from dataclasses import dataclass

COLLEGE_CODE = "01"
COLLEGE_NAME = "计算机学院"
STUDENT_NO_LENGTH = 8
STUDENT_NO_EXAMPLE = "25010204"

_STUDENT_NO_RE = re.compile(
    r"^(?P<year>[0-9]{2})(?P<college>[0-9]{2})(?P<class_no>[0-9]{2})(?P<seq>[0-9]{2})$"
)
_CLASS_NAME_RE = re.compile(r"(?P<year>[0-9]{2})(?P<class_no>[0-9]{2})\s*班?$")

STUDENT_NO_HINT = (
    f"学号格式为 8 位数字：年份后两位 + 学院编号（{COLLEGE_CODE} 为{COLLEGE_NAME}）"
    f"+ 2 位班级号 + 2 位班内序号，如 {STUDENT_NO_EXAMPLE}"
    "（25 年入学、计算机学院 2 班第 4 位学生）。"
)


@dataclass(frozen=True)
class StudentNumber:
    """解析后的学号。``class_no`` / ``seq`` 保留两位字符串，便于直接拼回学号。"""

    year_short: int
    college_code: str
    class_no: str
    seq: str

    @property
    def enroll_year(self) -> int:
        """两位年份按 20xx 解释（本系统服务的是 2000 年后的在校生）。"""
        return 2000 + self.year_short

    @property
    def class_seq(self) -> str:
        return f"{self.class_no}{self.seq}"


def parse_student_no(sno: str | None) -> StudentNumber | None:
    """解析学号；格式不合法时返回 ``None``（不抛异常，便于表单与脚本共用）。"""
    match = _STUDENT_NO_RE.match((sno or "").strip())
    if match is None:
        return None
    return StudentNumber(
        year_short=int(match.group("year")),
        college_code=match.group("college"),
        class_no=match.group("class_no"),
        seq=match.group("seq"),
    )


def format_student_no(enroll_year: int, class_no: int | str, seq: int | str,
                      college_code: str = COLLEGE_CODE) -> str:
    """按规则拼出学号；``class_no`` / ``seq`` 超出 1~99 时抛 ``ValueError``。"""
    class_no_int = int(class_no)
    seq_int = int(seq)
    if not 1 <= class_no_int <= 99:
        raise ValueError("班级号必须为 01~99")
    if not 1 <= seq_int <= 99:
        raise ValueError("班内序号必须为 01~99")
    if not 1900 <= int(enroll_year) <= 2099:
        raise ValueError("入学年份必须为 1900~2099")
    if len(str(college_code)) != 2 or not str(college_code).isdigit():
        raise ValueError("学院编号必须是 2 位数字")
    return f"{int(enroll_year) % 100:02d}{college_code}{class_no_int:02d}{seq_int:02d}"


def class_no_from_name(class_name: str | None) -> str | None:
    """从班级名末尾解析班级号，如 ``计算机2502`` → ``"02"``；解析不出返回 ``None``。"""
    match = _CLASS_NAME_RE.search((class_name or "").strip())
    return match.group("class_no") if match else None


def student_number_error(sno: str | None) -> str | None:
    """返回学号的格式错误说明；合法时返回 ``None``。"""
    text = (sno or "").strip()
    if not text:
        return "学号不能为空。"
    if len(text) != STUDENT_NO_LENGTH or not text.isascii() or not text.isdigit():
        return f"学号必须是 {STUDENT_NO_LENGTH} 位数字（{STUDENT_NO_HINT}）。"

    parsed = parse_student_no(text)
    assert parsed is not None  # 上面的长度 / 数字判断已保证
    if parsed.college_code != COLLEGE_CODE:
        return f"学号第 3~4 位是学院编号，当前系统只支持 {COLLEGE_CODE}（{COLLEGE_NAME}）。"
    if parsed.class_no == "00":
        return "学号中的班级号必须为 01~99。"
    if parsed.seq == "00":
        return "学号中的班内序号必须为 01~99。"
    return None


__all__ = [
    "COLLEGE_CODE",
    "COLLEGE_NAME",
    "STUDENT_NO_EXAMPLE",
    "STUDENT_NO_HINT",
    "STUDENT_NO_LENGTH",
    "StudentNumber",
    "class_no_from_name",
    "format_student_no",
    "parse_student_no",
    "student_number_error",
]
