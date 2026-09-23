"""认证蓝图：登录 / 登出 / 会话保持。

R2 交付：
1. ``/auth/login``   —— 账号 + 口令登录（表单校验 + 口令哈希比对）
2. ``/auth/logout``  —— 登出（POST + CSRF，不接受 GET，避免被外站图片链触发）
3. ``before_app_request`` 钩子在每个请求前把当前用户放进 ``g.user``
4. 会话指纹：``session["_token"]`` 由 ``itsdangerous`` 用 ``SECRET_KEY`` 签名，
   口令被改、账号被停用时旧会话立即失效（校验时比对 ``password_hash`` 摘要）

设计约束（第 5 节数据模型要点 4）：**不开放自主注册**，账号只由管理员创建。
"""

from __future__ import annotations

import hashlib
from typing import Optional
from urllib.parse import urlsplit

from flask import (
    Blueprint,
    current_app,
    flash,
    g,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from flask_wtf import FlaskForm
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy import select
from wtforms import PasswordField, StringField, SubmitField, validators

from .decorators import login_required
from .extensions import db
from .models import User

bp = Blueprint("auth", __name__, url_prefix="/auth")

#: 会话指纹的签名盐与有效期（7 天），与 ``PERMANENT_SESSION_LIFETIME`` 保持一致
TOKEN_SALT = "gradeapp-auth-token"
TOKEN_MAX_AGE = 60 * 60 * 24 * 7

#: 角色中文名，供导航与页面显示
ROLE_LABELS: dict[str, str] = {"admin": "管理员", "teacher": "教师", "student": "学生"}


# --------------------------------------------------------------------------- #
# 表单
# --------------------------------------------------------------------------- #
class LoginForm(FlaskForm):
    """登录表单。``csrf_token`` 隐藏域由 Flask-WTF 自动生成（CSRF 防护）。"""

    username = StringField(
        "用户名",
        [validators.DataRequired(message="请输入用户名"), validators.Length(max=64)],
    )
    password = PasswordField("口令", [validators.DataRequired(message="请输入口令")])
    submit = SubmitField("登录")

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.user: Optional[User] = None

    def validate_username(self, field: StringField) -> None:
        """用户名 + 口令一起校验。

        - 用户不存在 / 口令错误 → 提示**同一句话**，不泄露"用户名是否存在"
        - 账号被停用（``is_active`` 为假）→ 明确提示，不发放会话
        """
        username = (field.data or "").strip()
        password = self.password.data or ""

        user = db.session.scalar(select(User).filter_by(username=username))
        if user is None or not user.check_password(password):
            self.username.errors.append("用户名或口令错误，请重新输入。")
            return
        if not user.is_active:
            self.username.errors.append("该账号已被停用，请联系管理员。")
            return

        self.user = user


class LogoutForm(FlaskForm):
    """空表单：只为在模板里生成 ``csrf_token``，保证登出走 POST + CSRF。"""


# --------------------------------------------------------------------------- #
# 会话指纹：让"改了口令 / 被停用"的旧会话立刻失效
# --------------------------------------------------------------------------- #
def generate_session_token(user: User) -> str:
    """签发会话指纹：载荷是 id + 口令哈希摘要，用 ``SECRET_KEY`` 签名。"""
    return _serializer().dumps([user.id, _password_fingerprint(user)])


def verify_session_token(token: str, user: User) -> bool:
    """校验会话指纹：签名有效、未过期，且口令哈希未变（改口令即登出）。"""
    try:
        payload = _serializer().loads(token, max_age=TOKEN_MAX_AGE)
    except (BadSignature, SignatureExpired):
        return False
    return bool(
        isinstance(payload, list)
        and len(payload) == 2
        and payload[0] == user.id
        and payload[1] == _password_fingerprint(user)
    )


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"], salt=TOKEN_SALT)


def _password_fingerprint(user: User) -> str:
    """口令哈希的短摘要：cookie 里不出现完整哈希。"""
    return hashlib.sha256((user.password_hash or "").encode("utf-8")).hexdigest()[:16]


# --------------------------------------------------------------------------- #
# 每个请求前加载当前用户 + 模板上下文
# --------------------------------------------------------------------------- #
@bp.before_app_request
def load_logged_in_user() -> None:
    """从会话恢复当前用户；会话不可信或用户已不可用时清空会话。"""
    user_id = session.get("user_id")
    if user_id is None:
        g.user = None
        return

    user = db.session.get(User, user_id)
    token = session.get("_token", "")
    if (
        user is None
        or not user.is_active
        or not token
        or not verify_session_token(token, user)
    ):
        session.clear()
        g.user = None
        return

    g.user = user


@bp.app_context_processor
def inject_auth_helpers() -> dict[str, object]:
    """模板全局：登出表单（提供 CSRF token）与角色中文名。"""
    return {"role_labels": ROLE_LABELS, "logout_form": LogoutForm()}


# --------------------------------------------------------------------------- #
# 视图
# --------------------------------------------------------------------------- #
@bp.route("/login", methods=("GET", "POST"))
def login():
    """登录。已登录再访问则直接回到首页。"""
    if g.get("user") is not None:
        return redirect(url_for("index"))

    form = LoginForm()
    if form.validate_on_submit():
        user = form.user
        assert user is not None  # 校验通过即已赋值
        session.clear()
        session["user_id"] = user.id
        session["_token"] = generate_session_token(user)  # 会话指纹
        session.permanent = True  # 保持登录（时长见 PERMANENT_SESSION_LIFETIME）
        flash(f"欢迎回来，{user.real_name}！", "success")
        return redirect(_safe_next() or url_for("index"))

    if form.is_submitted():
        flash("登录失败，请检查下方提示。", "error")

    return render_template("auth/login.html", form=form)


@bp.post("/logout")
@login_required
def logout():
    """登出：清空会话并回到登录页。仅接受 POST（带 CSRF token）。"""
    session.clear()
    flash("已安全退出登录。", "success")
    return redirect(url_for("auth.login"))


def _safe_next() -> Optional[str]:
    """只接受站内相对地址，防止用 ``?next=//evil.com`` 做开放重定向。"""
    target = request.args.get("next", "")
    return target if _is_safe_next(target) else None


def _is_safe_next(target: str) -> bool:
    parts = urlsplit(target)
    return (
        bool(target)
        and not parts.scheme
        and not parts.netloc
        and target.startswith("/")
        and "\\" not in target
    )


__all__ = [
    "bp",
    "LoginForm",
    "LogoutForm",
    "ROLE_LABELS",
    "generate_session_token",
    "verify_session_token",
]
