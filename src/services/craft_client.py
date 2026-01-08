"""
Craft API 客户端
"""
import ast
import httpx
from typing import List, Dict, Any, Optional, Iterable
from loguru import logger

from src.config import settings


class CraftClient:
    """Craft API 客户端"""
    
    def __init__(self):
        self.base_url = settings.craft_api_base_url
        self.collection_id = settings.craft_collection_id
        self.template_id = settings.craft_reading_template_id
        self.papers_folder_id = settings.craft_papers_folder_id
        self.client = httpx.AsyncClient(timeout=30.0)

    async def list_collection_items(self) -> List[Dict[str, Any]]:
        """列出 collection 的所有 items。"""
        url = f"{self.base_url}/collections/{self.collection_id}/items"
        response = await self.client.get(url)
        response.raise_for_status()
        data = response.json()
        items = data.get("items")
        return items if isinstance(items, list) else []

    async def list_documents(
        self,
        folder_id: Optional[str] = None,
        fetch_metadata: bool = True,
    ) -> List[Dict[str, Any]]:
        """列出 Craft 文档（可按 folderId 过滤）。"""
        url = f"{self.base_url}/documents"
        params: Dict[str, Any] = {}
        if folder_id:
            params["folderId"] = folder_id
        if fetch_metadata:
            params["fetchMetadata"] = "true"

        response = await self.client.get(url, params=params)
        response.raise_for_status()
        data = response.json()
        items = data.get("items")
        return items if isinstance(items, list) else []

    async def get_block_tree(self, block_id: str, max_depth: int = 3) -> Dict[str, Any]:
        """获取 block 树（用于读取文档内容）。"""
        url = f"{self.base_url}/blocks"
        params: Dict[str, Any] = {"id": block_id, "maxDepth": max_depth}
        response = await self.client.get(url, params=params)
        response.raise_for_status()
        data = response.json()
        return data if isinstance(data, dict) else {}
    
    async def close(self):
        """关闭客户端"""
        await self.client.aclose()
    
    async def add_collection_item(
        self,
        title: str,
        link: str,
        summary: str,
        tags: List[str],
        is_deep_read: bool = False,
        reading_doc_id: Optional[str] = None,
        comment: Optional[str] = None
    ) -> str:
        """
        添加论文到 Collection
        
        Args:
            title: 论文标题
            link: 论文链接
            summary: 概要
            tags: 文章方向标签
            is_deep_read: 是否精读
            reading_doc_id: 精读文档 ID
            comment: 评论
            
        Returns:
            Collection item ID
        """
        url = f"{self.base_url}/collections/{self.collection_id}/items"
        
        properties: Dict[str, Any] = {
            "": tags,  # 文章方向 (multi-select)
            "_2": link,  # 链接
            "_3": summary,  # 概要
            "_5": "Yes" if is_deep_read else "No",  # 是否精读
        }
        
        # 如果有精读文档，添加 block link
        if reading_doc_id:
            properties["_4"] = {
                "title": title,
                "blockId": reading_doc_id,
                "reference": {"blockId": reading_doc_id}
            }
        
        # 如果有评论，添加评论
        if comment:
            properties["_7"] = comment
        
        payload = {
            "items": [
                {
                    "title": title,
                    "properties": properties
                }
            ]
        }
        
        logger.info(f"Adding collection item: {title}")
        response = await self.client.post(url, json=payload)
        response.raise_for_status()
        
        result = response.json()
        item_id = result["items"][0]["id"]
        logger.info(f"Collection item created: {item_id}")
        
        return item_id
    
    async def update_collection_item(
        self,
        item_id: str,
        is_deep_read: Optional[bool] = None,
        reading_doc_id: Optional[str] = None,
        comment: Optional[str] = None,
        tags: Optional[List[str]] = None,
        title: Optional[str] = None,
    ):
        """
        更新 Collection item
        
        Args:
            item_id: Item ID
            is_deep_read: 是否精读
            reading_doc_id: 精读文档 ID
            comment: 评论
            tags: 文章方向标签
        """
        url = f"{self.base_url}/collections/{self.collection_id}/items"
        
        properties: Dict[str, Any] = {}
        
        if is_deep_read is not None:
            properties["_5"] = "Yes" if is_deep_read else "No"
        
        if reading_doc_id:
            properties["_4"] = {
                "title": title or "",
                "blockId": reading_doc_id,
                "reference": {"blockId": reading_doc_id}
            }
        
        if comment:
            properties["_7"] = comment
        
        if tags:
            properties[""] = tags
        
        payload = {
            "itemsToUpdate": [
                {
                    "id": item_id,
                    "properties": properties
                }
            ]
        }
        
        logger.info(f"Updating collection item: {item_id}")
        response = await self.client.put(url, json=payload)
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as e:
            body = (e.response.text or "")[:2000]
            logger.error(
                f"Craft update_collection_item HTTP error: status={e.response.status_code} item_id={item_id} body={body}"
            )
            raise
        logger.info(f"Collection item updated: {item_id}")
    
    async def create_reading_document(
        self,
        title: str,
        overview: str,
        innovations: str,
        directions: str
    ) -> str:
        """
        创建精读文档（基于模板）
        
        Args:
            title: 论文标题
            overview: 文章概述
            innovations: 创新点
            directions: 可能结合的方向
            
        Returns:
            Document ID
        """
        # 1. 创建新文档
        doc_url = f"{self.base_url}/documents"
        doc_payload = {
            "documents": [
                {
                    "title": f"【精读】{title}"
                }
            ]
        }
        if self.papers_folder_id:
            doc_payload["destination"] = {"folderId": self.papers_folder_id}
        
        logger.info(f"Creating reading document: {title}")
        response = await self.client.post(doc_url, json=doc_payload)
        response.raise_for_status()
        
        doc_id = response.json()["items"][0]["id"]

        # 2. 按“精读模板”填充内容（若模板不可用则降级为内置结构）
        content_markdown = await self._build_reading_markdown(
            overview=overview,
            innovations=innovations,
            directions=directions,
        )

        blocks_url = f"{self.base_url}/blocks"
        blocks_payload = {
            "markdown": content_markdown,
            "position": {"position": "end", "pageId": doc_id},
        }

        response = await self.client.post(blocks_url, json=blocks_payload)
        response.raise_for_status()
        
        logger.info(f"Reading document created: {doc_id}")
        return doc_id

    @staticmethod
    def _format_section_text(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, str):
            text = value.strip()
            if text.startswith("[") and text.endswith("]"):
                try:
                    parsed = ast.literal_eval(text)
                    if isinstance(parsed, list):
                        value = parsed
                    else:
                        return text
                except Exception:
                    return text
            else:
                return text
        if isinstance(value, Iterable):
            parts: List[str] = []
            for item in value:
                text = str(item).strip()
                if text:
                    parts.append(f"- {text}")
            return "\n".join(parts).strip()
        return str(value).strip()

    async def _build_reading_markdown(
        self,
        overview: Any,
        innovations: Any,
        directions: Any,
    ) -> str:
        replacements = {
            "overview": self._format_section_text(overview),
            "innovations": self._format_section_text(innovations),
            "directions": self._format_section_text(directions),
            "thoughts": "[待填写]",
        }

        if not self.template_id:
            return self._build_fallback_reading_markdown(replacements)

        template_url = f"{self.base_url}/blocks?id={self.template_id}"
        try:
            response = await self.client.get(template_url)
            response.raise_for_status()
            template = response.json()
        except Exception as e:
            logger.warning(f"Failed to load Craft reading template, fallback to default: {e}")
            return self._build_fallback_reading_markdown(replacements)

        content = template.get("content") if isinstance(template, dict) else None
        if not isinstance(content, list) or not content:
            return self._build_fallback_reading_markdown(replacements)

        blocks: List[str] = []
        current_section: Optional[str] = None
        inserted: set[str] = set()

        def _section_for_heading(markdown: str) -> Optional[str]:
            if not markdown:
                return None
            if "文章概述" in markdown:
                return "overview"
            if "创新点" in markdown:
                return "innovations"
            if "可能结合的方向" in markdown:
                return "directions"
            if "思考" in markdown or "感想" in markdown:
                return "thoughts"
            return None

        for block in content:
            if not isinstance(block, dict):
                continue

            markdown = (block.get("markdown") or "").rstrip()
            text_style = block.get("textStyle")

            if text_style in {"h1", "h2", "h3", "h4", "h5", "h6"} and markdown:
                current_section = _section_for_heading(markdown) or current_section
                blocks.append(markdown)
                continue

            if current_section and not markdown and current_section not in inserted:
                replacement = replacements.get(current_section, "")
                blocks.append(replacement)
                inserted.add(current_section)
                continue

            blocks.append(markdown)

        return "\n\n".join([b for b in blocks if b is not None]).strip() + "\n"

    @staticmethod
    def _build_fallback_reading_markdown(replacements: Dict[str, str]) -> str:
        overview = replacements.get("overview", "")
        innovations = replacements.get("innovations", "")
        directions = replacements.get("directions", "")
        thoughts = replacements.get("thoughts", "[待填写]")
        return (
            "# 📜 文章概述\n\n"
            f"{overview}\n\n"
            "# 💡创新点\n\n"
            f"{innovations}\n\n"
            "# 🌌可能结合的方向\n\n"
            f"{directions}\n\n"
            "# 🤔思考和感想\n\n"
            f"{thoughts}\n"
        )
    
    async def get_collection_item(self, item_id: str) -> Dict[str, Any]:
        """获取 Collection item"""
        url = f"{self.base_url}/collections/{self.collection_id}/items"
        response = await self.client.get(url)
        response.raise_for_status()
        
        items = response.json()["items"]
        for item in items:
            if item["id"] == item_id:
                return item
        
        raise ValueError(f"Collection item not found: {item_id}")

    async def write_thoughts_to_reading_document(self, doc_id: str, thoughts: str) -> str:
        """
        将用户的「思考和感想」写入精读文档。

        优先策略：
        1) 若存在「思考和感想」标题：把本次感想作为新内容追加到文档末尾（该 section 在模板里位于末尾）
        2) 若标题后的占位符块为「[待填写]」，则在追加成功后删除该占位符块
        3) 若找不到标题，则在末尾补上标题并追加

        Returns:
            doc_id（或被删除的占位符 block_id 作为辅助信息）
        """
        thoughts_md = (thoughts or "").strip()
        if not thoughts_md:
            raise ValueError("Empty thoughts")

        url = f"{self.base_url}/blocks"
        response = await self.client.get(url, params={"id": doc_id, "maxDepth": 1})
        response.raise_for_status()
        root = response.json()

        content = root.get("content") if isinstance(root, dict) else None
        if not isinstance(content, list):
            content = []

        def _is_text_block(block: Any) -> bool:
            return isinstance(block, dict) and block.get("type") == "text" and isinstance(block.get("id"), str)

        def _get_markdown(block: Any) -> str:
            if not isinstance(block, dict):
                return ""
            value = block.get("markdown")
            return value if isinstance(value, str) else ""

        def _contains_thoughts_heading(markdown: str) -> bool:
            md = markdown or ""
            return ("思考" in md and "感想" in md) or ("🤔" in md and ("思考" in md or "感想" in md))

        heading_index: Optional[int] = None
        for idx, block in enumerate(content):
            if not isinstance(block, dict):
                continue
            if _contains_thoughts_heading(_get_markdown(block)):
                heading_index = idx
                break

        def _is_placeholder_only(markdown: str) -> bool:
            md = (markdown or "").strip()
            return md in {"[待填写]", "待填写"}

        placeholder_block_id: Optional[str] = None
        has_heading = heading_index is not None
        if heading_index is not None:
            # 仅删除纯占位符块，避免误删用户已有内容
            for j in range(heading_index + 1, len(content)):
                block = content[j]
                if not _is_text_block(block):
                    continue
                md = _get_markdown(block)
                if _is_placeholder_only(md):
                    placeholder_block_id = block.get("id")
                break

        # 追加到文档末尾：POST /blocks 支持 markdown 生成多个 blocks（更适合多次追加/多段内容）
        insert_markdown = thoughts_md.rstrip() + "\n"
        if not has_heading:
            insert_markdown = f"# 🤔思考和感想\n\n{insert_markdown}"

        insert_payload = {
            "markdown": insert_markdown,
            "position": {"position": "end", "pageId": doc_id},
        }
        insert_resp = await self.client.post(url, json=insert_payload)
        try:
            insert_resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            body = (e.response.text or "")[:2000]
            logger.error(f"Craft write_thoughts insert HTTP error: status={e.response.status_code} doc_id={doc_id} body={body}")
            raise

        # 删除占位符（如果存在）
        if placeholder_block_id:
            delete_payload = {"blockIds": [placeholder_block_id]}
            delete_resp = await self.client.request("DELETE", url, json=delete_payload)
            try:
                delete_resp.raise_for_status()
            except httpx.HTTPStatusError as e:
                body = (e.response.text or "")[:2000]
                logger.error(
                    f"Craft write_thoughts delete placeholder HTTP error: status={e.response.status_code} doc_id={doc_id} block_id={placeholder_block_id} body={body}"
                )
                # 删除失败不影响感想已写入；不抛异常

        return placeholder_block_id or doc_id


# 全局客户端实例
craft_client = CraftClient()
