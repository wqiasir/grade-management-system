"""学生学号新格式（8 位）+ 课程总评成绩占比

Revision ID: c3f1a9d24b70
Revises: fba8e95c58f8
Create Date: 2026-11-19 13:05:00.000000

变更内容：
1. ``course`` 增加 ``weight_regular / weight_midterm / weight_final`` 三个占比字段，
   默认 30 / 30 / 40（合计 100%），并加 CHECK 约束保证单项 0~100、合计 100；
2. 把本地已有的旧学号 ``[4 位年份][2 位班级号][3 位序号]`` 平移为
   ``[年份后两位][01 计算机学院][2 位班级号][2 位班内序号]``，
   学生登录用户名与旧学号相同的同步更新。
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c3f1a9d24b70'
down_revision = 'fba8e95c58f8'
branch_labels = None
depends_on = None

COLLEGE_CODE = "01"


def _upgrade_student_numbers() -> None:
    """旧 9 位学号 → 新 8 位学号（幂等：只处理 9 位纯数字旧学号）。"""
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            "SELECT s.id, s.user_id, s.sno, u.username "
            "FROM student s JOIN user u ON u.id = s.user_id"
        )
    ).fetchall()

    for student_id, user_id, sno, username in rows:
        old_sno = str(sno or "")
        if len(old_sno) != 9 or not old_sno.isdigit():
            continue  # 已经是新格式（或其他手工数据），不碰

        new_sno = f"{old_sno[2:4]}{COLLEGE_CODE}{old_sno[4:6]}{old_sno[7:9]}"

        # 理论上旧数据映射到新格式是单射；仍做冲突检查，避免半途失败。
        if bind.execute(
            sa.text("SELECT 1 FROM student WHERE sno = :sno AND id <> :id"),
            {"sno": new_sno, "id": student_id},
        ).first():
            continue
        if username != old_sno and bind.execute(
            sa.text("SELECT 1 FROM user WHERE username = :username AND id <> :id"),
            {"username": new_sno, "id": user_id},
        ).first():
            continue

        bind.execute(
            sa.text("UPDATE student SET sno = :sno WHERE id = :id"),
            {"sno": new_sno, "id": student_id},
        )
        if username == old_sno:
            bind.execute(
                sa.text("UPDATE user SET username = :username WHERE id = :id"),
                {"username": new_sno, "id": user_id},
            )


def _downgrade_student_numbers() -> None:
    """新 8 位学号 → 旧 9 位学号（仅处理学院编号为 01 的新格式）。"""
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            "SELECT s.id, s.user_id, s.sno, u.username "
            "FROM student s JOIN user u ON u.id = s.user_id"
        )
    ).fetchall()

    for student_id, user_id, sno, username in rows:
        new_sno = str(sno or "")
        if len(new_sno) != 8 or not new_sno.isdigit() or new_sno[2:4] != COLLEGE_CODE:
            continue

        old_sno = f"20{new_sno[0:2]}{new_sno[4:6]}0{new_sno[6:8]}"
        if bind.execute(
            sa.text("SELECT 1 FROM student WHERE sno = :sno AND id <> :id"),
            {"sno": old_sno, "id": student_id},
        ).first():
            continue

        bind.execute(
            sa.text("UPDATE student SET sno = :sno WHERE id = :id"),
            {"sno": old_sno, "id": student_id},
        )
        if username == new_sno:
            bind.execute(
                sa.text("UPDATE user SET username = :username WHERE id = :id"),
                {"username": old_sno, "id": user_id},
            )


def upgrade():
    with op.batch_alter_table("course", schema=None) as batch_op:
        batch_op.add_column(sa.Column("weight_regular", sa.Integer(), nullable=False, server_default="30"))
        batch_op.add_column(sa.Column("weight_midterm", sa.Integer(), nullable=False, server_default="30"))
        batch_op.add_column(sa.Column("weight_final", sa.Integer(), nullable=False, server_default="40"))
        batch_op.create_check_constraint(
            "ck_course_weight_regular", "weight_regular >= 0 AND weight_regular <= 100"
        )
        batch_op.create_check_constraint(
            "ck_course_weight_midterm", "weight_midterm >= 0 AND weight_midterm <= 100"
        )
        batch_op.create_check_constraint(
            "ck_course_weight_final", "weight_final >= 0 AND weight_final <= 100"
        )
        batch_op.create_check_constraint(
            "ck_course_weight_sum", "weight_regular + weight_midterm + weight_final = 100"
        )

    _upgrade_student_numbers()


def downgrade():
    _downgrade_student_numbers()

    with op.batch_alter_table("course", schema=None) as batch_op:
        batch_op.drop_constraint("ck_course_weight_sum", type_="check")
        batch_op.drop_constraint("ck_course_weight_final", type_="check")
        batch_op.drop_constraint("ck_course_weight_midterm", type_="check")
        batch_op.drop_constraint("ck_course_weight_regular", type_="check")
        batch_op.drop_column("weight_final")
        batch_op.drop_column("weight_midterm")
        batch_op.drop_column("weight_regular")
