# 基于 MongoDB 的在线问卷系统

本项目实现问卷创建、发布、填写和结果统计。注册用户可以管理自己的问卷，通过链接邀请其他用户登录作答；后端根据题目配置校验答案、执行条件跳转，并将答卷保存到 MongoDB。

## 功能

- 账号注册、登录、密码哈希存储及问卷管理权限检查。
- 创建和编辑问卷，设置说明、匿名展示、重复填写和截止时间，发布或关闭问卷。
- 单选、多选、文本和数字四种题型，支持必答、选择数量、文本长度及数字范围限制。
- 单选、多选和数字条件跳转，按优先级执行第一条命中的规则，未命中则进入下一题。
- 逐题填写、返回改答、后端答题路径复核及重复提交限制。
- 整份和单题统计，包括选项计数、到达与回答人数、原始填写内容及数字平均值。

填写者必须登录。匿名提交在统计中隐藏账号，数据库保留身份用于执行重复填写限制。未提交答案仅保存在当前页面，刷新后清空。

## 技术与目录

| 目录 | 内容 |
| --- | --- |
| `backend/app/` | FastAPI 接口、Pydantic 模型、PyMongo 数据访问及业务逻辑 |
| `backend/app/db/schema.py` | MongoDB 集合校验规则及索引 |
| `backend/tests/` | 后端自动测试和真实 MongoDB 集成测试 |
| `frontend/src/` | Vue 3、TypeScript、Vue Router、Pinia 页面及交互 |
| `frontend/tests/` | 会话、时间、答案校验和跳转逻辑测试 |
| `docs/` | 设计、接口、测试、截图及 AI 使用日志 |

所有业务数据存储于 MongoDB。前后端使用通用开发框架，问卷业务由项目代码实现。

## 本地运行

环境要求：Python 3.12+、Node.js 20.19+ 或 22.12+、MongoDB 7/8。先启动 MongoDB，默认连接 `mongodb://127.0.0.1:27017`。前后端分别在两个终端运行。

### 1. 后端

进入 `backend` 目录执行：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

首次配置时复制 `.env.example`；已有 `.env` 时保留现有配置。按实际环境设置：

| 配置 | 含义 | 默认示例 |
| --- | --- | --- |
| `MONGODB_URI` | 数据库连接地址 | `mongodb://127.0.0.1:27017` |
| `MONGODB_DB` | 业务数据库 | `survey_system` |
| `JWT_SECRET` | 登录令牌签名密钥 | 替换为足够长的随机字符串 |
| `JWT_EXPIRE_MINUTES` | 令牌有效分钟数 | `120` |
| `FRONTEND_ORIGIN` | 允许的前端来源 | `http://localhost:5173` |

启动后端：

```powershell
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

接口页面：`http://127.0.0.1:8000/docs`。启动时初始化四个集合的校验规则及索引，已存数据不自动迁移。

### 2. 前端

进入 `frontend` 目录执行：

```powershell
npm ci
npm run dev -- --port 5173 --strictPort
```

访问 `http://localhost:5173/surveys`，注册并登录。开发服务器将 `/api` 请求代理至 `http://127.0.0.1:8000`。

若 5173 已被其他程序占用，前端可改用空闲端口，例如：

```powershell
npm run dev -- --port 5174 --strictPort
```

对应访问 `http://localhost:5174/surveys`，并将后端 `FRONTEND_ORIGIN` 设为 `http://localhost:5174` 后重启后端。验收截图使用的是 5174 端口。

### 3. 运行约束

后端按单个服务进程运行。问卷文档中的活动计数协调发布与编辑、关闭与提交；冲突返回 409，重新读取后可重试。异常退出留下的计数在下次单进程启动时恢复。

发布后锁定题目、跳转规则、匿名和重复设置，标题、说明及截止时间仍可调整。时间按 UTC 存储，页面统一使用北京时间。

## 测试

后端在 `backend` 目录执行：

```powershell
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

常规接口测试使用 mongomock。真实 MongoDB 测试默认跳过，启用前先确认测试实例可连接：

```powershell
$env:RUN_MONGO_INTEGRATION = '1'
$env:MONGO_TEST_URI = 'mongodb://127.0.0.1:27018'
python -m pytest -q
```

端口按实际实例调整；测试仅操作随机命名的 `survey_system_test_*` 数据库，结束后清理。

前端在 `frontend` 目录执行：

```powershell
npm test
npm run build
```

2026-10-21 的完整后端测试为 64 passed、0 skipped，其中 3 项使用真实 MongoDB；前端 8 个测试项通过，TypeScript 检查与 Vite 构建成功。浏览器手工验收 H01—H08 通过，包含 13 张代表截图。本机独立环境已完成依赖安装及启动、发布、提交、统计流程验证。

## 文档

| 文档 | 内容 |
| --- | --- |
| [系统与数据库设计](docs/design.md) | 集合划分、索引、跳转、校验、状态及统计逻辑 |
| [API 说明](docs/api.md) | 路径、请求字段、返回示例及错误状态 |
| [测试用例与结果](docs/test-cases.md) | 自动测试及手工验收的步骤、输入、输出和结果 |
| [手工验收截图](docs/manual-screenshots-20261021.md) | 13 张截图及用例对应关系 |
| [AI 使用日志](docs/ai-collaboration.md) | 25项开发记录、任务指令、生成代码、修改及验证结果 |

## 第一阶段交付

- [交付文件与实验要求逐项对照](docs/submission.md)
- GitHub 仓库：[chenyunshu1031/survey-system-phase1](https://github.com/chenyunshu1031/survey-system-phase1)（私有）

提交目录包含代码、MongoDB schema、配置示例、正式说明、测试用例、验收截图和 AI 使用日志。Word 报告单独提交，不上传仓库。本地数据库、实际 `.env`、依赖目录、日志、旧报告及生成预览不纳入仓库。
