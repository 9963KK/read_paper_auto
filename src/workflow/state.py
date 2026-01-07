"""
LangGraph 工作流状态定义
"""
from typing import TypedDict, Optional, List, Literal
from enum import Enum


class DecisionType(str, Enum):
    """决策类型"""
    DEEP_READ = "deep_read"
    SKIM = "skim"
    DROP = "drop"


class PaperState(TypedDict, total=False):
    """论文处理状态"""
    
    # 输入
    paper_id: str  # 由 URL/DOI hash 生成
    source_url: str
    source_type: Literal["arxiv", "pdf", "url"]
    
    # 元信息
    title: Optional[str]
    authors: Optional[List[str]]
    year: Optional[int]
    abstract: Optional[str]
    pdf_url: Optional[str]  # PDF URL（用于 OpenAI 直接读取）
    
    # Triage 结果
    triage_summary: Optional[str]  # 概要
    triage_contributions: Optional[str]  # 贡献点
    triage_limitations: Optional[str]  # 局限性
    triage_relevance: Optional[int]  # 相关性评分 1-5
    triage_suggested_action: Optional[DecisionType]  # LLM 建议
    triage_suggested_tags: Optional[List[str]]  # 建议的文章方向
    
    # Craft 归档
    craft_collection_item_id: Optional[str]
    craft_reading_doc_id: Optional[str]
    
    # 人工决策
    human_decision: Optional[DecisionType]
    human_tags: Optional[List[str]]
    human_comment: Optional[str]
    
    # Deep Read 结果
    deep_read_overview: Optional[str]  # 📜 文章概述
    deep_read_innovations: Optional[str]  # 💡创新点
    deep_read_directions: Optional[str]  # 🌌可能结合的方向
    
    # 状态
    status: Literal["ingesting", "extracting", "triaging", "waiting_decision", "deep_reading", "completed", "failed"]
    error_message: Optional[str]
