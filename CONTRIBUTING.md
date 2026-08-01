# Contributing to YiOps

感谢你帮助 YiOps 变得更可靠。提交代码前请先搜索已有 Issue；较大的功能或架构变化，
建议先创建 Discussion 或 Issue 描述问题、用户价值和验收方式。

## 本地开发

```shell
python3.12 -m venv backend/.venv
backend/.venv/bin/pip install -e "backend[dev]"
cd frontend && npm ci && npm run build && cd ..
./service.sh start
```

## 提交检查

```shell
cd backend
.venv/bin/ruff check app tests
.venv/bin/python -m pytest -q

cd ../frontend
npm run typecheck
npm run build
```

新增 RCA 逻辑时必须同时增加测试或 `evals/scenarios` 场景。报告中的根因必须引用
有效证据 ID，不能把数据源查询失败描述为系统健康。

## Pull Request

- 一个 PR 聚焦一个问题；
- 描述行为变化、验证方式和兼容性影响；
- UI 变化请附截图；
- 不要提交 API Key、Token、真实日志或内部网络地址；
- 提交即表示你同意按项目 Apache-2.0 License 授权贡献。
