# 数据源连接器扩展指南

YiOps 通过 `backend/app/connectors/registry.py` 维护数据源能力目录。Web 界面和 API
从注册表读取展示名称、健康检查、凭据类型和能力声明，避免在多个位置重复维护类型清单。

## 当前内置连接器

| 类型 | 能力 | 凭据建议 |
| --- | --- | --- |
| Prometheus | 指标范围查询、QueryPack | 只读 HTTP 访问 |
| Loki | 日志范围查询、QueryPack | 只读 HTTP 访问 |
| Elasticsearch | 日志检索、QueryPack | 只读索引用户 |
| Kubernetes | 对象、事件、工作负载检查 | 自包含 kubeconfig + 最小权限 ServiceAccount |

## 添加连接器

1. 在注册表中声明唯一 `type`、展示名称、健康检查路径、能力和凭据类型；
2. 在 `DatasourceClient` 中实现查询与连接测试适配器，所有返回值统一为 `ToolResult`；
3. 只暴露参数化、只读查询，不允许模型直接拼接并执行任意命令；
4. 为凭据脱敏、超时、结果上限、错误映射和 mock 模式补充测试；
5. 在 `ChatToolRunner` 或 QueryPack 目录中显式开放所需工具。

连接器必须保证失败结果可序列化、凭据不进入日志、原始响应在进入模型前完成裁剪和脱敏。
后续版本会在此注册表上增加 Python entry point，使第三方包无需修改核心仓库即可安装。
