"""
LangGraph 工作流定义
"""
from typing import Literal
from langgraph.graph import StateGraph, END
from loguru import logger

from src.workflow.state import PaperState, DecisionType
from src.workflow.nodes.ingest import ingest_node
from src.workflow.nodes.extract import extract_node
from src.workflow.nodes.triage import triage_node
from src.workflow.nodes.archive import archive_base_node, update_archive_node
from src.workflow.nodes.decision import decision_node
from src.workflow.nodes.deep_read import deep_read_node
from src.persistence.checkpointer import get_checkpointer


def route_on_failure(state: PaperState) -> Literal["continue", "end"]:
    if state.get("status") == "failed":
        return "end"
    return "continue"


def route_after_decision(state: PaperState) -> Literal["deep_read", "update_archive", "end"]:
    """
    条件分支：判断是否需要精读

    Args:
        state: 工作流状态

    Returns:
        "deep_read" / "update_archive" / "end"
    """
    if state.get("status") == "failed":
        return "end"

    decision = state.get("human_decision")
    if decision == DecisionType.DEEP_READ:
        logger.info(f"Routing to deep_read for: {state.get('title', '<unknown>')}")
        return "deep_read"
    else:
        logger.info(
            f"Routing to update_archive for: {state.get('title', '<unknown>')} (decision: {getattr(decision, 'value', decision)})"
        )
        return "update_archive"


def create_workflow():
    """
    创建 LangGraph 工作流

    Returns:
        编译后的工作流图
    """
    # 创建状态图
    workflow = StateGraph(PaperState)

    # 添加节点
    workflow.add_node("ingest", ingest_node)
    workflow.add_node("extract", extract_node)
    workflow.add_node("triage", triage_node)
    workflow.add_node("archive_base", archive_base_node)
    workflow.add_node("decision", decision_node)
    workflow.add_node("deep_read", deep_read_node)
    workflow.add_node("update_archive", update_archive_node)

    # 设置入口点
    workflow.set_entry_point("ingest")

    # 添加边
    workflow.add_conditional_edges(
        "ingest",
        route_on_failure,
        {
            "continue": "extract",
            "end": END,
        },
    )
    workflow.add_conditional_edges(
        "extract",
        route_on_failure,
        {
            "continue": "triage",
            "end": END,
        },
    )
    workflow.add_conditional_edges(
        "triage",
        route_on_failure,
        {
            "continue": "archive_base",
            "end": END,
        },
    )
    workflow.add_conditional_edges(
        "archive_base",
        route_on_failure,
        {
            "continue": "decision",
            "end": END,
        },
    )

    # 添加条件分支（从 decision 节点）
    workflow.add_conditional_edges(
        "decision",
        route_after_decision,
        {
            "deep_read": "deep_read",
            "update_archive": "update_archive",
            "end": END,
        }
    )

    # 从 deep_read 到 update_archive
    workflow.add_conditional_edges(
        "deep_read",
        route_on_failure,
        {
            "continue": "update_archive",
            "end": END,
        },
    )

    # 从 update_archive 到 END
    workflow.add_edge("update_archive", END)

    # 获取 checkpointer
    checkpointer = get_checkpointer()

    # 编译工作流（在 decision 节点内使用 interrupt）
    app = workflow.compile(checkpointer=checkpointer)

    logger.info("Workflow created successfully")

    return app


# 全局工作流实例
workflow_app = create_workflow()
