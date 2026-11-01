# Eshop Assistant 运行配置

日常启动、演示账号与 LangSmith 变量见 README。

## MySQL 模式

Compose 项目名固定为 eshop-assistant，使用显式命名的外部数据卷。首次部署先执行 README 中的四条 `docker volume create`，再运行 `docker compose up -d`。本机 MySQL 映射端口 3307，数据库 eshop_assistant。本地 `.env` 对应两行：

```dotenv
DATABASE_URL=mysql+asyncmy://root:root@localhost:3307/eshop_assistant
TEST_DATABASE_URL=mysql+asyncmy://root:root@localhost:3307/eshop_assistant_test
```

随后运行 `uv run python -m scripts.init_demo` 初始化新库。演示密码必须至少 6 位。已有历史数据库需要按模型差异迁移，不能用 create_all 当作升级迁移。

## 数据库与数据卷

Compose 使用四个显式命名的外部数据卷（mysql / milvus / etcd / minio），首次部署前先按 README 创建。MySQL 中原业务库保留，本项目在 `eshop_assistant` 库中初始化当前版本模型与演示数据。LangGraph checkpoint 单独存放于 `data/conversation_checkpoints.sqlite`。

演示订单 1001、2002 来自固定随机种子生成的模拟快照。`uv run python -m scripts.import_seed_orders` 将这两个快照幂等导入新库，归属林悦账号，不改变其他用户的归属校验。保留快照中的商品、金额、时间、状态及物流单号，不生成不存在的物流事件。

## 前后端

开发：FastAPI 8010，Vite 5173，两个 MCP 8111 与 8112。

交付：`npm --prefix frontend ci` 和 `npm --prefix frontend run build` 后，FastAPI 提供构建产物与 SPA 回退。

当前服务默认只绑定 127.0.0.1。对外部署时使用 HTTPS、设置 COOKIE_SECURE=true、关闭演示身份入口、使用独立数据库账号，并在反向代理关闭 SSE 响应缓冲。当前版本按一个 API worker 运行。

## 观测与验证范围

LangSmith 密钥只保存在后端 `.env`，不放入 Vite 环境变量或前端产物。`LANGSMITH_PROJECT` 必须与网页端选中的环境同名（本机为 `eshop-assistant-local`），只改 Agent ID 或环境变量都不足以让 trace 出现在对应页面。默认追踪关闭，缺少密钥时不影响业务运行。

本地 SQLite 回归与前端构建成功，不等于 MySQL、模型上游、Milvus 或 LangSmith 云端已经验证。云端 trace、真实模型调用与 Milvus 检索需分别验收，记录见 [docs/validation.md](docs/validation.md)。
