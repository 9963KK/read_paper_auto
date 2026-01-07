"""
Archive 节点 - 归档到 Craft
"""
from loguru import logger
from src.workflow.state import PaperState, DecisionType
from src.services.craft_client import craft_client


async def archive_base_node(state: PaperState) -> PaperState:
    """
    创建基础归档条目到 Craft Collection

    Args:
        state: 包含 title, source_url, triage_summary, triage_suggested_tags

    Returns:
        更新后的 state，包含 craft_collection_item_id
    """
    try:
        # 安全访问必填字段
        title = state.get("title", "<unknown>")
        logger.info(f"Archive base node: {title}")

        # 幂等性检查：如果已创建则跳过
        if state.get("craft_collection_item_id"):
            logger.info(f"Collection item already exists: {state['craft_collection_item_id']}, skipping creation")
            state["status"] = "waiting_decision"
            return state

        # 规范化可选字段
        tags = state.get("triage_suggested_tags") or []
        summary = state.get("triage_summary") or ""
        source_url = state.get("source_url", "")

        # 创建 Collection 条目
        item_id = await craft_client.add_collection_item(
            title=title,
            link=source_url,
            summary=summary,
            tags=tags,
            is_deep_read=False  # 初始状态为非精读
        )

        # 更新 state（立即保存，触发 checkpoint）
        state["craft_collection_item_id"] = item_id
        state["status"] = "waiting_decision"

        logger.info(f"Base archive created: {item_id}")
        return state

    except Exception as e:
        logger.exception(f"Archive base failed: {e}")
        state["status"] = "failed"
        state["error_message"] = str(e)
        return state


async def update_archive_node(state: PaperState) -> PaperState:
    """
    更新归档条目（精读后）

    Args:
        state: 包含 craft_collection_item_id, human_decision, craft_reading_doc_id

    Returns:
        更新后的 state
    """
    try:
        # 安全访问必填字段
        title = state.get("title", "<unknown>")
        logger.info(f"Update archive node: {title}")

        item_id = state.get("craft_collection_item_id")
        if not item_id:
            raise ValueError("No collection item ID found")

        # 判断是否精读 - 使用字符串比较以兼容序列化
        human_decision = state.get("human_decision")
        is_deep_read = (
            human_decision == DecisionType.DEEP_READ or
            human_decision == "deep_read" or
            str(human_decision) == "deep_read"
        )

        # 更新 Collection 条目
        await craft_client.update_collection_item(
            item_id=item_id,
            is_deep_read=is_deep_read,
            reading_doc_id=state.get("craft_reading_doc_id"),
            comment=state.get("human_comment"),
            tags=state.get("human_tags"),
            title=title,
        )

        # 更新状态
        state["status"] = "completed"

        logger.info(f"Archive updated: {item_id}")
        return state

    except Exception as e:
        logger.exception(f"Update archive failed: {e}")
        state["status"] = "failed"
        state["error_message"] = str(e)
        return state
