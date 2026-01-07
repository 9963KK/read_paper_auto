"""
Triage 节点 - LLM 分析论文
"""
from loguru import logger
from src.workflow.state import PaperState, DecisionType
from src.services.llm_client import llm_client


def _coerce_decision_type(value: object) -> DecisionType:
    if isinstance(value, DecisionType):
        return value
    if isinstance(value, str):
        try:
            return DecisionType(value)
        except ValueError:
            pass
    return DecisionType.SKIM


async def triage_node(state: PaperState) -> PaperState:
    """
    使用 LLM 分析论文并生成 Triage 结果

    Args:
        state: 包含 title, abstract, pdf_url

    Returns:
        更新后的 state，包含 triage_summary, triage_contributions,
        triage_limitations, triage_relevance, triage_suggested_action, triage_suggested_tags
    """
    try:
        # 安全访问必填字段
        title = state.get("title")
        abstract = state.get("abstract")

        if not title:
            raise ValueError("Missing required field: title")
        if not abstract:
            raise ValueError("Missing required field: abstract")

        logger.info(f"Triage node: {title}")

        # 调用 LLM 生成 Triage 分析
        result = await llm_client.generate_triage(
            title=title,
            abstract=abstract,
            pdf_url=state.get("pdf_url")
        )

        # 更新 state
        state.update({
            "triage_summary": result.get("summary", ""),
            "triage_contributions": result.get("contributions", ""),
            "triage_limitations": result.get("limitations", ""),
            "triage_relevance": result.get("relevance", 3),
            "triage_suggested_action": _coerce_decision_type(result.get("suggested_action")),
            "triage_suggested_tags": result.get("suggested_tags", []),
            "status": "triaging"
        })

        logger.info(f"Triage completed: {title}")
        logger.info(f"Suggested action: {getattr(state['triage_suggested_action'], 'value', state['triage_suggested_action'])}")
        logger.info(f"Suggested tags: {state['triage_suggested_tags']}")

        return state

    except Exception as e:
        logger.exception(f"Triage failed: {e}")
        state["status"] = "failed"
        state["error_message"] = str(e)
        return state
