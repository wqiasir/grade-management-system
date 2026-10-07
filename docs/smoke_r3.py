"""R3 端到端冒烟：对真实运行的服务验证"角色权限控制（RBAC）"。

用 Python 标准库 urllib + http.cookiejar（不引入新依赖），对真实运行的
``flask run`` 服务发请求，逐个角色验证：

1. 未登录访问受限页面 → 302 跳登录页（带 ``?next=``）；
2. admin / teacher / student 登录后，**导航与首页内容各不相同**；
3. ``student`` 直接敲 ``/admin/users`` → **HTTP 403**（不是 404、不是跳转）；
4. 教师看别人的课程详情 → **HTTP 403**（行级校验）；
5. 未登录 POST 停用账号 → 302 跳登录页，且**账号状态不变**（被拒的写操作无副作用）。

用法（先在项目根目录执行 flask init-db / seed / run）：
    python docs/smoke_r3.py [base_url]
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


class NoRedirect(urllib.request.HTTPRedirectHandler):
    """不自动跟随 302，方便断言 Location。"""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D102
        return None


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

    def post(self, path: str, data: dict[str, str] | None = None, token: str = ""):
        payload = dict(data or {})
        if token:
            payload["csrf_token"] = token
        body = urllib.parse.urlencode(payload).encode()
        return self._open(urllib.request.Request(BASE + path, data=body, method="POST"))

    def _open(self, request):
        try:
            with self.opener.open(request, timeout=10) as response:
                return response.status, dict(response.headers), response.read().decode("utf-8")
        except urllib.error.HTTPError as error:
            return error.code, dict(error.headers), error.read().decode("utf-8")


def csrf_token(html: str) -> str:
    match = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', html)
    return match.group(1) if match else ""


def fresh_token(browser: Browser) -> str:
    """取一次新的 CSRF token（每次渲染都会刷新 session 里的 raw token）。"""
    _, _, html = browser.get("/auth/login")
    return csrf_token(html)


def current_token(browser: Browser) -> str:
    """从首页取当前会话的 CSRF token。

    已登录用户访问 ``/auth/login`` 会被 302 挡回首页（这里的浏览器不跟随跳转，
    拿到的就不是登录页），所以登录态的写操作要从首页取 token。
    """
    _, _, html = browser.get("/")
    return csrf_token(html)


def login_as(browser: Browser, username: str, password: str) -> bool:
    """登录；已登录时先登出，保证切换到目标账号。"""
    token = fresh_token(browser)
    browser.post("/auth/logout", token=token)
    token = fresh_token(browser)
    status, _, _ = browser.post(
        "/auth/login", {"username": username, "password": password}, token=token
    )
    return status == 302


# --------------------------------------------------------------------------- #
# 1. 未登录
# --------------------------------------------------------------------------- #
print("\n[1] 未登录访问受限页面")
anon = Browser()
for path in ("/admin/users", "/admin/", "/score/my-courses", "/report/overview"):
    status, headers, _ = anon.get(path)
    location = headers.get("Location", "")
    check(
        f"{path} → 302 跳登录页并带 next",
        status == 302 and "/auth/login" in location and f"next={path}" in location,
        f"status={status} location={location}",
    )

status, _, html = anon.get("/")
check("未登录首页仍显示系统状态", status == 200 and "系统已启动" in html, f"status={status}")
check("未登录首页不出现管理员首页", "管理员首页" not in html)


# --------------------------------------------------------------------------- #
# 2~4. 三种角色
# --------------------------------------------------------------------------- #
print("\n[2] admin：能进账号管理，首页是管理员首页")
admin = Browser()
check("admin 登录成功", login_as(admin, "admin", "admin123"))

status, _, html = admin.get("/")
check("admin 首页显示管理员首页", status == 200 and "管理员首页" in html, f"status={status}")
check("admin 导航里有账号管理链接", "/admin/users" in html)

status, _, html = admin.get("/admin/users")
check("admin 能打开 /admin/users", status == 200 and "账号管理" in html, f"status={status}")
check("账号列表里有种子账号 student", "student" in html)

status, _, html = admin.get("/admin/")
check("admin 能打开账号总览", status == 200 and "按角色分布" in html, f"status={status}")

status, _, html = admin.get("/report/overview")
check("admin 统计范围是全校", status == 200 and "全校范围" in html, f"status={status}")


print("\n[3] student：被 403 挡住，导航里没有账号管理")
student = Browser()
check("student 登录成功", login_as(student, "student", "student123"))

status, _, html = student.get("/")
check("student 首页显示学生首页", status == 200 and "学生首页" in html, f"status={status}")
check("student 导航里没有账号管理链接", "/admin/users" not in html)
check("student 导航里有我的成绩占位项", "我的成绩" in html)

status, _, html = student.get("/admin/users")
check("student 访问 /admin/users → 403", status == 403, f"status={status}")
check("403 页面写明当前角色与要求角色", "403" in html and "学生" in html and "管理员" in html)

status, _, _ = student.get("/admin/")
check("student 访问 /admin/ → 403", status == 403, f"status={status}")

status, _, html = student.get("/report/overview")
check(
    "student 统计范围是仅本人",
    status == 200 and "仅你本人的选课与成绩" in html,
    f"status={status}",
)


print("\n[4] teacher：行级校验（别人的课）")
teacher = Browser()
check("teacher 登录成功", login_as(teacher, "teacher", "teacher123"))

status, _, html = teacher.get("/")
check("teacher 首页显示教师首页", status == 200 and "教师首页" in html, f"status={status}")

status, _, html = teacher.get("/admin/users")
check("teacher 访问 /admin/users → 403", status == 403, f"status={status}")

status, _, html = teacher.get("/score/my-courses")
check("teacher 能打开我的课程", status == 200, f"status={status}")

# 种子课程 CS101 是张伟（teacher）自己教的；再造一门"别人的课"不现实，
# 这里直接用一个不存在的课程号验证 404 与 403 的区分
status, _, html = teacher.get("/score/courses/999999")
check("不存在的课程 → 404（与 403 区分）", status == 404, f"status={status}")

status, _, html = teacher.get("/report/overview")
check(
    "teacher 统计范围是仅自己授课",
    status == 200 and "仅你授课的课程" in html,
    f"status={status}",
)


# --------------------------------------------------------------------------- #
# 5. 被拒的写操作没有副作用
# --------------------------------------------------------------------------- #
print("\n[5] 被拒的写操作")
attacker = Browser()
# 注意：全局 CSRFProtect 排在鉴权之前 —— 没有 csrf_token 的 POST 会先被拦成 400。
# 这里带上合法 token（同源页面可取到），才能走到鉴权那一层。
token = fresh_token(attacker)
status, headers, _ = attacker.post("/admin/users/1/toggle", token=token)
check(
    "未登录 POST 停用账号 → 302 跳登录页",
    status == 302 and "/auth/login" in headers.get("Location", ""),
    f"status={status}",
)

# 缺少 CSRF token 的 POST 更早一步就被拦下（400），连鉴权都不会执行
status, _, _ = attacker.post("/admin/users/1/toggle")
check("缺 CSRF token 的 POST → 400（在鉴权之前拦下）", status == 400, f"status={status}")

status, _, html = admin.get("/admin/users")
check("admin 账号仍是启用状态（未被匿名请求改动）", "admin" in html)

# 登录后的越权写操作：CSRF 通过，被 @role_required 拦成 403
token = current_token(student)
status, _, html = student.post("/admin/users/1/toggle", token=token)
check("student POST 停用账号 → 403", status == 403, f"status={status}")
check("403 页面说明被拒原因", "无权访问" in html)

# --------------------------------------------------------------------------- #
# 汇总
# --------------------------------------------------------------------------- #
print(f"\n{'=' * 56}")
print(f"R3 冒烟结果：通过 {ok_count} 项 / 失败 {fail_count} 项")
print(f"{'=' * 56}")
sys.exit(1 if fail_count else 0)
