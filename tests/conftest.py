"""pytest 夹具。

参照 Flask 官方教程（Flaskr）的做法：每个测试用 ``tempfile.mkstemp()``
生成独立的临时 SQLite 文件，测试之间互不干扰。
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest
from flask import Flask
from flask.testing import FlaskCliRunner, FlaskClient

from gradeapp import create_app
from gradeapp.extensions import db


@pytest.fixture
def app():
    """独立的 Flask 应用 + 空数据库，测试结束后删除临时文件。"""
    fd, db_path = tempfile.mkstemp(prefix="gradeapp-test-", suffix=".sqlite")
    os.close(fd)

    app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test-secret-key",
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{Path(db_path).as_posix()}",
            "WTF_CSRF_ENABLED": False,
        }
    )

    ctx = app.app_context()
    ctx.push()
    db.create_all()

    yield app

    db.session.remove()
    db.drop_all()
    db.engine.dispose()
    ctx.pop()
    try:
        os.unlink(db_path)
    except OSError:  # pragma: no cover - Windows 上文件可能已被删除
        pass


@pytest.fixture
def client(app: Flask) -> FlaskClient:
    return app.test_client()


@pytest.fixture
def runner(app: Flask) -> FlaskCliRunner:
    return app.test_cli_runner()
