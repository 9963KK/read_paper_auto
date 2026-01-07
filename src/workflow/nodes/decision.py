"""
Decision 节点 - 处理人工决策
"""
from loguru import logger
from langgraph.errors import GraphInterrupt
from langgraph.types import interrupt
from src.workflow.state import PaperState
from src.workflow.nodes.triage import _coerce_decision_type


async def decision_node(state: PaperState) -> PaperState:
    """
    人工决策节点 - 使用 interrupt 等待用户决策

    Args:
        state: 包含 triage 结果的状态

    Returns:
        更新后的 state，包含 human_decision, human_tags, human_comment
    """
    try:
        # 安全访问必填字段
        title = state.get("title", "<unknown>")
        paper_id = state.get("paper_id", "<unknown>")

        logger.info(f"Decision node: {title}")

        # 构建决策包
        decision_payload = {
            "paper_id": paper_id,
            "title": title,
            "source_url": state.get("source_url", ""),
            "triage_summary": state.get("triage_summary", ""),
            "triage_contributions": state.get("triage_contributions", ""),
            "triage_relevance": state.get("triage_relevance", 3),
            "triage_suggested_action": getattr(state.get("triage_suggested_action"), "value", state.get("triage_suggested_action", "skim")),
            "triage_suggested_tags": state.get("triage_suggested_tags", []),
        }

        logger.info(f"Waiting for human decision: {paper_id}")

        # 使用 interrupt 等待人工决策
        # 注意：interrupt 可能通过抛出异常实现暂停，不应该被捕获
        # 这里将 interrupt 调用移到 try 外，或者明确排除 interrupt 异常
        human_input = interrupt(decision_payload)

        # 处理人工决策 - 使用 _coerce_decision_type 进行安全转换
        state["human_decision"] = _coerce_decision_type(human_input.get("decision"))
        state["human_tags"] = human_input.get("tags", state.get("triage_suggested_tags", []))
        state["human_comment"] = human_input.get("comment", "")

        logger.info(f"Human decision received: {getattr(state['human_decision'], 'value', state['human_decision'])}")

        return state

    except GraphInterrupt:
        raise
    except Exception as e:
        # 只捕获业务异常，不捕获 LangGraph 的控制流异常
        # 注意：如果 LangGraph 使用特定异常类型实现 interrupt,
        # 应该在这里显式 re-raise，例如:
        # except GraphInterrupt:
        #     raise
        logger.error(f"Decision node failed: {e}")
        state["status"] = "failed"
        state["error_message"] = str(e)
        return state
