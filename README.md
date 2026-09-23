# 学生成绩管理系统

> 软件工程课程实践项目 · Web 应用（B/S 架构）· Python 3.12 + Flask + SQLite

一个面向高校教学场景的学生成绩管理系统，支持 **管理员 / 教师 / 学生** 三种角色，覆盖学生与教师信息管理、
课程管理、选课、成绩录入与查询、统计报表、Excel 导入导出等功能。

**当前进度：R2 已完成（2 / 12）—— 用户认证。** 详见 [进度计划](#进度计划)。

---

## 目录

- [功能现状](#功能现状)
- [技术栈](#技术栈)
- [环境要求](#环境要求)
- [快速开始](#快速开始)
- [种子账号](#种子账号)
- [认证与安全（R2）](#认证与安全r2)
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
R1 交付地基，R2 加上**登录 / 登出 / 会话保持**，业务数据（学生、课程、成绩）的网页界面自 R4 起逐个出现。

| 能力 | 现状 |
| --- | --- |
| 启动 Web 服务、访问首页 | ✅ 可用 |
| **登录 / 登出 / 会话保持**（R2） | ✅ 可用（三种角色均可登录） |
| **口令哈希校验、错误口令提示、停用账号拦截**（R2） | ✅ 可用 |
| **CSRF 防护、开放重定向防护、安全退出**（R2） | ✅ 可用 |
| 6 张数据表建表（走 Alembic 迁移） | ✅ 可用 |
| 数据增删改查（ORM 层） | ✅ 可用（`flask shell` 中直接操作） |
| 写入演示数据 | ✅ 可用（`flask seed` 命令） |
| 口令哈希、唯一约束、范围约束、级联删除 | ✅ 可用（数据库层强制） |
| **按角色的导航与页面**（R3） | ⬜ R3 实现 |
| **学生 / 教师 / 课程 / 成绩的网页 CRUD** | ❌ R4 起逐轮实现 |

> 也就是说：**登录已经能用，业务数据的网页录入还不能用。** 网页上的 CRUD 界面从 R4（学生信息管理）开始出现。
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
│   ├── __init__.py               ← create_app() 应用工厂 + 蓝图注册 + init-db / seed 命令 + 首页路由
│   ├── extensions.py             ← db / migrate / csrf 扩展单例
│   ├── models.py                 ← 6 张表 ORM 定义
│   ├── auth.py                   ← R2 认证蓝图（登录 / 登出 / 会话指纹 / 当前用户钩子）
│   ├── decorators.py             ← R2 @login_required（R3 补 @role_required）
│   ├── templates/
│   │   ├── base.html             ← R2 布局：导航（按角色渲染）+ 闪现消息 + footer 块
│   │   ├── index.html            ← 首页（登录状态 + 系统状态页）
│   │   └── auth/
│   │       └── login.html        ← 登录页（含演示账号表）
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
│   └── test_auth.py              ← R2 认证测试（35 条）
│
└── docs/
    ├── 验收记录.md                ← 每轮验收总结（开发日志素材）
    └── smoke_r2.py                ← R2 端到端冒烟脚本（对真实服务发 HTTP 请求）
```

### 尚未创建（后续轮次产出）

```
gradeapp/decorators.py 的 @role_required   R3   角色鉴权（@login_required 已于 R2 交付）
gradeapp/admin.py         R4   管理员蓝图（学生/教师/课程）
gradeapp/score.py         R6   选课 / 成绩录入 / 查询
gradeapp/report.py        R9   统计报表
gradeapp/excel_io.py      R10  Excel 导入导出
gradeapp/templates/errors/403.html  R3
tests/test_permissions.py R11  权限矩阵测试（重点）
tests/seed_data.py        R11  测试数据构造
docs/需求分析.md           R12
docs/数据库设计.md         R12
docs/用户手册.md           R12
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

> R11 将补齐**权限矩阵与边界**测试，当前的覆盖率不能替代它。

---

## 进度计划

12 轮迭代，每轮 = 一个功能，独立可演示、独立可验收。

| 轮次 | 内容 | 状态 |
| --- | --- | --- |
| R1 | 项目骨架与数据库 | ✅ 已完成 |
| R2 | 用户认证 | ✅ 已完成 |
| R3 | 角色权限控制（RBAC） | ⬜ 未开始 |
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

- 登录已可用（R2），但**业务数据的网页录入还不能用**，需通过 `flask seed` 或 `flask shell`（R4 起提供网页表单）。
- 除首页外的业务路由尚未出现，导航栏里"学生管理 / 选课 / 我的成绩"等菜单项是**灰色占位**，R3~R8 逐轮启用。
- 权限控制目前只有 `@login_required`（登录才能访问）；**按角色的鉴权（`@role_required`）与 403 页面留到 R3**。
  第 6 节的权限矩阵要求行级校验，R3 起在每个视图内落实。
- 学生 / 课程删除的级联策略目前只在数据库层做了 `ondelete="CASCADE"`，
  业务层规则（如"有成绩的学生能否删除"）留到 R4 / R5 决定。
- 使用 SQLite，适合单机演示；并发写入场景需换 PostgreSQL/MySQL。
- `.flaskenv` 中的 `SECRET_KEY` 是开发占位值，R12 将改为从环境变量注入的随机密钥并分离 `.env`。
  （未配置时应用会自动生成随机密钥并告警，因此不会以"空密钥"启动。）

---

*最后更新：2026-09-22 — R2 完成（47 条测试全绿，覆盖率 98%）*
