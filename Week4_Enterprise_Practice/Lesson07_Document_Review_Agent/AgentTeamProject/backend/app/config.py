from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com/v1"
    deepseek_model: str = "deepseek-chat"
    review_llm_api_key: str = ""
    review_llm_base_url: str = ""
    review_llm_model: str = ""
    siliconflow_api_key: str = ""
    siliconflow_base_url: str = "https://api.siliconflow.cn/v1"
    siliconflow_embedding_model: str = "Qwen/Qwen3-Embedding-8B"
    siliconflow_embedding_dimensions: int = 4096
    siliconflow_reranker_model: str = "Qwen/Qwen3-Reranker-8B"
    siliconflow_reranker_instruction: str = "请根据水土保持方案审查规则查询，对候选证据片段进行相关性排序，优先保留能支撑规则判断、字段缺失或跨章节一致性核验的片段。"
    rag_top_k: int = 16
    rag_rerank_top_n: int = 10
    rag_max_issues: int = 20
    langextract_enabled: bool = True
    langextract_extraction_passes: int = 2
    langextract_max_workers: int = 6
    langextract_max_char_buffer: int = 3000
    langextract_max_chunks: int = 24
    langextract_request_timeout: int = 120
    database_url: str = "sqlite:///./contract_review.db"
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    debug: bool = True
    secret_key: str = "dev-secret-key"
    storage_path: str = "./storage"

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()


def get_llm():
    from langchain_openai import ChatOpenAI

    api_key = settings.review_llm_api_key or settings.deepseek_api_key
    base_url = settings.review_llm_base_url or settings.deepseek_base_url
    model = settings.review_llm_model or settings.deepseek_model
    if not api_key:
        raise RuntimeError("REVIEW_LLM_API_KEY or DEEPSEEK_API_KEY is required for rule adjudication")

    return ChatOpenAI(
        model=model,
        api_key=api_key,
        base_url=base_url,
        temperature=0.1,
        timeout=90,
        max_retries=1,
    )
