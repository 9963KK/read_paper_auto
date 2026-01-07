"""
Ingest 节点 - 接收论文输入并解析元信息
"""
from loguru import logger
from src.workflow.state import PaperState
from src.services.paper_parser import paper_parser


async def ingest_node(state: PaperState) -> PaperState:
    """
    接收论文 URL 并解析元信息

    Args:
        state: 包含 source_url 和 source_type

    Returns:
        更新后的 state，包含 paper_id, title, authors, year, abstract, pdf_url
    """
    try:
        # 安全访问必填字段
        source_url = state.get("source_url")
        if not source_url:
            raise ValueError("Missing required field: source_url")

        logger.info(f"Ingest node: {source_url}")

        source_type = state.get("source_type", "arxiv")

        if source_type == "arxiv":
            # 解析 arXiv 论文
            result = await paper_parser.parse_arxiv(source_url)

            # 更新 state
            state.update({
                "paper_id": result["paper_id"],
                "title": result["title"],
                "authors": result["authors"],
                "year": result["year"],
                "abstract": result["abstract"],
                "pdf_url": result["pdf_url"],
                "status": "extracting"
            })

        elif source_type == "pdf":
            # PDF 文件上传场景（暂不实现）
            raise NotImplementedError("PDF file upload not implemented yet")

        else:
            raise ValueError(f"Unsupported source type: {source_type}")

        logger.info(f"Ingest completed: {state.get('title', '<unknown>')}")
        return state

    except Exception as e:
        logger.exception(f"Ingest failed: {e}")
        state["status"] = "failed"
        state["error_message"] = str(e)
        return state
