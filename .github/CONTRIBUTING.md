# Contributing to YiOps

感谢你帮助 YiOps 变得更可靠。提交代码前请先搜索已有 Issue；较大的功能或架构变化，建议先创建
Discussion 或 Issue 说明问题、用户价值和验收方式。

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

修改 `.env` 中的 `YIOPS_DATABASE_URL`，然后在两个终端分别启动：

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
2. 在 `DatasourceClient` 中实现查询和连接测试，统一返回 `ToolResult`；
3. 只开放参数化、只读查询，不允许模型拼接任意命令；
4. 为凭据脱敏、超时、结果上限、错误映射和 mock 模式补充测试；
5. 在 `ChatToolRunner` 或 QueryPack 目录中显式开放工具。

当前内置 Prometheus、Loki、Elasticsearch 和 Kubernetes。连接器必须保证失败结果可序列化、凭据不进入
日志、原始响应在进入模型前完成裁剪和脱敏。

## Pull Request

- 一个 PR 聚焦一个问题；
- 描述行为变化、验证方式和兼容性影响；
- UI 变化请附截图；
- 不要提交 API Key、Token、真实日志、测试环境地址或内部网络信息；
- 提交即表示你同意按项目 Apache-2.0 License 授权贡献。
