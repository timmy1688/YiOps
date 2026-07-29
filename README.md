# YiOps

YiOps 是一个面向 Kubernetes 与云原生环境的告警根因分析平台。它接收
Alertmanager 告警，按受控流程查询 Prometheus、Loki、Elasticsearch 和
Kubernetes，只把压缩后的证据交给大模型，最终生成带证据引用的中文根因报告。

> 当前版本是单节点 MVP，默认只进行只读调查，不执行自动修复。

## 主要能力

- 接收 Alertmanager Webhook，自动归并和去重告警；
- 自动聚合 Alertmanager 告警，并可按接入渠道配置自动或手动发起分析；
- 接入 Prometheus、Loki、Elasticsearch 和 Kubernetes 数据源；
- 在 Web 界面维护 DeepSeek 及其他 OpenAI Compatible 模型渠道并随时切换；
- 使用受控的八节点流程规划查询、补充缺失证据并生成根因报告；
- 展示分析进度、工具调用、原始证据和证据引用；
- 对模型密钥及数据源凭据进行本地加密存储；
- 支持分析失败重试和报告反馈。

## 技术架构

```mermaid
flowchart LR
    AM[Alertmanager] --> API[FastAPI]
    UI[Vue 3] --> API
    API --> DB[(MySQL)]
    API --> AGENT[LangGraph 分析流程]
    AGENT --> PROM[Prometheus]
    AGENT --> LOKI[Loki]
    AGENT --> ES[Elasticsearch]
    AGENT --> K8S[Kubernetes API]
    AGENT --> LLM[DeepSeek / OpenAI Compatible 多渠道]
```

后端采用 Python 3.12、FastAPI、LangGraph、Tortoise ORM；前端采用 Vue 3、
TypeScript、Vite 和 Element Plus。更完整的设计说明见
[YiOps MVP 技术落地方案](./YiOps-MVP技术落地方案.md)。

## Agent 分析流程

当前 Agent 使用固定的八节点流程：

```text
normalize → plan → collect → compress → refine → analyze → validate → save
```

模型只负责选择受控 QueryPack、进行一次证据缺口复核和生成结构化报告；实际
PromQL、LogQL、Kubernetes API 查询、证据压缩、引用验证和置信度校准均由
Python 执行。完整的触发条件、节点输入输出、证据模型、失败恢复及 Incident
关闭流程见 [Agent 分析流程](./docs/agent-analysis-flow.md)。

## 界面功能

- **告警事件**：查看事件列表、严重级别和分析状态；
- **分析详情**：查看调查步骤、证据、模型结论和处置建议；
- **数据源**：添加数据源、配置只读凭据并测试连通性；
- **告警接入**：生成独立的 Alertmanager Webhook 地址；
- **模型接入**：维护多个模型渠道、测试连接并选择当前分析渠道。

## 快速开始

### 1. 环境要求

- Linux；
- Python 3.12+；
- Node.js 20+ 与 npm；
- MySQL 8.0+；
- 可选：Prometheus、Loki、Elasticsearch、Kubernetes 集群和模型 API。

### 2. 获取代码

```bash
git clone git@github.com:timmy1688/YiOps.git
cd YiOps
```

### 3. 创建数据库

```sql
CREATE DATABASE yiops
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;
```

复制环境变量模板，并将数据库账号和密码改成当前环境的实际值：

```bash
cp .env.example .env
```

关键配置如下：

```dotenv
YIOPS_DATABASE_URL=mysql://yiops:change_me@127.0.0.1:3306/yiops?charset=utf8mb4
YIOPS_DATASOURCE_MOCK_MODE=false
YIOPS_LLM_MOCK_MODE=true
```

首次启动时会自动创建所需数据表。

### 4. 安装后端

```bash
python3.12 -m venv backend/.venv
backend/.venv/bin/pip install -e "backend[dev]"
```

### 5. 构建前端

```bash
cd frontend
npm install
npm run build
cd ..
```

### 6. 启动服务

```bash
./service.sh start
./service.sh status
```

默认访问地址：

- Web：`http://127.0.0.1:8100/`
- OpenAPI：`http://127.0.0.1:8100/docs`
- 健康检查：`http://127.0.0.1:8100/api/v1/health`

常用管理命令：

```bash
./service.sh logs
./service.sh restart
./service.sh stop
```

可通过环境变量修改监听端口：

```bash
YIOPS_PORT=8200 ./service.sh start
```

## Docker Compose 部署

仓库提供多阶段镜像构建和 MySQL 编排，前端会在构建阶段编译，运行镜像中只保留
后端、Python 运行依赖和前端静态文件。

先创建 Docker 专用环境变量文件，并替换其中的数据库密码：

```bash
cp .env.docker.example .env.docker
```

启动服务：

```bash
docker compose --env-file .env.docker up -d --build
docker compose --env-file .env.docker ps
```

查看日志和停止服务：

```bash
docker compose --env-file .env.docker logs -f yiops
docker compose --env-file .env.docker down
```

默认访问 `http://127.0.0.1:8100/`。Compose 不会向宿主机暴露 MySQL，并使用
Named Volume 持久化数据库、运行日志及凭据加密密钥。`docker compose down`
不会删除这些数据；只有明确执行 `docker compose down -v` 才会删除 Volume。

默认只绑定本机地址。如需从其他机器访问，推荐使用带 HTTPS 和身份认证的反向
代理；仅在受信网络测试时，才把 `.env.docker` 中的 `YIOPS_BIND_ADDRESS` 改为
`0.0.0.0`。

## 开发模式

分别启动后端和前端：

```bash
cd backend
.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8100 --reload
```

```bash
cd frontend
npm run dev
```

Vite 开发服务器默认运行在 `http://127.0.0.1:5173`，并把 `/api` 请求代理到
后端的 `8100` 端口。

## 配置模型

推荐在 Web 界面的“模型接入”中配置：

1. 添加一个或多个 DeepSeek 或其他 OpenAI Compatible 模型渠道；
2. 为每个渠道填写 Base URL、模型名称和 API Key；
3. 点击“测试连接”验证渠道；
4. 将需要使用的渠道设为当前渠道（同一时间只会启用一个）。

API Key 不会返回给前端，后端会使用 `.runtime/credential.key` 加密后再保存。
该密钥文件不进入 Git，但迁移实例时需要通过安全渠道单独备份。

也可以通过 `.env` 设置默认 DeepSeek 配置：

```dotenv
YIOPS_DEEPSEEK_API_KEY=
YIOPS_DEEPSEEK_MODEL=deepseek-v4-pro
YIOPS_LLM_MOCK_MODE=false
```

不要把真实 API Key 写入 `.env.example` 或其他受 Git 管理的文件。

## 接入数据源

在“数据源”页面添加服务地址和只读凭据，然后点击连接测试。建议遵循以下原则：

- Prometheus 与 Loki 仅开放查询接口；
- Elasticsearch 使用只读索引权限；
- Kubernetes 使用独立 ServiceAccount 和最小化 RBAC；
- 不要使用集群管理员 Token；
- 通过防火墙或 NetworkPolicy 限制 YiOps 来源地址。

仓库提供以下 Kubernetes 示例：

- [`deploy/k8s/yiops-reader.yaml`](./deploy/k8s/yiops-reader.yaml)：只读 ServiceAccount；
- [`deploy/k8s/loki-demo.yaml`](./deploy/k8s/loki-demo.yaml)：测试用 Loki；
- [`deploy/k8s/observability-nodeports.example.yaml`](./deploy/k8s/observability-nodeports.example.yaml)：
  Prometheus 与 Loki 的受限 NodePort 示例。

应用 NodePort 示例前，必须复制为本地文件并替换示例 CIDR：

```bash
cp deploy/k8s/observability-nodeports.example.yaml \
  deploy/k8s/observability-nodeports.yaml
```

`observability-nodeports.yaml` 已加入 `.gitignore`，避免提交真实网络信息。

## 接入 Alertmanager

在“告警接入”页面创建集成后，YiOps 会生成带独立令牌的 Webhook URL。将该地址
配置为 Alertmanager Receiver：

```yaml
route:
  receiver: yiops

receivers:
  - name: yiops
    webhook_configs:
      - url: "http://yiops.example.com:8100/api/v1/integrations/REPLACE_INTEGRATION_ID/webhook/REPLACE_TOKEN"
        send_resolved: true
```

保存后发送一条测试告警，即可在“告警事件”页面查看。接入渠道默认开启自动分析：
收到 firing 告警后会创建或更新 Incident，并自动启动一次分析；关闭
`auto_analyze` 后，才需要在 Incident 页面手动点击“开始分析”。resolved 告警
只更新告警和 Incident 状态，不会触发新的分析。

## 代码检查

```bash
cd backend
.venv/bin/ruff check app
.venv/bin/python -m compileall -q app
```

```bash
cd frontend
npm run typecheck
npm run build
```

## 安全说明

- `.env`、`.runtime/`、日志、缓存、虚拟环境和前端构建产物默认不会提交；
- 模型密钥和数据源凭据不会通过读取接口返回；
- 查询工具使用预定义模板，模型不能直接执行任意 PromQL、LogQL 或命令；
- 当前 MVP 未内置完整的用户认证、多租户隔离与细粒度授权；
- 不要把当前版本直接暴露到公网，生产部署前应增加 HTTPS、反向代理、身份认证、
  访问控制、密钥托管、备份和审计策略。

## 项目结构

```text
YiOps/
├── backend/                  # FastAPI、Agent、连接器与数据模型
├── frontend/                 # Vue 3 Web 界面
├── docs/                     # Agent 流程和测试环境文档
├── deploy/k8s/              # Kubernetes 示例清单
├── .env.example             # 脱敏的环境变量模板
├── .env.docker.example      # Docker Compose 环境变量模板
├── Dockerfile               # 前后端多阶段镜像
├── docker-compose.yml       # YiOps 与 MySQL 编排
├── service.sh               # 单节点服务管理脚本
└── YiOps-MVP技术落地方案.md   # 详细设计文档
```

## 当前范围

YiOps 当前定位为验证告警分析闭环的 MVP。它不会执行自动修复，也不能替代人工变更
审批。模型结论应结合证据、监控数据和现场情况由运维人员复核。
