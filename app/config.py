from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    chat_model: str = ""
    chat_base_url: str = ""
    chat_api_key: str = ""
    embed_base_url: str = "https://api.siliconflow.cn/v1"
    embed_api_key: str = ""
    rerank_base_url: str = "https://api.siliconflow.cn/v1"
    rerank_api_key: str = ""
    chat_thinking: str = ""
    chat_reasoning_effort: str = ""
    chat_reasoning_split: str = ""
    token_budget: int = 2000
    database_url: str = "mysql+asyncmy://root:root@localhost:3307/eshop_assistant"
    test_database_url: str = "mysql+asyncmy://root:root@localhost:3307/eshop_assistant_test"
    embed_model: str = "BAAI/bge-m3"
    milvus_uri: str = "http://localhost:19531"
    milvus_collection: str = "eshop_knowledge"
    rerank_model: str = "BAAI/bge-reranker-v2-m3"
    recall_top_k: int = 50
    rerank_top_k: int = 10
    subquery_split: bool = True
    rerank_min_score: float = 0.3
    max_agent_steps: int = 6
    checkpointer_db_path: str = "data/conversation_checkpoints.sqlite"
    intent_model: str = ""
    summary_trigger_messages: int = 30
    context_window_turns: int = 8
    context_window_max_tokens: int = 3000
    summary_model: str = ""
    mcp_logistics_url: str = "http://127.0.0.1:8111/mcp"
    mcp_aftersales_url: str = "http://127.0.0.1:8112/mcp"
    tool_default_timeout: float = 5.0
    mcp_tool_timeout: float = 10.0
    tool_max_retries: int = 2
    demo_ticket_delay_seconds: float = 0.0
    langsmith_tracing: bool = False
    langsmith_api_key: str = ""
    langsmith_endpoint: str = "https://api.smith.langchain.com"
    langsmith_project: str = "eshop-assistant-local"
    langsmith_workspace_id: str = ""
    langsmith_hide_inputs: bool = True
    cookie_secure: bool = False
    session_hours: int = 12
    demo_accounts_enabled: bool = False
    demo_password: str = ""
    retrieval_warmup: bool = False
    evidence_confidence_threshold: float = 0.26


settings = Settings()
