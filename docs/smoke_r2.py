"""R2 端到端冒烟：走真实 HTTP 请求，验证登录 / 会话保持 / 登出。

用 Python 标准库 urllib + http.cookiejar（不引入新依赖），对真实运行的
``flask run`` 服务发请求，模拟浏览器的 cookie 行为。

用法（服务已在项目根目录启动）：
    python docs/smoke_r2.py [base_url]
"""

from __future__ import annotations

import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from http.cookiejar import CookieJar

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:5000"

ok_count = 0
fail_count = 0


def check(label: str, condition: bool, detail: str = "") -> None:
    global ok_count, fail_count
    if condition:
        ok_count += 1
        print(f"  [PASS] {label}")
    else:
        fail_count += 1
        print(f"  [FAIL] {label} {detail}")


class Browser:
    """带 cookie 的极简浏览器。"""

    def __init__(self) -> None:
        self.jar = CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.jar),
            NoRedirect(),
        )

    def get(self, path: str):
        return self._open(urllib.request.Request(BASE + path))

    def post(self, path: str, data: dict[str, str], token: str = ""):
        payload = dict(data)
        if token:
            payload["csrf_token"] = token
        body = urllib.parse.urlencode(payload).encode()
        request = urllib.request.Request(BASE + path, data=body, method="POST")
        return self._open(request)

    def _open(self, request):
        try:
            with self.opener.open(request, timeout=10) as response:
                return response.status, dict(response.headers), response.read().decode("utf-8")
        except urllib.error.HTTPError as error:
            return error.code, dict(error.headers), error.read().decode("utf-8")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    """不自动跟随 302，方便断言 Location。"""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D102
        return None


def csrf_token(html: str) -> str:
    match = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', html)
    return match.group(1) if match else ""


def fresh_token(browser: "Browser") -> str:
    """取一次新的 CSRF token（每次渲染都会刷新 session 里的 raw token）。"""
    _, _, html = browser.get("/auth/login")
    return csrf_token(html)


def main() -> int:
    print(f"R2 端到端冒烟 —— 目标 {BASE}\n")

    print("1) 未登录首页")
    status, _, html = Browser().get("/")
    check("首页返回 200", status == 200, f"实际 {status}")
    check("首页显示未登录状态", "未登录" in html)
    check("首页提供登录入口", 'href="/auth/login"' in html)

    print("\n2) 登录页")
    guest = Browser()
    status, _, html = guest.get("/auth/login")
    check("登录页返回 200", status == 200, f"实际 {status}")
    check("登录页含用户名/口令输入框", 'name="username"' in html and 'type="password"' in html)
    check("登录表单带 CSRF token", bool(csrf_token(html)))

    print("\n3) 错误口令被拒")
    status, _, html = guest.post(
        "/auth/login", {"username": "admin", "password": "wrong"}, fresh_token(guest)
    )
    check("错误口令停留在登录页（200）", status == 200, f"实际 {status}")
    check("提示用户名或口令错误", "用户名或口令错误" in html)

    print("\n4) 不存在的用户被拒（提示与口令错误相同）")
    status, _, html = guest.post(
        "/auth/login", {"username": "ghost", "password": "x"}, fresh_token(guest)
    )
    check("用户不存在时提示一致", status == 200 and "用户名或口令错误" in html)

    print("\n5) 三个种子账号都能登录 + 会话保持 + 登出")
    for username, password, real_name, role_label in [
        ("admin", "admin123", "系统管理员", "管理员"),
        ("teacher", "teacher123", "张伟", "教师"),
        ("student", "student123", "李小明", "学生"),
    ]:
        browser = Browser()
        login_token = fresh_token(browser)

        status, headers, html = browser.post(
            "/auth/login", {"username": username, "password": password}, login_token
        )
        check(f"{username} 登录后跳转首页", status == 302 and headers.get("Location") == "/",
              f"实际 {status} {headers.get('Location')}")

        status, _, home = browser.get("/")
        check(f"{username} 首页显示姓名 {real_name}", status == 200 and real_name in home)
        check(f"{username} 首页显示角色 {role_label}", role_label in home)
        check(f"{username} 导航显示退出登录按钮", "退出登录" in home)

        # 会话保持：再请求一次仍是登录状态
        _, _, home_again = browser.get("/")
        check(f"{username} 会话保持（二次请求仍在线）", real_name in home_again)

        # 登出（token 取自导航里的登出表单）
        status, headers, _ = browser.post("/auth/logout", {}, csrf_token(home))
        check(f"{username} 登出后回登录页",
              status == 302 and headers.get("Location") == "/auth/login",
              f"实际 {status} {headers.get('Location')}")

        status, _, after = browser.get("/")
        check(f"{username} 登出后首页显示未登录", "未登录" in after)

    print("\n6) 安全边界")
    status, _, _ = Browser().get("/auth/logout")
    check("GET /auth/logout 不被允许（405）", status == 405, f"实际 {status}")

    browser = Browser()
    status, _, _ = browser.post("/auth/logout", {})
    check("缺 CSRF token 的登出被拒（400）", status == 400, f"实际 {status}")

    browser = Browser()
    status, headers, _ = browser.post(
        "/auth/login",
        {"username": "admin", "password": "admin123", "next": "//evil.example.com"},
        fresh_token(browser),
    )
    check("开放重定向被拦（回首页）",
          status == 302 and headers.get("Location") == "/",
          f"实际 {status} {headers.get('Location')}")

    print(f"\n结果：通过 {ok_count} 项，失败 {fail_count} 项")
    return 1 if fail_count else 0


if __name__ == "__main__":
    raise SystemExit(main())
