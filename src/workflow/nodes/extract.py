"""
Extract 节点 - 提取论文内容（已优化为直接使用 PDF URL）
"""
from loguru import logger
from src.workflow.state import PaperState


async def extract_node(state: PaperState) -> PaperState:
    """
    提取论文内容（现在只是状态更新，实际提取由 OpenAI 完成）

    Args:
        state: 包含 pdf_url 的状态

    Returns:
        更新状态为 triaging
    """
    try:
        # 安全访问字段
        title = state.get("title", "<unknown>")
        logger.info(f"Extract node: {title}")

        # 检查是否有 PDF URL
        if not state.get("pdf_url"):
            raise ValueError("No PDF URL found")

        # 更新状态
        state["status"] = "triaging"

        logger.info(f"Extract completed, PDF URL ready: {state['pdf_url']}")
        return state

    except Exception as e:
        logger.exception(f"Extract failed: {e}")
        state["status"] = "failed"
        state["error_message"] = str(e)
        return state
