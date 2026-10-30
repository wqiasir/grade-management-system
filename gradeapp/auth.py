"""认证蓝图（精简修复版）：登录 / 登出 / 会话保持。"""
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

TOKEN_SALT = "gradeapp-auth-token"
TOKEN_MAX_AGE = 60 * 60 * 24 * 7
ROLE_LABELS: dict[str, str] = {"admin": "管理员", "teacher": "教师", "student": "学生"}


# --------------------------------------------------------------------------- #
# 表单定义
# --------------------------------------------------------------------------- #
class LoginForm(FlaskForm):
    username = StringField("用户名", [validators.DataRequired("请输入用户名"), validators.Length(max=64)])
    password = PasswordField("口令", [validators.DataRequired("请输入口令")])
    submit = SubmitField("登录")

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.user: Optional[User] = None

    def validate_username(self, field: StringField) -> None:
        """严格校验：用户名、密码及账号激活状态。"""
        username = (field.data or "").strip()
        password = self.password.data or ""

        user = db.session.scalar(select(User).filter_by(username=username))
        
        # 统一提示，防止暴露出哪个账号存在
        if user is None or not user.check_password(password):
            self.username.errors.append("用户名或口令错误，请重新输入。")
            return
        
        if not user.is_active:
            self.username.errors.append("该账号已被停用，请联系管理员。")
            return

        # 校验全部通过，绑定 user
        self.user = user


class LogoutForm(FlaskForm):
    """仅用于在模板中生成 CSRF 令牌的空表单。"""


# --------------------------------------------------------------------------- #
# 会话指纹与签名工具
# --------------------------------------------------------------------------- #
def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"], salt=TOKEN_SALT)


def _password_fingerprint(user: User) -> str:
    return hashlib.sha256((user.password_hash or "").encode("utf-8")).hexdigest()[:16]


def generate_session_token(user: User) -> str:
    return _serializer().dumps([user.id, _password_fingerprint(user)])


def verify_session_token(token: str, user: User) -> bool:
    try:
        payload = _serializer().loads(token, max_age=TOKEN_MAX_AGE)
        return (
            isinstance(payload, list)
            and len(payload) == 2
            and payload[0] == user.id
            and payload[1] == _password_fingerprint(user)
        )
    except (BadSignature, SignatureExpired):
        return False


# --------------------------------------------------------------------------- #
# 请求钩子与上下文
# --------------------------------------------------------------------------- #
@bp.before_app_request
def load_logged_in_user() -> None:
    user_id = session.get("user_id")
    if user_id is None:
        g.user = None
        return

    user = db.session.get(User, user_id)
    token = session.get("_token", "")

    if not user or not user.is_active or not token or not verify_session_token(token, user):
        session.clear()
        g.user = None
    else:
        g.user = user


@bp.app_context_processor
def inject_auth_helpers() -> dict[str, object]:
    return {"role_labels": ROLE_LABELS, "logout_form": LogoutForm()}


# --------------------------------------------------------------------------- #
# 视图函数
# --------------------------------------------------------------------------- #
@bp.route("/login", methods=("GET", "POST"))
def login():
    if g.get("user") is not None:
        return redirect(url_for("index"))

    form = LoginForm()
    if form.validate_on_submit():
        user = form.user
        assert user is not None
        session.clear()
        session["user_id"] = user.id
        session["_token"] = generate_session_token(user)
        session.permanent = True
        flash(f"欢迎回来，{user.real_name}！", "success")
        return redirect(_safe_next() or url_for("index"))

    if form.is_submitted() and not form.errors:
        flash("登录失败，请检查下方提示。", "error")

    return render_template("auth/login.html", form=form)


@bp.post("/logout")
@login_required
def logout():
    session.clear()
    flash("已安全退出登录。", "success")
    return redirect(url_for("auth.login"))


def _safe_next() -> Optional[str]:
    target = request.args.get("next", "")
    parts = urlsplit(target)
    is_safe = (
        bool(target)
        and not parts.scheme
        and not parts.netloc
        and target.startswith("/")
        and "\\" not in target
    )
    return target if is_safe else None


__all__ = ["bp", "LoginForm", "LogoutForm", "ROLE_LABELS", "generate_session_token", "verify_session_token"]