# Eshop Assistant

面向电商咨询与售后的客服工作台。用户咨询商品政策、查看自己的订单并确认售后申请；客服核对申请并记录处理结果；运营审核知识缺口，发布经过索引的答案。

## 当前能力

- 用户端：流式会话、证据引用、订单选择、工单确认与取消、售后申请、未解决反馈。
- 客服端：售后申请队列、订单详情、审核意见、状态时间线、人工待办与相关对话。
- 知识运营：三类缺口来源、问题归并、答案审核、索引失败重试、发布状态。
- 知识库：材料切块预览与查重、入库、补齐向量、四策略检索自测、对话挖掘结果人工采纳。
- 服务端：会话认证、CSRF 校验、订单与会话归属校验、幂等提交、售后状态版本控制、工具审计。
- AI 核心：LangGraph 编排、interrupt/resume、混合检索与重排、证据置信度、异步滚动摘要。
- 观测：LangSmith 回调、会话 thread_id 关联、按意图聚合根调用 token 用量；默认关闭。

## 目录

```text
frontend/src/          React + TypeScript 页面、API 客户端和视觉样式
app/api/               认证、会话、订单售后、知识审核 API
app/core/              业务状态、身份认证、知识发布、检索与观测
app/graph/             LangGraph 状态、路由、节点与持久化恢复
app/db/                SQLAlchemy 模型与数据库会话
app/tools/             内置工具、统一执行器、MCP 客户端
mcp_servers/           物流与售后两个独立服务
docs/roadmap.md        范围、技术决策与里程碑
docs/validation.md     验证记录与未验证项
scripts/init_demo.py   建表与幂等演示数据初始化
tests/portfolio/       业务回归测试
```

## 本地启动

已完成初始化后，打开 Docker Desktop，在项目根目录执行一条命令即可启动 Docker 依赖、两个 MCP 和 API：

```powershell
uv run python -m scripts.dev
```

访问 http://127.0.0.1:8010。Ctrl+C 停止本次启动的进程；已运行的进程与 Docker 保持运行。日志位于 `data/runtime-logs`。启动器检测到已占用的 MCP 端口时会保留现有服务，如端口被其他程序占用，需先处理冲突。此命令不安装依赖、不迁移数据、不构建知识库。

需要 Python 3.12+ 和 Node.js 22。以下命令在项目根目录运行。

```powershell
uv sync --python 3.12
Copy-Item .env.example .env
docker volume create eshop-assistant-mysql-data
docker volume create eshop-assistant-milvus-data
docker volume create eshop-assistant-milvus-etcd
docker volume create eshop-assistant-milvus-minio
docker compose up -d
uv run python -m scripts.init_demo
npm --prefix frontend ci
npm --prefix frontend run build
uv run uvicorn app.main:app --host 127.0.0.1 --port 8010
```

已有 `.env` 时直接使用现有文件，不要执行覆盖命令。打开 [本地工作台](http://127.0.0.1:8010)。前端开发可另开终端运行 `npm --prefix frontend run dev`，Vite 将 `/api` 转发至 8010。

默认业务数据库为 MySQL `eshop_assistant`，端口 3307。首次启动需等待 MySQL 健康后再初始化。Compose 使用显式命名的外部数据卷，重复执行上面的卷创建命令不会清空已有卷。初始化命令重复执行不会覆盖账号密码、订单或已有处理记录。SQLite 仅用于隔离测试及 LangGraph checkpoint；此前演示业务文件保留，不会自动导入 MySQL。

演示账号：

| 身份 | 邮箱 |
| --- | --- |
| 用户林悦 | lin@eshop.demo |
| 用户周然 | zhou@eshop.demo |
| 客服陈曦 | agent@eshop.demo |

示例环境的演示密码是 `123456`。初次初始化时可修改 `DEMO_PASSWORD`；已存在账号的密码不会被重置。开启演示入口时，登录页点击任一演示身份会自动填入该邮箱与当前 `DEMO_PASSWORD`，再点一次「登录工作台」即可进入。`DEMO_ACCOUNTS_ENABLED=false` 隐藏演示身份入口，同时该接口不再回传密码。

## 检索与独立 MCP 服务

```powershell
docker compose up -d
uv run python -m scripts.build_kb
uv run python -m scripts.vectorize_kb
```

向量化需要 `.env` 中的嵌入与重排配置。本机使用 `eshop_knowledge` 集合、Milvus 端口 19531，与其他环境隔离。聊天还需要 `CHAT_MODEL`、`CHAT_BASE_URL`、`CHAT_API_KEY`。

分别在两个终端启动 MCP：

```powershell
uv run python -m mcp_servers.logistics_server
uv run python -m mcp_servers.aftersales_server
```

两个服务默认绑定本机 8111、8112。物流、保修与售后查询读取本项目的固定订单和处理记录；它们是本地外部系统适配示例，没有连接真实物流或支付平台。模型调用这些工具前，由统一执行器验证订单或物流单号属于当前用户。

## LangSmith

```dotenv
LANGSMITH_TRACING=true
LANGSMITH_API_KEY=your-langsmith-key
LANGSMITH_ENDPOINT=https://api.smith.langchain.com
LANGSMITH_PROJECT=eshop-assistant-local
LANGSMITH_WORKSPACE_ID=
LANGSMITH_HIDE_INPUTS=true
```

Agent 的 Local 环境对应追踪项目 `eshop-assistant-local`，项目名必须与网页环境对应；仅设置 Agent ID 和环境变量不替代此配置。密钥仅配置在后端。启用后重启 API，图调用与子调用通过 `thread_id` 元数据关联到同一会话；未启用或缺少密钥时，不影响业务运行。`LANGSMITH_ENDPOINT` 应匹配账号区域。

默认隐藏 trace 输入；输出仍可能包含业务结果。云端追踪验收需要有效密钥和一次真实图调用，本地测试不能替代这个验收。

```powershell
uv run python -m scripts.cost_by_intent --days 7
```

成本报表只统计根调用，避免重复计算子调用；数据来自当前 LangSmith 项目。

官方说明：[LangChain tracing](https://docs.langchain.com/langsmith/trace-with-langchain)、[会话关联](https://docs.langchain.com/langsmith/threads)。

## 验证

RAG 评估脚本为 `scripts/eval_rag.py`，数据集为 `tests/data/rag_eval.jsonl`（300 题，政策/型号/口语/库外/跨文档五类各 60 题）。数据格式检查入口为 `scripts/validate_rag_dataset.py`。

运行报告分别输出至 `data/reports/rag/`、`data/reports/confidence/`、`data/reports/usage/` 和 `data/reports/knowledge/`，默认不提交 Git。报告只反映最近一次运行，重跑即覆盖。

```powershell
uv run python -m scripts.verify
npm --prefix frontend run build
```

回归集覆盖身份隔离、CSRF、重复与并发提交、状态版本冲突、MCP 越权拦截、知识发布失败重试、工具描述和真实 SQLite checkpoint 重新打开后的恢复。数据库测试使用独立临时文件，不清理演示库。

全仓测试中仍有一批早期用例按旧契约断言（未带登录态、依赖本机 MySQL/Milvus、对同步函数的 mock 与实现中的 `await` 不符），不在回归门内；判断当前版本是否健康以 `scripts/verify` 为准。检索指标需在 Milvus 与模型就绪后重跑，不沿用历史结果。

## 演示顺序与边界

1. 林悦选择订单，确认申请，进入「我的售后」查看待审核状态。
2. 客服打开同一申请，核对订单、填写意见、批准，再记录处理结果。
3. 周然登录，确认无法读取林悦的订单、会话和申请。
4. 在配置检索服务后，演示拒答、反馈沉淀、审核补全、后续检索生效。

售后「已处理」表示本地业务处理结束，不表示支付渠道已打款。当前 API 与 SQLite checkpoint 按单进程运行；跨进程并发恢复需要额外的共享会话锁。知识索引依靠稳定块 ID 和重试补偿，不宣称数据库与 Milvus 跨库强一致。
