"""数据模型（第 5 节，已冻结的 6 张表）。"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
    select,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from werkzeug.security import check_password_hash, generate_password_hash

from .extensions import db

ROLES: tuple[str, ...] = ("admin", "teacher", "student")
EXAM_TYPES: tuple[str, ...] = ("平时", "期中", "期末")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(db.Model):
    __tablename__ = "user"
    __table_args__ = (CheckConstraint("role IN ('admin', 'teacher', 'student')", name="ck_user_role"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(256), nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    real_name: Mapped[str] = mapped_column(String(64), nullable=False)
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    student: Mapped[Optional["Student"]] = relationship(back_populates="user", uselist=False, cascade="all, delete-orphan")
    teacher: Mapped[Optional["Teacher"]] = relationship(back_populates="user", uselist=False, cascade="all, delete-orphan")

    def set_password(self, raw_password: str) -> None:
        self.password_hash = generate_password_hash(raw_password)

    def check_password(self, raw_password: str) -> bool:
        return check_password_hash(self.password_hash, raw_password)

    def deactivation_blocker(self, actor: Optional["User"] = None) -> Optional[str]:
        if actor is not None and actor.id == self.id:
            return "不能停用当前登录的账号。"
        if self.role == "admin":
            others = db.session.scalar(
                select(func.count()).select_from(User)
                .where(User.role == "admin", User.is_active.is_(True), User.id != self.id)
            )
            if not others:
                return "系统必须保留至少一个可用的管理员账号。"
        return None

    def __repr__(self) -> str:  # pragma: no cover
        return f"<User {self.username} ({self.role})>"


class Student(db.Model):
    __tablename__ = "student"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"), unique=True, nullable=False)
    sno: Mapped[str] = mapped_column(String(32), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    gender: Mapped[Optional[str]] = mapped_column(String(8))
    class_name: Mapped[Optional[str]] = mapped_column(String(64))
    enroll_year: Mapped[Optional[int]] = mapped_column(Integer)

    user: Mapped["User"] = relationship(back_populates="student")
    enrollments: Mapped[list["Enrollment"]] = relationship(back_populates="student", cascade="all, delete-orphan")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Student {self.sno} {self.name}>"


class Teacher(db.Model):
    __tablename__ = "teacher"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"), unique=True, nullable=False)
    tno: Mapped[str] = mapped_column(String(32), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[Optional[str]] = mapped_column(String(32))
    department: Mapped[Optional[str]] = mapped_column(String(64))

    user: Mapped["User"] = relationship(back_populates="teacher")
    courses: Mapped[list["Course"]] = relationship(back_populates="teacher")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Teacher {self.tno} {self.name}>"


class Course(db.Model):
    __tablename__ = "course"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    credit: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    hours: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    teacher_id: Mapped[Optional[int]] = mapped_column(ForeignKey("teacher.id"))
    semester: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    capacity: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    teacher: Mapped[Optional["Teacher"]] = relationship(back_populates="courses")
    enrollments: Mapped[list["Enrollment"]] = relationship(back_populates="course", cascade="all, delete-orphan")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Course {self.code} {self.name}>"


class Enrollment(db.Model):
    __tablename__ = "enrollment"
    __table_args__ = (UniqueConstraint("student_id", "course_id", name="uq_enrollment_student_course"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("student.id", ondelete="CASCADE"), nullable=False, index=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("course.id", ondelete="CASCADE"), nullable=False, index=True)
    enrolled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    student: Mapped["Student"] = relationship(back_populates="enrollments")
    course: Mapped["Course"] = relationship(back_populates="enrollments")
    scores: Mapped[list["Score"]] = relationship(back_populates="enrollment", cascade="all, delete-orphan")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Enrollment student={self.student_id} course={self.course_id}>"


class Score(db.Model):
    __tablename__ = "score"
    __table_args__ = (
        UniqueConstraint("enrollment_id", "exam_type", name="uq_score_enrollment_exam_type"),
        CheckConstraint("score >= 0 AND score <= 100", name="ck_score_range"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    enrollment_id: Mapped[int] = mapped_column(ForeignKey("enrollment.id", ondelete="CASCADE"), nullable=False, index=True)
    exam_type: Mapped[str] = mapped_column(String(32), nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    updated_by: Mapped[Optional[int]] = mapped_column(ForeignKey("user.id"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)

    enrollment: Mapped["Enrollment"] = relationship(back_populates="scores")
    updated_by_user: Mapped[Optional["User"]] = relationship(foreign_keys=[updated_by])

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Score enrollment={self.enrollment_id} {self.exam_type}={self.score}>"


MODELS: tuple[type[db.Model], ...] = (User, Student, Teacher, Course, Enrollment, Score)

__all__ = ["ROLES", "EXAM_TYPES", "MODELS", "User", "Student", "Teacher", "Course", "Enrollment", "Score", "utcnow"]