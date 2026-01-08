#!/usr/bin/env python3
import argparse
import asyncio
import json
from datetime import datetime
from pathlib import Path
import os
import tempfile
import sys
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
os.chdir(REPO_ROOT)

from src.config import settings
from src.services.craft_client import craft_client
from src.services.llm_client import llm_client


HEADING_STYLES = {"h1", "h2", "h3", "h4", "h5", "h6"}


def _parse_iso_datetime(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    text = value.strip()
    if not text:
        return None
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        return datetime.fromisoformat(text)
    except Exception:
        return None


def _flatten_blocks(root: Any) -> List[Dict[str, Any]]:
    flattened: List[Dict[str, Any]] = []

    def _walk(node: Any):
        if not isinstance(node, dict):
            return
        flattened.append(node)
        content = node.get("content")
        if isinstance(content, list):
            for child in content:
                _walk(child)

    _walk(root)
    return flattened


def _contains_thoughts_heading(markdown: str) -> bool:
    md = markdown or ""
    return ("思考" in md and "感想" in md) or ("心得" in md) or ("🤔" in md and ("思考" in md or "感想" in md))


def _is_placeholder_only(markdown: str) -> bool:
    md = (markdown or "").strip()
    return md in {"[待填写]", "待填写"}


def extract_thoughts_section(block_tree: Dict[str, Any]) -> Optional[str]:
    """
    从 Craft 文档 blocks 中抽取「思考和感想」段落内容（不包含标题本身）。
    若未找到该段落，返回 None。
    """
    blocks = _flatten_blocks(block_tree)
    start_index: Optional[int] = None

    for idx, block in enumerate(blocks):
        markdown = block.get("markdown")
        if not isinstance(markdown, str) or not markdown.strip():
            continue
        text_style = block.get("textStyle")
        if text_style in HEADING_STYLES and _contains_thoughts_heading(markdown):
            start_index = idx
            break

    if start_index is None:
        return None

    lines: List[str] = []
    for block in blocks[start_index + 1 :]:
        markdown = block.get("markdown")
        if not isinstance(markdown, str):
            continue
        md = markdown.strip()
        if not md:
            continue
        text_style = block.get("textStyle")
        if text_style in HEADING_STYLES:
            break
        if _is_placeholder_only(md):
            continue
        lines.append(md)

    text = "\n".join(lines).strip()
    return text or None


def _truncate(text: str, max_chars: int) -> str:
    if max_chars <= 0:
        return text
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1].rstrip() + "…"


def _atomic_write_text(path: str, text: str) -> None:
    target = Path(path).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=str(target.parent),
        prefix=target.name + ".",
        suffix=".tmp",
        delete=False,
    ) as f:
        tmp_path = Path(f.name)
        f.write(text)
        f.flush()
        os.fsync(f.fileno())

    os.replace(str(tmp_path), str(target))


def _atomic_write_json(path: str, obj: Any) -> None:
    _atomic_write_text(path, json.dumps(obj, ensure_ascii=False, indent=2) + "\n")


async def _pick_docs_from_folder(
    folder_id: str,
    title_prefix: Optional[str],
    max_docs: int,
) -> List[Tuple[str, str]]:
    docs = await craft_client.list_documents(folder_id=folder_id, fetch_metadata=True)

    picked: List[Dict[str, Any]] = []
    for doc in docs:
        if not isinstance(doc, dict):
            continue
        doc_id = doc.get("id")
        title = doc.get("title")
        if not isinstance(doc_id, str) or not isinstance(title, str):
            continue
        if title_prefix and not title.startswith(title_prefix):
            continue
        picked.append(doc)

    def _sort_key(d: Dict[str, Any]):
        dt = _parse_iso_datetime(d.get("lastModifiedAt")) or _parse_iso_datetime(d.get("createdAt"))
        return dt or datetime.min

    picked.sort(key=_sort_key, reverse=True)
    result: List[Tuple[str, str]] = []
    for doc in picked[:max_docs]:
        result.append((doc["id"], doc["title"]))
    return result


def _extract_reading_doc_id_from_collection_item(item: Dict[str, Any]) -> Optional[str]:
    properties = item.get("properties")
    if not isinstance(properties, dict):
        return None
    reading_prop = properties.get("_4")
    if isinstance(reading_prop, dict):
        block_id = reading_prop.get("blockId")
        if isinstance(block_id, str) and block_id:
            return block_id
        reference = reading_prop.get("reference")
        if isinstance(reference, dict):
            ref_id = reference.get("blockId")
            if isinstance(ref_id, str) and ref_id:
                return ref_id
    return None


def _is_deep_read_collection_item(item: Dict[str, Any]) -> bool:
    properties = item.get("properties")
    if not isinstance(properties, dict):
        return False
    flag = properties.get("_5")
    return str(flag).strip().lower() in {"yes", "true", "1"}


async def _pick_docs_from_collection(max_docs: int) -> List[Tuple[str, str]]:
    items = await craft_client.list_collection_items()

    seen: set[str] = set()
    result: List[Tuple[str, str]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        if not _is_deep_read_collection_item(item):
            continue
        doc_id = _extract_reading_doc_id_from_collection_item(item)
        if not doc_id or doc_id in seen:
            continue
        title = item.get("title")
        if not isinstance(title, str) or not title.strip():
            title = doc_id
        seen.add(doc_id)
        result.append((doc_id, title))
        if len(result) >= max_docs:
            break
    return result


async def build_style_guide(
    samples: List[Dict[str, str]],
    model: str,
) -> Dict[str, str]:
    """
    使用 ASIDE_LLM 从样本中提炼“精读偏好指南”，并生成 deep_read prompt 的可拼接片段。
    """
    system_prompt = """你是一个严格的 Prompt 工程师 + 研究助手。

你将收到若干条“用户在 Craft 精读笔记里的【思考和感想】内容”样本。你的目标是：
1) 归纳用户做精读时真正关心的点（偏好、视角、评估标准、你认为他经常问的问题）。
2) 输出一段可复用的“精读风格指南”（markdown），用于指导后续 LLM 生成更符合用户口味的精读内容。
3) 额外输出一段可直接拼接到 deep_read system prompt 的 addendum（更短、更可执行）。

强约束：
- 只能从样本中归纳总结，禁止凭空脑补具体事实；禁止复述/引用样本中的具体私密内容（例如具体项目名、账号、链接、token 等）。
- 输出必须是 JSON，且仅包含两个字段：
  - style_guide_markdown: string
  - deep_read_prompt_addendum: string
- 两个字段都使用中文；风格指南用条目化结构（小标题 + 要点）。
"""

    user_text = json.dumps({"samples": samples}, ensure_ascii=False, indent=2)

    try:
        resp = await llm_client.aside_client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_text},
            ],
            temperature=0.2,
        )
        content = resp.choices[0].message.content or ""
    except Exception:
        resp = await llm_client.aside_client.responses.create(
            model=model,
            instructions=system_prompt,
            input=user_text,
            temperature=0.2,
        )
        content = getattr(resp, "output_text", None) or ""

    parsed = llm_client._parse_json_response(content)
    style_guide = parsed.get("style_guide_markdown") or ""
    addendum = parsed.get("deep_read_prompt_addendum") or ""
    if not isinstance(style_guide, str):
        style_guide = str(style_guide)
    if not isinstance(addendum, str):
        addendum = str(addendum)
    return {
        "style_guide_markdown": style_guide.strip(),
        "deep_read_prompt_addendum": addendum.strip(),
    }


async def main():
    parser = argparse.ArgumentParser(description="从 Craft 精读笔记样本提炼精读偏好，并生成可复用的 prompt 风格指南。")
    parser.add_argument("--source", choices=["auto", "folder", "collection"], default="auto", help="样本来源（默认 auto）")
    parser.add_argument("--folder-id", default=None, help="Craft folderId（source=folder 时使用；默认读取 CRAFT_PAPERS_FOLDER_ID）")
    parser.add_argument("--title-prefix", default="", help="按标题前缀过滤（folder source 生效）；默认不过滤，若只取精读可传入：【精读】")
    parser.add_argument("--max-docs", type=int, default=10, help="最多抽取多少篇精读样本（默认 10）")
    parser.add_argument("--max-depth", type=int, default=3, help="读取 blocks 的 maxDepth（默认 3）")
    parser.add_argument("--max-chars", type=int, default=2000, help="每篇样本最多保留字符数（默认 2000）")
    parser.add_argument("--samples-out", default="./data/deep_read_thoughts_samples.json", help="抽取到的样本输出路径")
    parser.add_argument("--style-out", default="./data/deep_read_style_guide.md", help="生成的风格指南输出路径")
    parser.add_argument("--addendum-out", default="./data/deep_read_prompt_addendum.txt", help="生成的 prompt addendum 输出路径")
    parser.add_argument("--use-llm", action="store_true", help="是否调用 ASIDE_LLM 生成风格指南（否则只抽样本）")

    args = parser.parse_args()

    try:
        if not settings.craft_api_base_url:
            raise ValueError("CRAFT_API_BASE_URL is empty")

        source = args.source
        folder_id = args.folder_id or settings.craft_papers_folder_id

        doc_pairs: List[Tuple[str, str]]
        if source == "folder" or (source == "auto" and folder_id):
            if not folder_id:
                raise ValueError("No folder_id provided and CRAFT_PAPERS_FOLDER_ID is empty")
            logger.info(f"Sampling docs from folder: {folder_id} (max_docs={args.max_docs})")
            doc_pairs = await _pick_docs_from_folder(folder_id, args.title_prefix, args.max_docs)
        else:
            logger.info(f"Sampling docs from collection (max_docs={args.max_docs})")
            doc_pairs = await _pick_docs_from_collection(args.max_docs)

        if not doc_pairs:
            raise ValueError("No documents found for sampling (check folder/collection config and filters).")

        samples: List[Dict[str, str]] = []
        for doc_id, title in doc_pairs:
            tree = await craft_client.get_block_tree(doc_id, max_depth=args.max_depth)
            thoughts = extract_thoughts_section(tree)
            if not thoughts:
                continue
            samples.append(
                {
                    "doc_id": doc_id,
                    "title": title,
                    "thoughts": _truncate(thoughts, args.max_chars),
                }
            )

        if not samples:
            raise ValueError("Found documents, but none contains a '思考和感想' section with content.")

        _atomic_write_json(args.samples_out, {"samples": samples})
        logger.info(f"Wrote samples: {args.samples_out} (count={len(samples)})")

        if args.use_llm:
            model = llm_client.aside_model
            result = await build_style_guide(samples=samples, model=model)

            _atomic_write_text(args.style_out, result["style_guide_markdown"].rstrip() + "\n")
            _atomic_write_text(args.addendum_out, result["deep_read_prompt_addendum"].rstrip() + "\n")

            logger.info(f"Wrote style guide: {args.style_out}")
            logger.info(f"Wrote addendum: {args.addendum_out}")

            logger.info("Next: set DEEP_READ_STYLE_GUIDE_PATH to the style guide path in your .env, then restart the server.")

    finally:
        await craft_client.close()


if __name__ == "__main__":
    asyncio.run(main())
