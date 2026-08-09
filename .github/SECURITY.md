# Security Policy

## Supported versions

安全修复优先覆盖最新发布版本。YiOps 默认只进行只读调查，Compose 部署默认启用登录
认证；公网部署仍必须使用 HTTPS 和网络访问控制。

## Reporting a vulnerability

请不要为未修复漏洞创建公开 Issue。通过 GitHub Security Advisory 私下报告，并提供：

- 受影响版本和部署方式；
- 可复现步骤及影响；
- 已知缓解措施；
- 如有可能，提供最小化验证代码。

维护者确认前请避免访问不属于你的系统或数据。我们会尽快确认报告、评估影响，并在
修复发布后公开致谢（如报告者愿意）。

## Deployment baseline

- 使用只读数据源凭据和最小权限 Kubernetes ServiceAccount；
- 不向宿主机或公网发布 `yiops-mcp` 的 8110 端口，仅允许 YiOps API 通过内部网络访问；
- 为 `YIOPS_MCP_INTERNAL_TOKEN` 使用独立随机值并限制 `.env.docker` 的读取权限；
- 保持身份认证开启，使用 HTTPS、Secure Cookie 和网络访问控制；
- 保护 `.env.docker`、`.runtime/credential.key` 和数据库备份；
- 限制 PromQL、LogQL、TraceQL 的查询范围与并发；
- 定期升级 YiOps、数据库和基础镜像。
