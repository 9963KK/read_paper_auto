"""
API Schemas - Pydantic 模型
"""
from typing import Optional, List, Literal
from pydantic import BaseModel


class TriageRequest(BaseModel):
    """Triage 请求"""
    source_url: str
    source_type: Literal["arxiv", "pdf", "url"] = "arxiv"


class ResumeRequest(BaseModel):
    """Resume 请求"""
    paper_id: str
    decision: Literal["deep_read", "skim", "drop"]
    tags: Optional[List[str]] = None
    comment: Optional[str] = None


class FeishuMessageEvent(BaseModel):
    """飞书消息事件"""
    type: str
    event: Optional[dict] = None
    challenge: Optional[str] = None
    token: Optional[str] = None


class FeishuCardAction(BaseModel):
    """飞书卡片动作"""
    type: str
    event: Optional[dict] = None
    token: Optional[str] = None


class PaperStatusResponse(BaseModel):
    """论文状态响应"""
    paper_id: str
    status: str
    title: Optional[str] = None
    source_url: Optional[str] = None
    triage_summary: Optional[str] = None
    human_decision: Optional[str] = None
    craft_item_id: Optional[str] = None
    craft_reading_doc_id: Optional[str] = None
    error_message: Optional[str] = None


class DifyTriageResponse(BaseModel):
    """Dify: 同步返回 Triage 结果（执行到 waiting_decision）"""
    paper_id: str
    status: str
    source_url: Optional[str] = None
    title: Optional[str] = None
    abstract: Optional[str] = None
    pdf_url: Optional[str] = None

    triage_summary: Optional[str] = None
    triage_contributions: Optional[str] = None
    triage_limitations: Optional[str] = None
    triage_relevance: Optional[int] = None
    triage_suggested_action: Optional[str] = None
    triage_suggested_tags: Optional[List[str]] = None

    craft_collection_item_id: Optional[str] = None
    craft_reading_doc_id: Optional[str] = None
    error_message: Optional[str] = None


class DifyResumeResponse(BaseModel):
    """Dify: 同步返回 Resume 结果（执行到 completed/failed）"""
    paper_id: str
    status: str
    title: Optional[str] = None
    human_decision: Optional[str] = None
    craft_collection_item_id: Optional[str] = None
    craft_reading_doc_id: Optional[str] = None
    error_message: Optional[str] = None
