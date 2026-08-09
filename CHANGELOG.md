# Changelog

本项目遵循语义化版本。所有重要变化记录在此文件。

## [Unreleased]

### Added

- 内置统一 `yiops-mcp` Streamable HTTP Server，提供 Prometheus、Loki、Tempo、Elasticsearch、
  Kubernetes 六个固定只读查询工具和控制面连接探测工具；
- API 侧官方 MCP Python SDK v2 Client、内部 Bearer Token 认证和可信租户请求头隔离；
- 数据源原生 API 连接器，以及 none、Bearer、Basic Auth、API Key 四种认证方式；
- 持久化 Investigation 工作台与 RCA Evaluation Harness；
- HttpOnly 会话、CSRF 防护、登录限流、管理员密码修改和 Workspace 数据边界；
- 独立 RCA 评测中心、持久化评测运行与 20 个固定场景明细；
- 三个可一键导入且幂等的官方合成 RCA Demo；
- 数据源连接器注册表与扩展开发指南。

### Changed

- 数据源配置由外部 MCP Endpoint 改为原生 API 地址；API、自动 RCA、调查工作台和 AI 助手统一通过
  `yiops-mcp` 查询；
- Compose 和源码生命周期脚本同时管理 YiOps API 与 MCP 进程，MCP 仅在内部网络监听；
- API 与 MCP 共享加密凭据卷，凭据密钥改为跨进程原子创建。

### Removed

- 删除 Grafana MCP、Kubernetes MCP Server、Tempo MCP 和 `langchain-mcp-adapters` 运行时依赖；
- 删除 Grafana datasource UID、外部 MCP 地址及兼容回退逻辑。

### Migration

- 此变更不向后兼容。升级后需删除旧数据源，并使用 Prometheus、Loki、Tempo、Elasticsearch 或
  Kubernetes 的原生 API 地址重新创建；旧 MCP Endpoint 和 Grafana datasource UID 不再读取。

## [0.2.0] - 2026-08-01

### Added

- 独立 AI 助手及 Loki、Prometheus、Kubernetes、Elasticsearch 只读工具调用；
- Docker Compose 一键部署、随机数据库凭据和数据库级健康检查；
- 多模型渠道管理、告警自动分析和证据驱动根因报告；
- 统一 `service.sh` 生命周期入口和开源项目基础文件。
