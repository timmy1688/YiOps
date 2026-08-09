# Contributing to YiOps

感谢你帮助 YiOps 变得更可靠。提交代码前请先搜索已有 Issue；较大的功能或架构变化，建议先创建
Discussion 或 Issue 说明问题、用户价值和验收方式。

## Framework first

能由成熟主流框架解决的问题，不在 YiOps 内重新实现。提交新基础设施代码或引入自研抽象前，请先：

1. 检查当前技术栈和主流开源项目是否已经提供所需能力；
2. 优先使用官方 SDK、标准扩展点和框架生命周期；
3. 将自研部分限制为 YiOps 的领域策略或必要的薄适配层；
4. 在 PR 中说明候选方案、未采用原因、维护成本、安全边界和替换路径。

例如，MCP 协议和传输必须使用官方 MCP SDK，Agent 循环优先使用 LangChain/LangGraph，API 使用
FastAPI/Starlette，Schema 使用 Pydantic，数据库和迁移使用 Tortoise ORM/Aerich。不要复制协议解析、
序列化、重试、通用认证、ORM、任务队列或 UI 组件库。

## 本地环境

需要 Linux、Python 3.12+、Node.js 20+、npm 和 MySQL 8.0+。

创建数据库：

```sql
CREATE DATABASE yiops
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;
```

安装依赖：

```shell
cp .env.example .env
python3.12 -m venv backend/.venv
backend/.venv/bin/pip install -e "backend[dev]"
cd frontend
npm install
cd ..
```

修改 `.env` 中的 `YIOPS_DATABASE_URL`。确认 API 和 MCP 使用相同的
`YIOPS_MCP_INTERNAL_TOKEN`，然后在三个终端分别启动：

```shell
cd backend
.venv/bin/python -m app.mcp.server
```

```shell
cd backend
.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8100 --reload
```

```shell
cd frontend
npm run dev
```

前端默认运行在 `http://127.0.0.1:5173`，并将 `/api` 代理到后端 `8100` 端口。

## 数据库迁移

数据库结构使用 Aerich 管理。修改模型后执行：

```shell
cd backend
AERICH_MYSQL_VERSION=8.0 .venv/bin/aerich migrate --name describe_change
.venv/bin/aerich upgrade
```

源码和 Compose 启动都会先执行 `aerich upgrade`；生产环境不依赖运行时自动建表。

## 提交检查

```shell
cd backend
.venv/bin/ruff check app tests
.venv/bin/python -m pytest -q

cd ../frontend
npm run typecheck
npm run build
```

新增 RCA 逻辑时必须同时增加测试或 `evals/scenarios` 场景。根因必须引用有效 Evidence ID，不能把
数据源查询失败描述为系统健康。

## 添加数据源连接器

连接器能力统一登记在 `backend/app/connectors/registry.py`。新增连接器时：

1. 在注册表中声明唯一 `type`、展示名称、健康检查、能力和凭据类型；
2. 在 `backend/app/connectors/datasources.py` 实现原生只读查询、连接测试和 `ToolResult` 归一化；
3. 在 `backend/app/mcp/server.py` 登记语义明确、参数有界的 MCP 工具，并设置只读 annotation；
4. 在 `backend/app/mcp/client.py` 将 MCP 结果适配到稳定的 Agent Tool 契约；
5. 在 `AgentToolRegistry` 或 QueryPack 目录中显式开放工具，禁止模型指定 URL、HTTP method 或资源路径；
6. 为凭据脱敏、租户隔离、超时、结果上限、错误映射、mock 模式和 MCP structured output 补充测试。

当前内置 Prometheus、Loki、Tempo、Elasticsearch 和 Kubernetes。不要为新数据源增加独立常驻 MCP
服务；优先扩展统一 `yiops-mcp`。连接器必须保证失败结果可序列化、凭据不进入日志、原始响应在进入
模型前完成裁剪和脱敏。

## Pull Request

- 一个 PR 聚焦一个问题；
- 新增自研基础设施时，说明为什么现有主流框架不能满足；
- 描述行为变化、验证方式和兼容性影响；
- UI 变化请附截图；
- 不要提交 API Key、Token、真实日志、测试环境地址或内部网络信息；
- 提交即表示你同意按项目 Apache-2.0 License 授权贡献。
