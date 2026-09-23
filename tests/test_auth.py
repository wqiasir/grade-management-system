"""R2 验证：登录 / 登出 / 会话保持。

对应第 7 节 R2 的完成标准：``test_auth.py`` 通过
（含错误口令、不存在的用户、口令哈希校验）。
"""

from __future__ import annotations

import os
import re
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from flask import Flask
from flask.testing import FlaskCliRunner, FlaskClient

from gradeapp import auth, create_app
from gradeapp.extensions import csrf, db
from gradeapp.models import User

PASSWORD = "pw-123456"


# --------------------------------------------------------------------------- #
# 辅助
# --------------------------------------------------------------------------- #
def make_user(
    username: str = "u1",
    password: str = PASSWORD,
    role: str = "student",
    real_name: str = "测试用户",
    is_active: bool = True,
) -> User:
    user = User(username=username, role=role, real_name=real_name, is_active=is_active)
    user.set_password(password)
    db.session.add(user)
    db.session.commit()
    return user


def post_login(
    client: FlaskClient,
    username: str,
    password: str,
    next_url: str | None = None,
):
    data = {"username": username, "password": password}
    if next_url is not None:
        data["next"] = next_url
    return client.post("/auth/login", data=data)


def login(client: FlaskClient, username: str = "u1", password: str = PASSWORD):
    """登录并断言成功（登录成功后跳首页）。"""
    response = post_login(client, username, password)
    assert response.status_code == 302, "登录未成功跳转"
    return response


def extract_csrf_token(html: str) -> str:
    """从渲染后的表单里取出 CSRF token。"""
    match = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', html)
    assert match, "页面里没有 csrf_token 隐藏域"
    return match.group(1)


# --------------------------------------------------------------------------- #
# 登录页
# --------------------------------------------------------------------------- #
def test_login_page_renders_form(client: FlaskClient) -> None:
    response = client.get("/auth/login")
    assert response.status_code == 200

    html = response.get_data(as_text=True)
    assert "登录" in html
    assert 'name="username"' in html
    assert 'type="password"' in html
    assert "admin123" in html  # 页面列出演示账号，便于验收演示


def test_home_page_shows_login_entry_for_anonymous_user(client: FlaskClient) -> None:
    response = client.get("/")
    assert response.status_code == 200

    html = response.get_data(as_text=True)
    assert "未登录" in html
    assert "/auth/login" in html


# --------------------------------------------------------------------------- #
# 三种角色的种子账号都能登录
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("username", "password", "role", "real_name"),
    [
        ("admin", "admin123", "admin", "系统管理员"),
        ("teacher", "teacher123", "teacher", "张伟"),
        ("student", "student123", "student", "李小明"),
    ],
)
def test_seed_accounts_can_log_in(
    app: Flask,
    client: FlaskClient,
    runner: FlaskCliRunner,
    username: str,
    password: str,
    role: str,
    real_name: str,
) -> None:
    """演示要点：admin / teacher / student 三个账号均可登录。"""
    assert runner.invoke(args=["seed"]).exit_code == 0

    response = post_login(client, username, password)
    assert response.status_code == 302
    assert response.headers["Location"] == "/"

    # 会话保持：跟随跳转后首页显示当前登录人
    page = client.get("/").get_data(as_text=True)
    assert real_name in page
    assert auth.ROLE_LABELS[role] in page

    with client.session_transaction() as sess:
        assert sess["user_id"] == db.session.scalar(
            db.select(User.id).filter_by(username=username)
        )


def test_role_label_is_rendered_after_login(app: Flask, client: FlaskClient) -> None:
    make_user(role="teacher", real_name="王老师")
    login(client)

    page = client.get("/").get_data(as_text=True)
    assert "王老师" in page
    assert "教师" in page


# --------------------------------------------------------------------------- #
# 失败路径
# --------------------------------------------------------------------------- #
def test_wrong_password_is_rejected(app: Flask, client: FlaskClient) -> None:
    make_user(password="correct-pw")

    response = post_login(client, "u1", "wrong-pw")
    assert response.status_code == 200  # 停在登录页，不发放会话
    assert "用户名或口令错误" in response.get_data(as_text=True)

    with client.session_transaction() as sess:
        assert "user_id" not in sess


def test_unknown_user_is_rejected_without_leaking_existence(
    app: Flask, client: FlaskClient
) -> None:
    """不存在的用户与口令错误返回同一条提示，避免泄露账号是否存在。"""
    make_user(username="exists", password="correct-pw")

    response = post_login(client, "no-such-user", "whatever")
    assert response.status_code == 200
    assert "用户名或口令错误" in response.get_data(as_text=True)

    with client.session_transaction() as sess:
        assert "user_id" not in sess


def test_missing_password_is_rejected(app: Flask, client: FlaskClient) -> None:
    make_user()
    response = client.post("/auth/login", data={"username": "u1", "password": ""})
    assert response.status_code == 200
    assert "请输入口令" in response.get_data(as_text=True)


def test_inactive_account_cannot_log_in(app: Flask, client: FlaskClient) -> None:
    make_user(username="stopped", password="pw", is_active=False)

    response = post_login(client, "stopped", "pw")
    assert response.status_code == 200
    assert "已被停用" in response.get_data(as_text=True)

    with client.session_transaction() as sess:
        assert "user_id" not in sess


def test_form_errors_are_flashed(app: Flask, client: FlaskClient) -> None:
    make_user()
    response = post_login(client, "u1", "bad")
    assert "登录失败" in response.get_data(as_text=True)


def test_login_redirects_home_when_already_logged_in(
    app: Flask, client: FlaskClient
) -> None:
    make_user()
    login(client)

    response = client.get("/auth/login")
    assert response.status_code == 302
    assert response.headers["Location"] == "/"


# --------------------------------------------------------------------------- #
# 登出
# --------------------------------------------------------------------------- #
def test_logout_clears_session_and_returns_to_login(
    app: Flask, client: FlaskClient
) -> None:
    make_user()
    login(client)
    with client.session_transaction() as sess:
        assert sess["user_id"] is not None

    response = client.post("/auth/logout")
    assert response.status_code == 302
    assert response.headers["Location"] == "/auth/login"

    with client.session_transaction() as sess:
        assert "user_id" not in sess
        assert "_token" not in sess

    # 登出后回到登录页并看到提示
    page = client.get("/auth/login").get_data(as_text=True)
    assert "已安全退出登录" in page


def test_logout_requires_login(client: FlaskClient) -> None:
    response = client.post("/auth/logout")
    assert response.status_code == 302
    assert "/auth/login" in response.headers["Location"]


def test_logout_route_is_post_only(client: FlaskClient) -> None:
    """登出必须走 POST：GET 不生效，避免被外站链接/图片顺带触发。"""
    assert client.get("/auth/logout").status_code == 405


def test_csrf_protection_is_enforced_when_enabled() -> None:
    """正常配置下（CSRF 开启）：表单带 token，缺 token 的请求被拒。

    conftest 的 app 为了测试便利关掉了 CSRF，这里用一个启用 CSRF 的实例验证防护真的生效。
    临时库用 `mkstemp` 生成，避免依赖 pytest 的 tmp_path（沙箱下可能不可写）。
    """
    fd, db_path = tempfile.mkstemp(prefix="gradeapp-csrf-", suffix=".sqlite")
    os.close(fd)

    csrf_app = create_app(
        {
            "TESTING": True,
            "WTF_CSRF_ENABLED": True,
            "SECRET_KEY": "csrf-test-key",
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{Path(db_path).as_posix()}",
        }
    )

    with csrf_app.app_context():
        db.create_all()
        user = User(username="csrf_user", role="student", real_name="CSRF 用户")
        user.set_password("pw")
        db.session.add(user)
        db.session.commit()

    try:
        with csrf_app.test_client() as csrf_client:
            # 登录页与导航里的登出表单都带 CSRF token
            login_page = csrf_client.get("/auth/login").get_data(as_text=True)
            token = extract_csrf_token(login_page)

            assert csrf_client.post("/auth/logout").status_code == 400
            assert csrf_client.post(
                "/auth/login",
                data={
                    "csrf_token": token,
                    "username": "csrf_user",
                    "password": "pw",
                },
            ).status_code == 302

            home = csrf_client.get("/")
            assert home.status_code == 200
            assert "csrf_token" in home.get_data(as_text=True)  # 登出按钮也带 token
    finally:
        with csrf_app.app_context():
            db.session.remove()
            db.drop_all()
            db.engine.dispose()
        try:
            os.unlink(db_path)
        except OSError:  # pragma: no cover - Windows 上文件可能已被释放
            pass


# --------------------------------------------------------------------------- #
# 会话保持与失效
# --------------------------------------------------------------------------- #
def test_session_is_permanent_and_reused_across_requests(
    app: Flask, client: FlaskClient
) -> None:
    """会话保持：登录后连续多次请求仍是同一登录用户。"""
    user = make_user()
    login(client)

    for _ in range(3):
        page = client.get("/").get_data(as_text=True)
        assert user.real_name in page

    with client.session_transaction() as sess:
        assert sess.permanent is True


def test_modified_password_invalidates_existing_session(
    app: Flask, client: FlaskClient
) -> None:
    """口令被改后，旧会话（指纹不匹配）立即失效并回到登录状态。"""
    user = make_user()
    login(client)

    user.set_password("brand-new-pw")
    db.session.commit()

    page = client.get("/").get_data(as_text=True)
    assert "未登录" in page


def test_deactivated_user_session_is_revoked(app: Flask, client: FlaskClient) -> None:
    user = make_user()
    login(client)

    user.is_active = False
    db.session.commit()

    page = client.get("/").get_data(as_text=True)
    assert "未登录" in page


def test_session_survives_within_app_context(app: Flask, client: FlaskClient) -> None:
    """在同一会话内操作数据后再访问页面，登录状态不受影响。"""
    make_user()
    login(client)

    with client.session_transaction() as sess:
        assert sess["_token"]

    user = db.session.scalar(db.select(User))
    user.real_name = "改名后"
    db.session.commit()

    # 改名不影响口令指纹，登录状态保持
    assert "改名后" in client.get("/").get_data(as_text=True)


def test_session_token_roundtrip_and_tampering(app: Flask) -> None:
    user = make_user()
    token = auth.generate_session_token(user)

    assert auth.verify_session_token(token, user) is True
    assert auth.verify_session_token(token + "x", user) is False
    assert auth.verify_session_token("not-a-token", user) is False

    user.set_password("another-pw")
    db.session.commit()
    assert auth.verify_session_token(token, user) is False


def test_session_token_expires(app: Flask, monkeypatch: pytest.MonkeyPatch) -> None:
    user = make_user()
    token = auth.generate_session_token(user)

    monkeypatch.setattr(auth, "TOKEN_MAX_AGE", -1)
    assert auth.verify_session_token(token, user) is False

    monkeypatch.setattr(auth, "TOKEN_MAX_AGE", 3600)
    assert auth.verify_session_token(token, user) is True


# --------------------------------------------------------------------------- #
# 登录后跳回原地址（?next=）
# --------------------------------------------------------------------------- #
def test_login_returns_to_requested_page(app: Flask, client: FlaskClient) -> None:
    make_user()
    response = post_login(client, "u1", PASSWORD, next_url="/")

    assert response.status_code == 302
    assert response.headers["Location"] == "/"


@pytest.mark.parametrize(
    "target",
    [
        "",
        "http://evil.example.com/steal",
        "https://evil.example.com",
        "//evil.example.com",
        "/\\evil.example.com",
        "javascript:alert(1)",
    ],
)
def test_safe_next_rejects_external_targets(target: str) -> None:
    """开放重定向防护：只接受站内相对地址。"""
    assert auth._is_safe_next(target) is False


@pytest.mark.parametrize("target", ["/", "/?page=2", "/admin/users"])
def test_safe_next_accepts_internal_targets(target: str) -> None:
    assert auth._is_safe_next(target) is True


def test_open_redirect_is_blocked(app: Flask, client: FlaskClient) -> None:
    make_user()
    response = post_login(client, "u1", PASSWORD, next_url="//evil.example.com")
    assert response.status_code == 302
    assert response.headers["Location"] == "/"


# --------------------------------------------------------------------------- #
# 口令哈希
# --------------------------------------------------------------------------- #
def test_password_is_hashed_not_plaintext(app: Flask, runner: FlaskCliRunner) -> None:
    runner.invoke(args=["seed"])
    user = db.session.scalar(db.select(User).filter_by(username="student"))

    assert user.password_hash != "student123"
    assert user.password_hash.startswith("scrypt:")
    assert user.check_password("student123") is True
    assert user.check_password("Student123") is False
    assert user.check_password("") is False


def test_secret_key_is_configurable(app: Flask) -> None:
    from gradeapp import create_app

    other = create_app({"TESTING": True, "SECRET_KEY": "explicit-key"})
    assert other.config["SECRET_KEY"] == "explicit-key"
