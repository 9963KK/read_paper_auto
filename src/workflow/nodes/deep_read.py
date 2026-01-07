"""
Deep Read 节点 - 生成精读笔记并创建 Craft 文档
"""
from loguru import logger
from src.workflow.state import PaperState
from src.services.llm_client import llm_client
from src.services.craft_client import craft_client


async def deep_read_node(state: PaperState) -> PaperState:
    """
    生成精读笔记并创建 Craft 精读文档

    Args:
        state: 包含 title, abstract, triage_summary, pdf_url

    Returns:
        更新后的 state，包含 deep_read_overview, deep_read_innovations,
        deep_read_directions, craft_reading_doc_id
    """
    try:
        # 安全访问必填字段
        title = state.get("title", "<unknown>")
        logger.info(f"Deep read node: {title}")

        # 幂等性检查：如果已创建精读文档则跳过
        if state.get("craft_reading_doc_id"):
            logger.info(f"Reading doc already exists: {state['craft_reading_doc_id']}, skipping creation")
            return state

        # 1. 调用 LLM 生成精读笔记
        state["status"] = "deep_reading"

        result = await llm_client.generate_deep_read(
            title=title,
            abstract=state.get("abstract", ""),
            triage_summary=state.get("triage_summary", ""),
            pdf_url=state.get("pdf_url")
        )

        # 2. 保存精读结果到 state
        state["deep_read_overview"] = result.get("overview", "")
        state["deep_read_innovations"] = result.get("innovations", "")
        state["deep_read_directions"] = result.get("directions", "")

        logger.info(f"Deep read content generated for: {title}")

        # 3. 创建 Craft 精读文档
        doc_id = await craft_client.create_reading_document(
            title=title,
            overview=state["deep_read_overview"],
            innovations=state["deep_read_innovations"],
            directions=state["deep_read_directions"]
        )

        # 立即保存 doc_id（触发 checkpoint）
        state["craft_reading_doc_id"] = doc_id

        logger.info(f"Craft reading document created: {doc_id}")
        logger.info(f"Deep read completed for: {title}")

        return state

    except Exception as e:
        logger.exception(f"Deep read failed: {e}")
        state["status"] = "failed"
        state["error_message"] = str(e)
        return state
