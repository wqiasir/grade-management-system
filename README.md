# 杭电计算机学院学生成绩管理系统

> 软件工程课程实践项目 · Web 应用（B/S 架构）· Python 3.12 + Flask + SQLite
> 使用单位：**杭州电子科技大学计算机学院**（简称"杭电计算机学院"）

一个面向**杭州电子科技大学计算机学院**教学场景的学生成绩管理系统，支持 **管理员 / 教师 / 学生** 三种角色，
覆盖学生与教师信息管理、课程管理、选课、成绩录入与查询、统计报表、Excel 导入导出等功能。
系统的学生、教师、课程、选课与成绩数据都以**本学院**为范围，不处理跨学院数据。

**当前进度：R3 已完成（3 / 12）—— 角色权限控制（RBAC）。** 详见 [进度计划](#进度计划)。

> **更名说明**：系统原名「学生成绩管理系统」，现统一更名为「**杭电计算机学院学生成绩管理系统**」。
> 系统名与学院名集中定义在 `gradeapp/__init__.py` 的 `SYSTEM_NAME` / `SCHOOL_NAME` 两个常量，
> 由 `create_app()` 写入配置并注入所有模板（模板里用 `{{ system_name }}` / `{{ school_name }}`）。
> 因此**改名只需改一处**，不会出现"某个页面还写着旧名"的情况；
> `tests/test_app.py::test_branding_is_the_hdu_cs_system` 会逐页校验这一点。
> 历史汇报材料（`PPT/` 下的 3 个 `.pptx`）按约定保持原样存档，其中显示的仍是旧名，见 `PPT说明.md`。

---

## 目录

- [功能现状](#功能现状)
- [技术栈](#技术栈)
- [环境要求](#环境要求)
- [快速开始](#快速开始)
- [种子账号](#种子账号)
- [认证与安全（R2）](#认证与安全r2)
- [角色权限控制（R3）](#角色权限控制r3)
- [常用命令](#常用命令)
- [数据模型](#数据模型)
- [权限矩阵](#权限矩阵)
- [目录结构](#目录结构)
- [测试](#测试)
- [进度计划](#进度计划)
- [开发约定](#开发约定)
- [常见问题](#常见问题)

---

## 功能现状

本项目按 **一轮一个功能** 的方式迭代，每轮结束时系统都处于"可运行、可演示、测试全绿"的状态。
R1 交付地基，R2 加上**登录 / 登出 / 会话保持**，R3 加上**角色权限控制**（403 拦截、行级校验、
三种角色各自的导航与首页），业务数据的网页录入自 R4 起逐个出现。

| 能力 | 现状 |
| --- | --- |
| 启动 Web 服务、访问首页 | ✅ 可用 |
| **登录 / 登出 / 会话保持**（R2） | ✅ 可用（三种角色均可登录） |
| **口令哈希校验、错误口令提示、停用账号拦截**（R2） | ✅ 可用 |
| **CSRF 防护、开放重定向防护、安全退出**（R2） | ✅ 可用 |
| **按角色的访问控制 `@role_required` + 403 页面**（R3） | ✅ 可用（每角色 × 每受限路由都有测试） |
| **按角色渲染的导航与首页**（R3） | ✅ 可用（管理员 / 教师 / 学生各不相同） |
| **账号管理（列表 / 筛选 / 搜索 / 分页 / 停用启用）**（R3） | ✅ 可用（仅管理员） |
| **课程可见范围与行级校验**（R3） | ✅ 可用（教师仅自授、学生仅已选） |
| **统计概览（按角色收缩范围）**（R3） | ✅ 可用（口径固定在代码里） |
| 6 张数据表建表（走 Alembic 迁移） | ✅ 可用 |
| 数据增删改查（ORM 层） | ✅ 可用（`flask shell` 中直接操作） |
| 写入演示数据 | ✅ 可用（`flask seed` 命令） |
| 口令哈希、唯一约束、范围约束、级联删除 | ✅ 可用（数据库层强制） |
| **学生 / 教师 / 课程的网页增删改查** | ❌ R4 起逐轮实现 |
| **选课 / 成绩录入 / 成绩单 / 图表 / Excel** | ❌ R6~R10 实现 |

> 也就是说：**登录与权限已经能用，业务数据的网页录入还不能用。** 网页上的 CRUD 界面从 R4（学生信息管理）开始出现。
> 现在想验证数据层，用 `flask seed` 或 `flask shell`（见[快速开始](#快速开始)第 6 步）。

---

## 技术栈

| 组件 | 用途 | 版本约束 | 本项目实测版本 |
| --- | --- | --- | --- |
| Python | 运行时 | 3.12 | 3.12.6 |
| Flask | Web 框架（应用工厂模式） | `>=3.1,<3.2` | 3.1.3 |
| Flask-SQLAlchemy | ORM | `>=3.1,<4` | 3.1.1 |
| SQLAlchemy | ORM 内核（2.0 类型化写法） | — | 2.0.54 |
| Flask-Migrate / Alembic | 数据库迁移 | `>=4,<5` | 4.1.0 / 1.20.0 |
| Flask-WTF / WTForms | 表单 + CSRF 防护 | `>=1.2,<2` | 1.3.0 / 3.2.2 |
| Werkzeug | 口令哈希（scrypt） | — | 3.1.8 |
| openpyxl | Excel 导入导出 | `>=3.1,<4` | 3.1.5 |
| pytest / pytest-cov | 测试与覆盖率 | `>=8,<9` | 8.4.2 / 7.1.0 |
| waitress | 生产 WSGI 服务器 | `>=3,<4` | 3.0.2 |
| Chart.js | 统计图表（前端 CDN 引入） | — | R9 使用 |
| SQLite | 数据库（开发/演示） | — | 标准库自带 |

完整依赖清单见 `requirements.txt`（已 `pip freeze` 冻结，含全部传递依赖）。

> 架构参考 Flask 官方教程 Flaskr 的**应用工厂与测试夹具写法**，业务代码全部自写。

---

## 环境要求

- **Python 3.12+**（开发环境使用 3.12.6）
- **git**（拉取代码）
- 无需单独安装数据库，SQLite 由 Python 标准库自带

---

## 快速开始

以下命令以 **Windows PowerShell** 为例，均在项目根目录（本文件所在目录）执行。

### 1. 创建虚拟环境并安装依赖

```powershell
cd D:\作业\软件工程课程实践\project

python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

### 2. 初始化数据库（建表）

```powershell
.\.venv\Scripts\flask.exe init-db
```

该命令通过 Alembic 迁移建表，等价于 `flask db upgrade`。
若要**清空数据重建**，加 `--force`：

```powershell
.\.venv\Scripts\flask.exe init-db --force
```

数据库文件位置：`instance/gradeapp.sqlite`（`instance/` 已在 `.gitignore` 中，不入版本控制）。

### 3. 写入演示数据

```powershell
.\.venv\Scripts\flask.exe seed
```

会创建 3 个账号、1 名学生、1 名教师、1 门课程。**该命令幂等**，重复执行不会产生重复数据。

### 4. 启动服务

```powershell
.\.venv\Scripts\flask.exe run
```

浏览器打开 <http://127.0.0.1:5000/> —— 页面显示"**系统已启动**"，并列出 6 张表的建表状态与实时记录数。
按 `Ctrl + C` 停止服务。

> `.flaskenv` 已配置 `FLASK_APP=gradeapp` 与 `FLASK_DEBUG=1`（调试模式，改代码自动重启），
> 因此**必须在项目根目录下启动**，否则 Flask 找不到应用。

### 5. 登录演示（R2）

1. 打开 <http://127.0.0.1:5000/>，首页显示"当前为 **未登录** 状态"，右上角有**登录**按钮；
2. 进入 <http://127.0.0.1:5000/auth/login>，用种子账号登录（页面下方也列出了演示账号）：

   | 角色 | 用户名 | 口令 |
   | --- | --- | --- |
   | 管理员 | `admin` | `admin123` |
   | 教师 | `teacher` | `teacher123` |
   | 学生 | `student` | `student123` |

3. 登录成功后回到首页，导航栏右上角显示**姓名 + 角色徽标**与**退出登录**按钮；
   首页"当前登录状态"区块显示用户名与角色；
4. **口令输错**时停留在登录页并提示"用户名或口令错误，请重新输入。"（不区分"用户名不存在"与"口令错误"）；
5. 点击**退出登录** → 回到登录页并提示"已安全退出登录。"，首页重新变回未登录状态；
6. **会话保持**：登录后刷新页面、甚至关掉浏览器重新打开（cookie 有效期 7 天），仍是登录状态。

### 6. 验证数据层可写（可选）

网页还没有业务表单，用交互式 shell 直接操作数据库：

```powershell
.\.venv\Scripts\flask.exe shell
```

```python
from gradeapp.extensions import db
from gradeapp.models import User

u = User(username="test1", role="student", real_name="测试用户")
u.set_password("123456")
db.session.add(u)
db.session.commit()

print(User.query.count())
exit()
```

刷新首页，`user` 表的记录数会从 3 变成 4 —— 首页数字是每次请求实时查库的。

### 7. 另一种启动方式（不敲长路径）

```powershell
.\.venv\Scripts\Activate.ps1     # 若提示"禁止运行脚本"，见下方常见问题
flask init-db
flask seed
flask run
```

> macOS / Linux 下把 `.\.venv\Scripts\` 换成 `.venv/bin/`、`flask.exe` 换成 `flask` 即可。

---

## 种子账号

`flask seed` 创建的演示账号，**仅用于教学演示，切勿用于任何真实环境**：

| 角色 | 用户名 | 口令 | 关联档案 |
| --- | --- | --- | --- |
| 管理员 admin | `admin` | `admin123` | — |
| 教师 teacher | `teacher` | `teacher123` | 张伟 / 工号 `T2001` / 副教授 / 计算机学院 |
| 学生 student | `student` | `student123` | 李小明 / 学号 `2025001` / 计算机2501 / 2025 级 |

附带 1 门课程：`CS101` 程序设计基础（3.0 学分 / 48 学时 / 学期 `2025-2026-1` / 容量 60 / 授课教师张伟）。

口令一律以 `scrypt` 哈希存储（形如 `scrypt:32768:8:1$...`），库中**不存在明文口令**。

> 系统**不开放自主注册** —— 账号由管理员创建。成绩系统不能让任何人自行注册。

---

## 认证与安全（R2）

登录相关的路由：

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/auth/login` | 登录页（已登录访问则直接回首页） |
| `POST` | `/auth/login` | 校验用户名 + 口令，成功后写入会话并跳回首页（或 `?next=` 指定页） |
| `POST` | `/auth/logout` | 登出，清空会话后回登录页 |

实现要点：

1. **口令只存哈希**：`werkzeug.security` 的 `scrypt`，比对走 `check_password()`。
2. **失败提示不泄露账号是否存在**：用户不存在与口令错误返回**同一句**"用户名或口令错误"。
3. **停用账号（`is_active=False`）无法登录**，且已在线的会话会被立即吊销。
4. **会话指纹**：`session["_token"]` 是 `itsdangerous` 用 `SECRET_KEY` 签名的 `[user_id, 口令哈希摘要]`。
   口令被管理员重置、账号被停用时，旧 cookie 立即失效 → 强制重新登录。
5. **CSRF 防护**：全局 `CSRFProtect`；登录表单与导航里的登出表单都由 Flask-WTF 生成 `csrf_token`。
6. **登出只接受 POST**：避免被外站的链接或图片顺带触发（GET 返回 `405`）。
7. **开放重定向防护**：`?next=` 只接受站内相对地址（`/` 开头、无 `scheme`/`netloc`、无反斜杠），
   否则一律回首页。
8. **会话 cookie**：`HttpOnly` + `SameSite=Lax`，有效期 7 天（`PERMANENT_SESSION_LIFETIME`）。

---

## 角色权限控制（R3）

R3 之前，系统只有"登录才能访问"；R3 起**每个页面都按角色判定**，并且**同一份数据只给该看的人看**。

### 路由与可见范围

| 方法 | 路径 | admin | teacher | student |
| --- | --- | --- | --- | --- |
| `GET` | `/` 首页 | 账号总览 | 我的授课情况 | 我的选课 |
| `GET` | `/admin/` 账号总览 | ✅ | 403 | 403 |
| `GET` | `/admin/users` 账号管理 | ✅ | 403 | 403 |
| `POST` | `/admin/users/<id>/toggle` 停用 / 启用 | ✅ | 403 | 403 |
| `GET` | `/score/my-courses` 我的课程 | 全部课程 | 仅自己授课 | 仅自己已选 |
| `GET` | `/score/courses/<id>` 课程详情与名单 | 全部 | 仅自己授课，否则 403 | 仅已选，否则 403 |
| `GET` | `/report/overview` 统计概览 | 全校 | 仅自己授课 | 仅本人 |

### 三个实现要点

1. **装饰器负责"拦不拦得住"，视图负责"是不是他的"。**
   `@role_required("teacher")` 只说明"是教师"；"这门课是不是他教的"必须在视图里查一次。
   R3 把这件事做成了可复用的原语（`gradeapp/decorators.py`）：

   ```python
   denial = guard_course_access(course)   # 无权则直接返回 403 响应
   if denial is not None:
       return denial
   ```

   `can_view_course(user, course)` 的判定规则：admin 全放、teacher 仅 `course.teacher_id == user.teacher.id`、
   student 仅"在 `enrollment` 里出现过"。R6~R8 的选课与录成绩会复用同一套判定，避免各写一份而漏掉。

2. **403 与 404 分得清。** 无权访问 → `403` + `templates/errors/403.html`（页面上写明"当前身份"与"要求的角色"）；
   记录不存在 → `404`。两者混用会让验收时无法判断"是权限生效了还是数据没找到"。

3. **导航只是"看不见"，不是"进不去"。** `gradeapp/menu.py` 按角色生成导航（R4~R10 未实现的功能是灰显占位），
   但**服务端才是权威**：直接敲 `/admin/users` 一样被 403 挡住，`tests/test_permissions.py` 会逐格验证。

### 演示（R3）

1. 用 `student` 登录，地址栏直接输入 <http://127.0.0.1:5000/admin/users> → **403**，
   页面上能看到"当前身份：学生 / 该功能要求的角色：管理员"；
2. 用 `admin` 登录 → 导航出现「账号管理」，打开后可按角色筛选、按用户名或姓名搜索、翻页，
   还能**停用 / 启用**账号（不能停用自己，系统会保留至少一个可用管理员）；
3. 三种角色分别登录，观察**首页顶部区块与导航项各不相同**；
4. 打开「我的课程」：同一地址，教师只看到自己教的课、学生只看到自己选的课、管理员看到全部；
   教师把地址里的课程编号改成**别人的课** → 403；改成不存在的编号 → 404；
5. 打开「统计报表」：同一套口径，管理员是「全校范围」、教师是「仅你授课的课程」、学生是「仅你本人的选课与成绩」；
   页面上写明了平均分与及格率的算法（及格线 60 分）。

> 想一次跑完全部要点：`python docs\smoke_r3.py http://127.0.0.1:5000`（需先在另一个终端 `flask run`），
> 32 项断言覆盖未登录跳转、三角色差异、403 拦截、行级校验与"被拒的写操作无副作用"。

---

## 常用命令

```powershell
# 查看全部命令（含自定义的 init-db / seed）
.\.venv\Scripts\flask.exe --help

# 查看已注册路由（R2 起含 /auth/login、/auth/logout）
.\.venv\Scripts\flask.exe routes

# 数据库迁移
.\.venv\Scripts\flask.exe db current     # 当前迁移版本
.\.venv\Scripts\flask.exe db upgrade     # 应用迁移到最新
.\.venv\Scripts\flask.exe db migrate -m "说明"   # 改完模型后生成迁移脚本
.\.venv\Scripts\flask.exe db downgrade   # 回退一个版本

# 运行测试
.\.venv\Scripts\python.exe -m pytest -q

# 运行测试并输出覆盖率
.\.venv\Scripts\python.exe -m pytest --cov=gradeapp --cov-report=term-missing

# R2 端到端冒烟（需先在另一个终端启动 flask run）
.\.venv\Scripts\python.exe docs\smoke_r2.py http://127.0.0.1:5000

# R3 端到端冒烟：角色权限（403 拦截 / 行级校验 / 三角色差异），32 项断言
.\.venv\Scripts\python.exe docs\smoke_r3.py http://127.0.0.1:5000
```

**修改数据模型后必须生成迁移并升级**，不允许手工改库：

```powershell
.\.venv\Scripts\flask.exe db migrate -m "R2: 说明本次变更"
.\.venv\Scripts\flask.exe db upgrade
```

---

## 数据模型

6 张表，设计已冻结。ER 关系：

```
user ──1:1── student ──1:N── enrollment ──N:1── course ──N:1── teacher ──1:1── user
                                   │
                                   └──1:N── score
```

| 表 | 关键字段 | 约束 / 说明 |
| --- | --- | --- |
| `user` | id, username, password_hash, role, real_name, is_active, created_at | `username` 唯一 + 索引；`role ∈ {admin, teacher, student}`（CHECK 约束 `ck_user_role`）；口令用 `werkzeug.security` 哈希 |
| `student` | id, user_id, sno, name, gender, class_name, enroll_year | `user_id` → `user.id` **唯一**（一对一，级联删除）；`sno` 学号唯一 |
| `teacher` | id, user_id, tno, name, title, department | `user_id` → `user.id` **唯一**；`tno` 工号唯一 |
| `course` | id, code, name, credit, hours, teacher_id, semester, capacity | `code` 课程代码唯一；`teacher_id` → `teacher.id`（可空，未排课时）；`semester` 如 `2025-2026-1` |
| `enrollment` | id, student_id, course_id, enrolled_at | **UNIQUE(student_id, course_id)**（`uq_enrollment_student_course`）；容量校验在业务层 |
| `score` | id, enrollment_id, exam_type, score, updated_by, updated_at | `enrollment_id` → `enrollment.id`（级联删除）；**UNIQUE(enrollment_id, exam_type)**；CHECK `ck_score_range` 约束 `score ∈ [0,100]`；`updated_by` → `user.id` 记录操作人 |

### 设计要点

1. **`enrollment` 是必需的，不是冗余的。** 教师录入成绩时需要知道"这门课有哪些学生"，
   这个名单只能来自选课表。
2. **`score` 挂在 `enrollment` 上，而不是直接挂 `(student_id, course_id)`** ——
   从数据库层面杜绝"给未选课的学生打分"。
3. **`exam_type` 支持同一门课多次考核**（平时 / 期中 / 期末），用唯一约束防止重复录入。
   该字段**有意不加数据库 CHECK**，便于 R10 Excel 导入时扩展考核类型。
4. **`utcnow()`** 统一用带时区的 UTC 时间（`datetime.now(timezone.utc)`），避免 `datetime.utcnow` 的时区陷阱。

ORM 定义见 `gradeapp/models.py`，初始迁移脚本见
`migrations/versions/fba8e95c58f8_initial_schema_user_student_teacher_.py`。

---

## 权限矩阵

设计已冻结。`✅` 允许 / `👁` 只读 / `❌` 禁止 / `⚠️` 部分允许。

| 功能 | admin 管理员 | teacher 教师 | student 学生 |
| --- | --- | --- | --- |
| 用户账号管理 | ✅ 全部 | ❌ | ❌ |
| 学生信息 | ✅ 增删改查 | 👁 只读 | 👁 仅本人 |
| 教师信息 | ✅ 增删改查 | 👁 仅本人 | ❌ |
| 课程信息 | ✅ 增删改查 | 👁 仅自己授课 | 👁 已选课程 |
| 选课 / 退课 | ✅ 全部 | ❌ | ✅ 仅自己 |
| 成绩录入 / 修改 | ✅ 全部 | ✅ **仅自己授课的课程** | ❌ |
| 成绩查询 | ✅ 全部 | ✅ 仅自己授课的课程 | 👁 **仅本人** |
| 统计报表 | ✅ 全校 | ✅ 仅自己授课的课程 | 👁 仅本人 |
| Excel 导入 | ✅ 全部 | ⚠️ 仅自己课程的成绩 | ❌ |
| Excel 导出 | ✅ 全部 | ✅ 仅自己授课的课程 | 👁 仅本人 |

> **实现要求**：`@role_required('teacher')` 只能挡住"角色不对"；
> **"是不是自己教的课"必须在每个视图内做行级校验**。仅靠前端隐藏菜单项不算权限控制。

---

## 目录结构

```
project/
├── README.md                     ← 本文件
├── requirements.txt              ← 依赖冻结（pip freeze）
├── pyproject.toml                ← 项目元数据 + pytest / coverage 配置
├── .flaskenv                     ← FLASK_APP / FLASK_DEBUG
├── .gitignore
│
├── gradeapp/                     ← 应用包
│   ├── __init__.py               ← create_app() 应用工厂 + 蓝图注册 + 导航/品牌/错误处理 + init-db / seed 命令 + 首页路由
│   │                               （SYSTEM_NAME / SCHOOL_NAME 品牌常量定义在这里）
│   ├── extensions.py             ← db / migrate / csrf 扩展单例
│   ├── models.py                 ← 6 张表 ORM 定义
│   ├── auth.py                   ← R2 认证蓝图（登录 / 登出 / 会话指纹 / 当前用户钩子）
│   ├── decorators.py             ← R2 @login_required；R3 @role_required / forbidden / can_view_course
│   ├── menu.py                   ← R3 按角色生成导航（未实现的轮次为灰显占位）
│   ├── dashboard.py              ← R3 首页按角色取数
│   ├── admin.py                  ← R3 管理员蓝图（账号总览 / 账号列表 / 停用启用）
│   ├── score.py                  ← R3 我的课程 / 课程详情（含行级校验）；R6~R8 继续扩展
│   ├── report.py                 ← R3 统计概览（口径 + 角色范围）；R9 补图表
│   ├── templates/
│   │   ├── base.html             ← R2 布局：导航（按角色渲染）+ 闪现消息 + footer 块
│   │   ├── index.html            ← 首页（系统状态 + 按角色渲染的首页区块）
│   │   ├── auth/login.html       ← 登录页（含演示账号表）
│   │   ├── admin/                ← R3 dashboard.html / user_list.html
│   │   ├── score/                ← R3 my_courses.html / course_detail.html
│   │   ├── report/overview.html  ← R3 统计概览
│   │   └── errors/               ← R3 403.html / 404.html
│   └── static/
│       └── style.css
│
├── migrations/                   ← Alembic 迁移脚本
│   ├── env.py                    ← 已适配 Flask-SQLAlchemy 3.1（优先用 db.engine）
│   ├── alembic.ini
│   ├── script.py.mako
│   └── versions/
│       └── fba8e95c58f8_initial_schema_user_student_teacher_.py
│
├── instance/                     ← SQLite 数据库 + 本地配置（整目录不入版本控制）
│   ├── gradeapp.sqlite           ← 首次 init-db 时自动生成
│   └── config.py                 ← 本地配置覆盖模板（可选，clone 后不存在）
│
├── tests/
│   ├── conftest.py               ← app / client / runner 测试夹具（临时库隔离）
│   ├── test_app.py               ← 骨架与模型测试（12 条）
│   ├── test_auth.py              ← R2 认证测试（35 条）
│   └── test_permissions.py       ← R3 权限矩阵测试（56 条，重点）
│
└── docs/
    ├── 验收记录.md                ← 每轮验收总结（开发日志素材）
    ├── smoke_r2.py                ← R2 端到端冒烟脚本
    ├── smoke_r3.py                ← R3 端到端冒烟脚本（角色权限，32 项断言）
    ├── ppt_anim_notes.md          ← PPT 出场动画实现与踩坑记录
    └── ppt_assets/                ← 汇报 PPT 的素材与生成脚本（成品归档在工作目录根的 PPT/ 下）
```

### 尚未创建（后续轮次产出）

```
gradeapp/admin.py 的学生/教师/课程 CRUD   R4 / R5
gradeapp/score.py 的选课 / 成绩录入 / 查询  R6 / R7 / R8
gradeapp/report.py 的图表与更多口径        R9
gradeapp/excel_io.py                      R10
tests/test_admin.py / test_score.py / test_report.py / test_excel.py / seed_data.py  R4~R11
docs/需求分析.md / 数据库设计.md / 用户手册.md  R12
```

---

## 测试

```powershell
# 全部测试
.\.venv\Scripts\python.exe -m pytest -q

# 带覆盖率
.\.venv\Scripts\python.exe -m pytest --cov=gradeapp --cov-report=term-missing
```

**R1 实测结果**：`12 passed`，覆盖率 **97%**（198 语句 / 漏 2，22 分支 / 部分 5）。
分模块：`models.py` 100%、`extensions.py` 100%、`__init__.py` 95%。

测试夹具（`tests/conftest.py`）用 `tempfile.mkstemp()` 为每个测试创建**独立的临时 SQLite 库**，
互不干扰、不污染开发数据库；teardown 按
`db.session.remove()` → `db.drop_all()` → `db.engine.dispose()` → 删文件 的顺序释放，
规避 Windows 下连接池持有句柄导致删除失败的问题。

R1 的 12 条测试覆盖（`tests/test_app.py`）：

- 应用工厂可创建、首页返回 200 且内容正确
- 6 张表均已声明、各表字段齐全
- `init-db` 通过迁移建表，且 `alembic_version` 表存在
- **模型定义与迁移脚本无漂移**（防止忘记生成迁移）
- `seed` 幂等性、口令为哈希而非明文
- 唯一约束（用户名、学号）、角色 CHECK 约束、重复选课被拒、成绩唯一性与 0~100 范围

**R2 实测结果**：`47 passed`，覆盖率 **98%**（314 语句 / 漏 2，38 分支 / 部分 5）。
分模块：`auth.py` 100%、`decorators.py` 100%、`models.py` 100%、`extensions.py` 100%、`__init__.py` 95%。

R2 的 35 条测试覆盖（`tests/test_auth.py`）：

- 登录页渲染表单与演示账号、首页对匿名用户显示登录入口
- **三个种子账号（admin / teacher / student）都能登录**，登录后首页显示姓名与角色中文名
- 口令错误、用户不存在（提示不泄露账号是否存在）、口令为空、账号被停用 → 均被拒且不发放会话
- 已登录再访问登录页 → 直接回首页；登出后会话清空并回登录页
- 登出必须 POST（GET 返回 405）、缺 CSRF token 的 POST 返回 400、表单带 token
- 会话保持（多次请求同一用户、`session.permanent`、7 天有效期）
- **改口令 / 停用账号后旧会话立即失效**；伪造与过期的会话指纹被拒
- 登录后跳回 `?next=` 指定页；**`//evil.com`、`http://evil.com`、`javascript:` 等开放重定向被拦**

**R3 实测结果**：`103 passed`，覆盖率 **96%**（653 语句 / 漏 13，150 分支 / 部分 16）。
分模块：`auth.py` 100%、`models.py` 100%、`extensions.py` 100%、`report.py` 100%、`menu.py` 100%、
`decorators.py` 97%、`admin.py` 91%、`score.py` 94%、`dashboard.py` 90%、`__init__.py` 96%。

R3 的 56 条测试覆盖（`tests/test_permissions.py`）：

- **权限矩阵**：5 条受限路由 × 4 种身份（未登录 / admin / teacher / student）逐格断言
  —— 允许的角色得到 `200`，其余得到 `403`（未登录则 `302` 且带 `?next=`）
- **403 页面内容**：写明当前角色、要求的角色，并说明这是服务端返回的 `HTTP 403`
- **导航按角色渲染**：学生页面里不出现 `/admin/users`；管理员页面里有；未实现的功能是灰显占位（不是死链）
- **行级校验**：教师的非自授课程 → `403`；学生的未选课程 → `403`；不存在的课程 → `404`（两者能区分）
- **被拒的写操作无副作用**：越权 / 未登录的 `POST /admin/users/<id>/toggle` 不会改动账号状态
- **业务规则**：不能停用自己；系统至少保留一个可用管理员（模型层单测）
- `can_view_course` 原语的角色矩阵，以及三种角色首页、统计报表范围收缩的差异

> R11 将补齐**权限矩阵与边界**测试，当前的覆盖率不能替代它。

---

## 进度计划

12 轮迭代，每轮 = 一个功能，独立可演示、独立可验收。

| 轮次 | 内容 | 状态 |
| --- | --- | --- |
| R1 | 项目骨架与数据库 | ✅ 已完成 |
| R2 | 用户认证 | ✅ 已完成 |
| R3 | 角色权限控制（RBAC） | ✅ 已完成 |
| R4 | 学生信息管理 | ⬜ 未开始 |
| R5 | 教师与课程管理 | ⬜ 未开始 |
| R6 | 选课管理 | ⬜ 未开始 |
| R7 | 成绩录入 | ⬜ 未开始 |
| R8 | 成绩查询 | ⬜ 未开始 |
| R9 | 统计报表 | ⬜ 未开始 |
| R10 | Excel 导入导出 | ⬜ 未开始 |
| R11 | 测试体系完善 | ⬜ 未开始 |
| R12 | 部署与交付 | ⬜ 未开始 |

分阶段：**地基** R1~R3（骨架、认证、权限）→ **核心业务** R4~R8（信息管理、选课、成绩）→
**增值功能** R9~R12（报表、Excel、测试、部署）。

每轮结束后的验收总结追加在 `docs/验收记录.md`。

---

## 开发约定

1. **每轮结束时系统必须可运行、可演示、`pytest` 全绿**，不允许留半成品跨轮。
2. **所有数据库结构变更必须通过 Alembic 迁移**，不手工改库。
3. **不在代码里硬编码密钥**：开发用 `.flaskenv`，生产用环境变量；未配置时自动生成随机密钥并告警。
4. **口令只存哈希**，永不存明文。
5. **权限控制必须在服务端**：`@role_required` 之外，行级校验（"是不是自己教的课"）不可省略。
6. 依赖以 `requirements.txt`（冻结版本）为准；增删依赖后同步更新 `pyproject.toml`。
7. 每轮结束后更新 `docs/验收记录.md`。

---

## 常见问题

**Q：`flask run` 报 `Could not locate a Flask application`**

必须在**项目根目录**执行，且 `.flaskenv` 存在。确认当前目录下有 `gradeapp/` 和 `.flaskenv`。

**Q：首页提示"还有表未创建，请先执行 `flask init-db`"**

数据库文件不存在或为空，执行 `.\.venv\Scripts\flask.exe init-db` 即可。

**Q：`Activate.ps1` 报"禁止运行脚本"**

用长路径方式调用（`.\.venv\Scripts\flask.exe`），或只对当前会话放开策略：

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

**Q：端口 5000 被占用**

```powershell
.\.venv\Scripts\flask.exe run --port 5001
```

**Q：想清空全部数据重来**

```powershell
.\.venv\Scripts\flask.exe init-db --force
.\.venv\Scripts\flask.exe seed
```

**Q：改了 `models.py` 之后测试报"迁移与模型不一致"**

说明忘了生成迁移脚本：

```powershell
.\.venv\Scripts\flask.exe db migrate -m "说明"
.\.venv\Scripts\flask.exe db upgrade
```

---

## 已知限制

- 登录已可用（R2），**权限控制已可用（R3）**，但**业务数据的网页录入还不能用**，
  需通过 `flask seed` 或 `flask shell`（R4 起提供网页表单）。
- 导航里的灰显项（学生管理 / 教师与课程 / 选课 / 成绩录入 / 我的成绩 / Excel）是**后续轮次**的功能，R4 起逐个启用。
- 账号管理（R3）目前只做**停用 / 启用**；新增账号、改角色、重置口令放 R4。
- 统计报表（R3）目前是表格 + 纯 CSS 进度条，Chart.js 图表、分数段分布、班级排名放 R9。
- **行级校验目前只用在只读的课程详情上**；R6~R8 的写操作（选课 / 录成绩）必须同样调用
  `guard_course_access()`，这是下一阶段最容易出漏洞的地方。
- 学生 / 课程删除的级联策略目前只在数据库层做了 `ondelete="CASCADE"`，
  业务层规则（如"有成绩的学生能否删除"）留到 R4 / R5 决定。
- 使用 SQLite，适合单机演示；并发写入场景需换 PostgreSQL/MySQL。
- `.flaskenv` 中的 `SECRET_KEY` 是开发占位值，R12 将改为从环境变量注入的随机密钥并分离 `.env`。
  （未配置时应用会自动生成随机密钥并告警，因此不会以"空密钥"启动。）

---

*最后更新：2026-10-10 — 更名为「杭电计算机学院学生成绩管理系统」（系统名/学院名收敛到配置，104 条测试全绿；R3 完成态）*
