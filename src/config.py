"""
配置管理模块
"""
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional


class Settings(BaseSettings):
    """应用配置"""
    
    # LLM 配置
    llm_base_url: str = "https://api.openai.com/v1"
    llm_api_key: str
    llm_model_name: str = "gpt-4"

    # ASIDE LLM（用于轻量任务：抽链接/分类/清洗等）
    # 不填则默认复用主 LLM 配置
    aside_llm_base_url: Optional[str] = None
    aside_llm_api_key: Optional[str] = None
    aside_llm_model_name: Optional[str] = None
    
    # Craft API
    craft_api_base_url: str
    craft_collection_id: str
    craft_reading_template_id: str
    craft_papers_folder_id: Optional[str] = None
    
    # 飞书机器人
    feishu_app_id: str
    feishu_app_secret: str
    feishu_verification_token: str
    feishu_encrypt_key: Optional[str] = None
    
    # 服务配置
    server_host: str = "0.0.0.0"
    server_port: int = 8000
    
    # 持久化
    sqlite_db_path: str = "./data/workflow.db"
    
    # 日志
    log_level: str = "INFO"

    # 个性化：精读 prompt 风格指南（可选）
    # 指向一个本地文件路径；文件内容会被拼接到 deep_read 的 system prompt 中
    deep_read_style_guide_path: Optional[str] = None

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


# 全局配置实例
settings = Settings()
