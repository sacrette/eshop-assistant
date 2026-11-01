export PYTHONUTF8 = 1

.PHONY: help dev test frontend build seed-demo kb-build kb-vectorize kb-mine kb-repatch eval-rag eval-flywheel calibrate-confidence cost-report mcp-logistics mcp-aftersales milvus-up

help:
	@echo "dev | frontend | build | seed-demo | test | kb-build | kb-vectorize | cost-report"

dev:
	uv run python -m scripts.dev

frontend:
	cd frontend && npm run dev

build:
	cd frontend && npm run build

seed-demo:
	uv run python -m scripts.init_demo

test:
	uv run python -m scripts.verify

kb-build:
	uv run python -m scripts.build_kb

kb-vectorize:
	uv run python -m scripts.vectorize_kb

kb-mine:
	uv run python -m scripts.mine_knowledge

kb-repatch:
	uv run python -m scripts.kb_repatch

eval-rag:
	uv run python -m scripts.eval_rag

eval-flywheel:
	uv run python -m scripts.eval_flywheel

calibrate-confidence:
	uv run python -m scripts.calibrate_confidence

cost-report:
	uv run python -m scripts.cost_by_intent

mcp-logistics:
	uv run python -m mcp_servers.logistics_server

mcp-aftersales:
	uv run python -m mcp_servers.aftersales_server

milvus-up:
	docker compose up -d
