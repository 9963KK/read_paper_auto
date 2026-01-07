"""
API 路由
"""
import json
import asyncio
import re
import time
from collections import defaultdict
from fastapi import APIRouter, HTTPException, BackgroundTasks, Request
from loguru import logger
from langgraph.errors import GraphInterrupt
from langgraph.types import Command

from src.api.schemas import (
    TriageRequest,
    ResumeRequest,
    DifyTriageResponse,
    DifyResumeResponse,
    PaperStatusResponse
)
from src.workflow.graph import workflow_app
from src.workflow.state import PaperState
from src.services.feishu_bot import feishu_bot
from src.services.paper_parser import PaperParser
from src.services.llm_client import llm_client
from src.services.craft_client import craft_client

router = APIRouter()

# 进程内互斥锁，防止同一 paper_id 被并发处理
# 注意：多 worker 部署时需要升级为 Redis 分布式锁
_paper_locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

# 进程内上下文：用于「感想」消息在不带链接时定位最近一篇论文
# key = "{sender_open_id}:{chat_id}"（chat_id 可能为空），value = paper_id
_chat_last_paper_id: dict[str, str] = {}
_recent_feishu_message_ids: dict[str, float] = {}
_RECENT_FEISHU_MESSAGE_TTL_SECONDS = 10 * 60

_THOUGHTS_CMD_RE = re.compile(
    r"^\s*(?:@_user_\d+\s*)*(?:/thoughts?\b|thoughts?\b|感想|心得|想法|思考)(?:[\s:：,，]|$)",
    re.IGNORECASE,
)


def _chat_context_key(sender_open_id: str | None, chat_id: str | None) -> str:
    sender = (sender_open_id or "").strip()
    chat = (chat_id or "").strip()
    if sender and chat:
        return f"{sender}:{chat}"
    return sender or chat


def _parse_thoughts_command(text: str) -> tuple[str | None, str]:
    """
    解析「感想」类消息：
    - 支持：感想/心得/想法/思考 或 /thought 前缀
    - 支持：消息内带 arXiv 链接（可选）
    """
    raw = (text or "").strip()
    raw = re.sub(r"^\s*(?:@_user_\d+\s*)+", "", raw).strip()
    raw = re.sub(r"^(?:/thoughts?\b|thoughts?\b|感想|心得|想法|思考)(?:[\s:：,，]*)", "", raw, flags=re.IGNORECASE).strip()

    url = feishu_bot.extract_url_from_message(raw) or feishu_bot.extract_url_from_message(text or "")
    if url:
        raw = raw.replace(url, "").strip()
    return url, raw


def _candidate_paper_ids_from_url(url: str) -> list[str]:
    raw = (url or "").strip()
    if not raw:
        return []

    candidates: list[str] = []
    try:
        arxiv_id = PaperParser.extract_arxiv_id(raw)
    except Exception:
        arxiv_id = None

    if arxiv_id:
        candidates.append(PaperParser.generate_paper_id(f"https://arxiv.org/abs/{arxiv_id}"))
    candidates.append(PaperParser.generate_paper_id(raw))

    deduped: list[str] = []
    seen: set[str] = set()
    for paper_id in candidates:
        if paper_id and paper_id not in seen:
            deduped.append(paper_id)
            seen.add(paper_id)
    return deduped


def _remember_feishu_message_once(message_id: str | None) -> bool:
    """
    记录 message_id（用于去重）。返回 True 表示已处理过/应跳过；False 表示首次看到。
    """
    if not message_id:
        return False

    now = time.time()
    # 清理过期
    if _recent_feishu_message_ids:
        expire_before = now - _RECENT_FEISHU_MESSAGE_TTL_SECONDS
        # 控制成本：只在字典变大时清理
        if len(_recent_feishu_message_ids) > 1024:
            for mid, ts in list(_recent_feishu_message_ids.items()):
                if ts < expire_before:
                    _recent_feishu_message_ids.pop(mid, None)

    ts = _recent_feishu_message_ids.get(message_id)
    if ts is not None and (now - ts) < _RECENT_FEISHU_MESSAGE_TTL_SECONDS:
        return True

    _recent_feishu_message_ids[message_id] = now
    return False


def _extract_text_from_feishu_message_item(item: dict) -> str:
    if not isinstance(item, dict):
        return ""

    msg_type = item.get("msg_type") or item.get("message_type") or item.get("type")
    if msg_type and str(msg_type) != "text":
        return ""

    body = item.get("body") or {}
    if not isinstance(body, dict):
        return ""

    content = body.get("content")
    if not isinstance(content, str) or not content.strip():
        return ""

    try:
        parsed = json.loads(content)
    except Exception:
        return ""

    if isinstance(parsed, dict):
        text = parsed.get("text")
        return str(text) if text is not None else ""

    return ""


async def _process_thoughts_message(
    *,
    sender_id: str | None,
    chat_id: str | None,
    receive_id: str,
    receive_id_type: str,
    text: str,
) -> None:
    """
    处理「感想」类消息：写入 Craft 并回消息。
    """
    ctx_key = _chat_context_key(sender_id, chat_id)
    url_in_msg, thoughts = _parse_thoughts_command(text)
    if not thoughts:
        try:
            await feishu_bot.send_text_message(
                receive_id,
                "请发送你的感想内容。\n示例：\n- 感想 这里写你的感想\n- 感想 https://arxiv.org/abs/xxxx.xxxxx 这里写你的感想",
                receive_id_type=receive_id_type,
            )
        except Exception:
            logger.exception("Failed to send feishu empty-thoughts hint message")
        return

    candidate_paper_ids: list[str] = []
    if url_in_msg:
        candidate_paper_ids = _candidate_paper_ids_from_url(url_in_msg)
    elif ctx_key:
        last_paper_id = _chat_last_paper_id.get(ctx_key)
        if last_paper_id:
            candidate_paper_ids = [last_paper_id]

    history_error: str | None = None
    if not candidate_paper_ids:
        # 尝试从群聊最近消息中回溯（依赖飞书权限：im:message.group_msg）
        if chat_id:
            try:
                items = await feishu_bot.list_chat_messages(chat_id, page_size=20)
                for item in items:
                    msg_text = _extract_text_from_feishu_message_item(item)
                    if not msg_text:
                        continue
                    found_url = feishu_bot.extract_url_from_message(msg_text)
                    if not found_url:
                        continue
                    for paper_id in _candidate_paper_ids_from_url(found_url):
                        config = {"configurable": {"thread_id": paper_id}}
                        state = await workflow_app.aget_state(config)
                        if state and state.values:
                            candidate_paper_ids = [paper_id]
                            break
                    if candidate_paper_ids:
                        break
            except Exception as e:
                history_error = str(e)
                logger.warning(f"Feishu history lookup failed: chat_id={chat_id} err={history_error}")

    if not candidate_paper_ids:
        extra_hint = ""
        if history_error and "im:message.group_msg" in history_error:
            extra_hint = "\n（提示：需要在飞书开放平台为应用开通权限 im:message.group_msg，并重新发布/管理员授权）"
        try:
            await feishu_bot.send_text_message(
                receive_id,
                "未找到对应论文上下文，请在感想消息里带上论文链接（arXiv 的 abs/pdf 均可）。\n示例：感想 https://arxiv.org/abs/xxxx.xxxxx 这里写你的感想"
                + extra_hint,
                receive_id_type=receive_id_type,
            )
        except Exception:
            logger.exception("Failed to send feishu missing-context message")
        return

    target_paper_id: str | None = None
    target_values: dict | None = None
    for paper_id in candidate_paper_ids:
        config = {"configurable": {"thread_id": paper_id}}
        state = await workflow_app.aget_state(config)
        if state and state.values:
            target_paper_id = paper_id
            target_values = state.values
            break

    if not target_paper_id or not target_values:
        try:
            await feishu_bot.send_text_message(
                receive_id,
                "未找到论文处理记录，请先发送论文链接触发处理。",
                receive_id_type=receive_id_type,
            )
        except Exception:
            logger.exception("Failed to send feishu missing-state message")
        return

    reading_doc_id = target_values.get("craft_reading_doc_id")
    if not reading_doc_id:
        try:
            await feishu_bot.send_text_message(
                receive_id,
                "该论文还没有精读文档（请先在卡片中选择「精读」并等待完成）。\n如需指定论文，请在消息中带上论文链接。",
                receive_id_type=receive_id_type,
            )
        except Exception:
            logger.exception("Failed to send feishu missing-reading-doc message")
        return

    try:
        await craft_client.write_thoughts_to_reading_document(reading_doc_id, thoughts)
    except Exception as e:
        logger.exception(
            f"Failed to write thoughts to Craft: paper_id={target_paper_id} doc_id={reading_doc_id} err={e}"
        )
        try:
            await feishu_bot.send_text_message(
                receive_id,
                "写入 Craft 失败，请稍后重试。",
                receive_id_type=receive_id_type,
            )
        except Exception:
            logger.exception("Failed to send feishu craft-write failure message")
        return

    if ctx_key:
        _chat_last_paper_id[ctx_key] = target_paper_id

    try:
        await feishu_bot.send_text_message(
            receive_id,
            f"已写入精读文档的「思考和感想」部分。\n精读文档: craft://x-callback-url/open?blockId={reading_doc_id}",
            receive_id_type=receive_id_type,
        )
    except Exception:
        logger.exception("Failed to send feishu thoughts-written message")

    return


def _is_thoughts_message(text: str) -> bool:
    return bool(_THOUGHTS_CMD_RE.match(text or ""))


def _extract_feishu_message_id(event_data: dict) -> str | None:
    message = event_data.get("message") if isinstance(event_data, dict) else None
    if not isinstance(message, dict):
        return None
    value = message.get("message_id") or message.get("messageId") or message.get("id")
    if value is None:
        return None
    return str(value)


def _coerce_enum_value(value: object) -> object:
    if value is None:
        return None
    return getattr(value, "value", value)


def _parse_feishu_action_value(raw_value: object) -> dict:
    """
    解析飞书卡片 action.value（兼容：dict / json-string / double-encoded json-string）
    """
    if raw_value is None:
        return {}
    if isinstance(raw_value, dict):
        return raw_value
    if not isinstance(raw_value, str):
        return {}

    value = raw_value.strip()
    if not value:
        return {}

    # 兼容 value 被重复 JSON 编码的情况：第一次 loads 得到 str，再次 loads 得到 dict
    for _ in range(2):
        try:
            parsed = json.loads(value)
        except Exception:
            return {}
        if isinstance(parsed, dict):
            return parsed
        if isinstance(parsed, str):
            value = parsed.strip()
            continue
        return {}
    return {}


def _build_dify_triage_response(values: dict, paper_id: str) -> DifyTriageResponse:
    return DifyTriageResponse(
        paper_id=values.get("paper_id", paper_id),
        status=values.get("status", "unknown"),
        source_url=values.get("source_url"),
        title=values.get("title"),
        abstract=values.get("abstract"),
        pdf_url=values.get("pdf_url"),
        triage_summary=values.get("triage_summary"),
        triage_contributions=values.get("triage_contributions"),
        triage_limitations=values.get("triage_limitations"),
        triage_relevance=values.get("triage_relevance"),
        triage_suggested_action=_coerce_enum_value(values.get("triage_suggested_action")),
        triage_suggested_tags=values.get("triage_suggested_tags"),
        craft_collection_item_id=values.get("craft_collection_item_id"),
        craft_reading_doc_id=values.get("craft_reading_doc_id"),
        error_message=values.get("error_message"),
    )


def _build_dify_resume_response(values: dict, paper_id: str) -> DifyResumeResponse:
    return DifyResumeResponse(
        paper_id=values.get("paper_id", paper_id),
        status=values.get("status", "unknown"),
        title=values.get("title"),
        human_decision=_coerce_enum_value(values.get("human_decision")),
        craft_collection_item_id=values.get("craft_collection_item_id"),
        craft_reading_doc_id=values.get("craft_reading_doc_id"),
        error_message=values.get("error_message"),
    )


@router.post("/triage")
async def triage_paper(request: TriageRequest, background_tasks: BackgroundTasks):
    """
    手动触发 Triage

    Args:
        request: Triage 请求

    Returns:
        论文 ID 和状态
    """
    logger.info(f"Manual triage request: {request.source_url}")

    try:
        paper_id = PaperParser.generate_paper_id(request.source_url)
        config = {"configurable": {"thread_id": paper_id}}

        # 检查现有状态，防止重复处理
        state = await workflow_app.aget_state(config)
        if state and state.values:
            current_status = state.values.get("status")
            # 如果已在处理中或已完成，直接返回
            if current_status in ["ingesting", "extracting", "triaging", "waiting_decision", "deep_reading", "completed"]:
                logger.info(f"Paper {paper_id} already in status: {current_status}")
                return {
                    "message": "Workflow already running or completed",
                    "paper_id": paper_id,
                    "source_url": request.source_url,
                    "status": current_status
                }

        # 获取锁，防止并发启动
        async with _paper_locks[paper_id]:
            # 双重检查（锁内再检查一次）
            state = await workflow_app.aget_state(config)
            if state and state.values:
                current_status = state.values.get("status")
                if current_status not in [None, "failed"]:
                    raise HTTPException(status_code=409, detail=f"Paper already processing with status: {current_status}")

            # 创建初始状态
            initial_state: PaperState = {
                "paper_id": paper_id,
                "source_url": request.source_url,
                "source_type": request.source_type,
                "status": "ingesting"
            }

            # 异步执行工作流（直到 interrupt）
            async def run_workflow():
                try:
                    async for event in workflow_app.astream(initial_state, config):
                        logger.info(f"Workflow event: {event}")
                except GraphInterrupt:
                    logger.info(f"Workflow interrupted (waiting decision): {paper_id}")
                except Exception as e:
                    logger.exception(f"Workflow execution failed for {paper_id}: {e}")

            background_tasks.add_task(run_workflow)

            return {
                "message": "Workflow started",
                "paper_id": paper_id,
                "source_url": request.source_url
            }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Triage failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/dify/triage", response_model=DifyTriageResponse)
async def dify_triage_paper(request: TriageRequest):
    """
    Dify 工具接口：同步执行工作流到 interrupt（waiting_decision），返回 triage + 归档信息。
    """
    logger.info(f"Dify triage request: {request.source_url}")

    paper_id = PaperParser.generate_paper_id(request.source_url)
    config = {"configurable": {"thread_id": paper_id}}

    async with _paper_locks[paper_id]:
        state = await workflow_app.aget_state(config)
        if state and state.values:
            current_status = state.values.get("status")
            if current_status in ["waiting_decision", "completed", "failed"]:
                return _build_dify_triage_response(state.values, paper_id)
            if current_status in ["ingesting", "extracting", "triaging", "deep_reading"]:
                raise HTTPException(status_code=409, detail=f"Paper already processing with status: {current_status}")

        initial_state: PaperState = {
            "paper_id": paper_id,
            "source_url": request.source_url,
            "source_type": request.source_type,
            "status": "ingesting",
        }

        async def _run_until_interrupt():
            async for _event in workflow_app.astream(initial_state, config):
                pass

        try:
            await asyncio.wait_for(_run_until_interrupt(), timeout=300)
        except GraphInterrupt:
            pass
        except asyncio.TimeoutError:
            raise HTTPException(status_code=504, detail="Workflow timeout while waiting for decision point")

        state = await workflow_app.aget_state(config)
        if not state or not state.values:
            raise HTTPException(status_code=500, detail="Failed to read workflow state")

        return _build_dify_triage_response(state.values, paper_id)


@router.post("/resume")
async def resume_workflow(request: ResumeRequest, background_tasks: BackgroundTasks):
    """
    手动恢复工作流

    Args:
        request: Resume 请求

    Returns:
        处理结果
    """
    logger.info(f"Manual resume request: {request.paper_id}")

    try:
        config = {"configurable": {"thread_id": request.paper_id}}

        # 检查状态：必须在 waiting_decision 才能 resume
        state = await workflow_app.aget_state(config)
        if not state or not state.values:
            raise HTTPException(status_code=404, detail="Paper not found")

        current_status = state.values.get("status")
        if current_status != "waiting_decision":
            raise HTTPException(
                status_code=400,
                detail=f"Cannot resume from status: {current_status}. Expected: waiting_decision"
            )

        # 获取锁，防止重复 resume
        async with _paper_locks[request.paper_id]:
            # 双重检查
            state = await workflow_app.aget_state(config)
            if state.values.get("status") != "waiting_decision":
                raise HTTPException(status_code=409, detail="Paper already resumed or status changed")

            # 构建人工决策输入
            human_input = {
                "decision": request.decision,
                "tags": request.tags or [],
                "comment": request.comment or ""
            }

            # 异步恢复工作流
            async def run_workflow():
                try:
                    async for event in workflow_app.astream(Command(resume=human_input), config):
                        logger.info(f"Workflow event: {event}")
                except GraphInterrupt:
                    logger.info(f"Workflow interrupted unexpectedly during resume: {request.paper_id}")
                except Exception as e:
                    logger.exception(f"Workflow resume failed for {request.paper_id}: {e}")

            background_tasks.add_task(run_workflow)

            return {
                "message": "Workflow resumed",
                "paper_id": request.paper_id,
                "decision": request.decision
            }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Resume failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/dify/resume", response_model=DifyResumeResponse)
async def dify_resume_workflow(request: ResumeRequest):
    """
    Dify 工具接口：同步 resume 工作流并返回最终状态（completed/failed）。
    """
    logger.info(f"Dify resume request: {request.paper_id} decision={request.decision}")

    config = {"configurable": {"thread_id": request.paper_id}}

    async with _paper_locks[request.paper_id]:
        state = await workflow_app.aget_state(config)
        if not state or not state.values:
            raise HTTPException(status_code=404, detail="Paper not found")

        current_status = state.values.get("status")
        if current_status == "completed":
            return _build_dify_resume_response(state.values, request.paper_id)
        if current_status != "waiting_decision":
            raise HTTPException(
                status_code=400,
                detail=f"Cannot resume from status: {current_status}. Expected: waiting_decision",
            )

        human_input = {
            "decision": request.decision,
            "tags": request.tags or [],
            "comment": request.comment or "",
        }

        async def _run_to_end():
            async for _event in workflow_app.astream(Command(resume=human_input), config):
                pass

        try:
            await asyncio.wait_for(_run_to_end(), timeout=600)
        except asyncio.TimeoutError:
            raise HTTPException(status_code=504, detail="Workflow timeout while resuming")

        state = await workflow_app.aget_state(config)
        if not state or not state.values:
            raise HTTPException(status_code=500, detail="Failed to read workflow state")

        return _build_dify_resume_response(state.values, request.paper_id)


@router.get("/paper/{paper_id}", response_model=PaperStatusResponse)
async def get_paper_status(paper_id: str):
    """
    查询论文处理状态

    Args:
        paper_id: 论文 ID

    Returns:
        论文状态
    """
    logger.info(f"Status query: {paper_id}")

    try:
        # 配置
        config = {"configurable": {"thread_id": paper_id}}

        # 获取状态
        state = await workflow_app.aget_state(config)

        if not state or not state.values:
            raise HTTPException(status_code=404, detail="Paper not found")

        values = state.values

        return PaperStatusResponse(
            paper_id=values.get("paper_id", paper_id),
            status=values.get("status", "unknown"),
            title=values.get("title"),
            source_url=values.get("source_url"),
            triage_summary=values.get("triage_summary"),
            human_decision=getattr(values.get("human_decision"), "value", values.get("human_decision")),
            craft_item_id=values.get("craft_collection_item_id"),
            craft_reading_doc_id=values.get("craft_reading_doc_id"),
            error_message=values.get("error_message")
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Status query failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/feishu/message")
@router.post("/feishu/message/")
async def feishu_message_handler(request: Request, background_tasks: BackgroundTasks):
    """
    飞书消息事件处理

    Args:
        request: 原始请求

    Returns:
        响应
    """
    payload = await _read_json_body(request)
    payload_keys = list(payload.keys()) if isinstance(payload, dict) else []
    logger.info(f"Feishu callback received: path={request.url.path} keys={payload_keys}")

    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Invalid payload")

    # URL 验证挑战
    challenge = payload.get("challenge")
    if challenge:
        logger.info(f"Feishu url_verification ok: challenge_len={len(challenge)}")
        return {"challenge": challenge}
    if payload.get("type") == "url_verification":
        logger.warning(f"Feishu url_verification missing challenge: keys={payload_keys}")
        raise HTTPException(status_code=400, detail="Missing challenge")

    # 验证请求
    token = _extract_feishu_token(payload)
    if not feishu_bot.verify_request(token):
        raise HTTPException(status_code=403, detail="Invalid token")

    # 处理消息事件
    event_data = payload.get("event") or {}
    # 兼容 schema 2.0（没有 type 字段）
    if (payload.get("type") == "event_callback" or payload.get("schema")) and event_data:

        # 只处理文本消息
        if event_data.get("message", {}).get("message_type") == "text":
            sender_id = (
                event_data.get("sender", {}).get("sender_id", {}).get("open_id")
                or event_data.get("sender", {}).get("open_id")
            )
            chat_id = event_data.get("message", {}).get("chat_id")
            receive_id = chat_id or sender_id
            receive_id_type = "chat_id" if chat_id else "open_id"
            message_content = json.loads(event_data.get("message", {}).get("content", "{}"))
            text = message_content.get("text", "")

            message_id = _extract_feishu_message_id(event_data)
            logger.info(f"Received message: sender={sender_id} chat_id={chat_id} message_id={message_id} text={text}")

            if _remember_feishu_message_once(message_id):
                logger.info(f"Skip duplicate message: message_id={message_id}")
                return {"message": "ok"}

            if _is_thoughts_message(text):
                # 感想写入可能超过飞书 3s 超时：放入后台任务，避免回调重试导致重复写入
                background_tasks.add_task(
                    _process_thoughts_message,
                    sender_id=sender_id,
                    chat_id=chat_id,
                    receive_id=receive_id,
                    receive_id_type=receive_id_type,
                    text=text,
                )
                return {"message": "ok"}

            ctx_key = _chat_context_key(sender_id, chat_id)

            # 提取论文 URL
            url = feishu_bot.extract_url_from_message(text)
            if not url:
                url = await llm_client.extract_paper_url(text)

            if url:
                if "arxiv.org" not in url:
                    try:
                        await feishu_bot.send_text_message(
                            receive_id,
                            f"已识别到论文链接：{url}\n\n但当前版本仅支持 arXiv 链接（例如 https://arxiv.org/abs/xxxx.xxxxx）。",
                            receive_id_type=receive_id_type,
                        )
                    except Exception:
                        logger.exception("Failed to send feishu unsupported-link message")
                    return {"message": "ok"}

                paper_id = PaperParser.generate_paper_id(url)
                if ctx_key:
                    _chat_last_paper_id[ctx_key] = paper_id
                config = {"configurable": {"thread_id": paper_id}}

                # 检查是否已在处理
                state = await workflow_app.aget_state(config)
                if state and state.values:
                    current_status = state.values.get("status")
                    if current_status in ["ingesting", "extracting", "triaging", "waiting_decision", "deep_reading", "completed"]:
                        try:
                            await feishu_bot.send_text_message(
                                receive_id,
                                f"该论文已在处理中或已完成（状态: {current_status}）",
                                receive_id_type=receive_id_type,
                            )
                        except Exception:
                            logger.exception("Failed to send feishu duplicate-status message")
                        return {"message": "ok"}

                # 发送处理中消息
                try:
                    await feishu_bot.send_text_message(
                        receive_id,
                        "正在处理论文，请稍候...",
                        receive_id_type=receive_id_type,
                    )
                except Exception:
                    logger.exception("Failed to send feishu processing message")

                # 获取锁
                async with _paper_locks[paper_id]:
                    # 双重检查
                    state = await workflow_app.aget_state(config)
                    if state and state.values and state.values.get("status") not in [None, "failed"]:
                        return {"message": "ok"}

                    # 创建初始状态
                    initial_state: PaperState = {
                        "paper_id": paper_id,
                        "source_url": url,
                        "source_type": "arxiv",
                        "status": "ingesting"
                    }

                    # 异步执行工作流
                    async def run_workflow():
                        try:
                            async for event in workflow_app.astream(initial_state, config):
                                logger.info(f"Workflow event: {event}")
                        except GraphInterrupt:
                            logger.info(f"Workflow interrupted (waiting decision): {paper_id}")
                        except Exception as e:
                            logger.error(f"Workflow failed: {e}")
                            try:
                                await feishu_bot.send_text_message(
                                    receive_id,
                                    f"处理失败：{str(e)}",
                                    receive_id_type=receive_id_type,
                                )
                            except Exception:
                                logger.exception("Failed to send feishu workflow failure message")
                            return

                        # 工作流到达 interrupt 点（或正常结束），查询状态并发送决策卡片
                        state = await workflow_app.aget_state(config)
                        if not state or not state.values:
                            try:
                                await feishu_bot.send_text_message(
                                    receive_id,
                                    "处理失败：无法读取论文状态",
                                    receive_id_type=receive_id_type,
                                )
                            except Exception:
                                logger.exception("Failed to send feishu state-read failure message")
                            return

                        values = state.values
                        if values.get("status") == "waiting_decision":
                            try:
                                await feishu_bot.send_decision_card(
                                    receive_id=receive_id,
                                    paper_id=values["paper_id"],
                                    title=values["title"],
                                    summary=values.get("triage_summary", ""),
                                    contributions=values.get("triage_contributions", ""),
                                    relevance=values.get("triage_relevance", 3),
                                    suggested_action=getattr(
                                        values.get("triage_suggested_action"),
                                        "value",
                                        values.get("triage_suggested_action", "skim"),
                                    ),
                                    suggested_tags=values.get("triage_suggested_tags", []),
                                    receive_id_type=receive_id_type,
                                )
                            except Exception:
                                logger.exception("Failed to send feishu decision card")

                    background_tasks.add_task(run_workflow)

            else:
                try:
                    await feishu_bot.send_text_message(
                        receive_id,
                        "未找到论文链接，请发送 arXiv 链接",
                        receive_id_type=receive_id_type,
                    )
                except Exception:
                    logger.exception("Failed to send feishu no-link message")

    return {"message": "ok"}


@router.post("/feishu/callback")
@router.post("/feishu/callback/")
async def feishu_callback_handler(request: Request, background_tasks: BackgroundTasks):
    """
    飞书统一回调入口（兼容：消息事件 + 卡片动作）

    说明：飞书控制台通常只支持配置一个“事件订阅请求地址”，因此提供单一入口做分发。
    """
    payload = await _read_json_body(request)
    payload_keys = list(payload.keys()) if isinstance(payload, dict) else []
    logger.info(f"Feishu unified callback received: path={request.url.path} keys={payload_keys}")

    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Invalid payload")

    # URL 验证挑战
    challenge = payload.get("challenge")
    if challenge:
        logger.info(f"Feishu url_verification ok: challenge_len={len(challenge)}")
        return {"challenge": challenge}
    if payload.get("type") == "url_verification":
        logger.warning(f"Feishu url_verification missing challenge: keys={payload_keys}")
        raise HTTPException(status_code=400, detail="Missing challenge")

    # 验证请求
    token = _extract_feishu_token(payload)
    if not feishu_bot.verify_request(token):
        raise HTTPException(status_code=403, detail="Invalid token")

    event_data = payload.get("event") or {}
    # 兼容 schema 2.0（可能没有 type=event_callback）
    if not isinstance(event_data, dict) or not event_data:
        return {"message": "ok"}

    # 卡片动作：event.action 存在
    if isinstance(event_data.get("action"), dict):
        user_id = event_data.get("operator", {}).get("open_id")
        chat_id = (
            event_data.get("open_chat_id")
            or (event_data.get("context") or {}).get("open_chat_id")
            or (event_data.get("message") or {}).get("chat_id")
        )
        receive_id = chat_id or user_id
        receive_id_type = "chat_id" if chat_id else "open_id"
        raw_value = event_data.get("action", {}).get("value")
        action_value = _parse_feishu_action_value(raw_value)
        if not action_value:
            logger.warning(
                f"Feishu card action value parse failed: receive_id_type={receive_id_type} receive_id={receive_id} raw_type={type(raw_value).__name__}"
            )
            return {"message": "ok"}

        paper_id = action_value.get("paper_id")
        decision = action_value.get("decision")

        logger.info(f"Card action: receive_id_type={receive_id_type} receive_id={receive_id} paper_id={paper_id} decision={decision}")

        if paper_id and decision and receive_id:
            # Backlog 已移除：为兼容旧卡片点击，将其按速读处理
            if decision == "backlog":
                decision = "skim"

            ctx_key = _chat_context_key(user_id, chat_id)
            if ctx_key:
                _chat_last_paper_id[ctx_key] = paper_id

            config = {"configurable": {"thread_id": paper_id}}

            state = await workflow_app.aget_state(config)
            if not state or not state.values:
                try:
                    await feishu_bot.send_text_message(receive_id, "论文状态未找到", receive_id_type=receive_id_type)
                except Exception:
                    logger.exception("Failed to send feishu not-found message")
                return {"message": "ok"}

            current_status = state.values.get("status")
            if current_status != "waiting_decision":
                try:
                    error_hint = ""
                    if current_status == "failed":
                        error_message = state.values.get("error_message") or "未提供错误信息"
                        error_hint = f"\n失败原因：{error_message}\n请重新发送论文链接以重新开始。"
                    await feishu_bot.send_text_message(
                        receive_id,
                        f"无法从当前状态恢复: {current_status}{error_hint}",
                        receive_id_type=receive_id_type,
                    )
                except Exception:
                    logger.exception("Failed to send feishu invalid-status message")
                return {"message": "ok"}

            async with _paper_locks[paper_id]:
                state = await workflow_app.aget_state(config)
                if state.values.get("status") != "waiting_decision":
                    return {"message": "ok"}

                human_input = {"decision": decision, "tags": [], "comment": ""}
                paper_title = state.values.get("title") or "<unknown>"
                decision_label = {
                    "deep_read": "精读",
                    "skim": "速读",
                    "drop": "Drop",
                }.get(decision, str(decision))
                ack_text = (
                    f"已收到选择：{decision_label}\n"
                    f"论文：{paper_title}\n"
                    "正在处理，请稍候..."
                )
                if decision == "deep_read":
                    ack_text = (
                        f"已收到选择：精读\n"
                        f"论文：{paper_title}\n"
                        "开始生成精读笔记并更新 Craft，完成后会通知你。"
                    )

                async def run_workflow():
                    try:
                        try:
                            await feishu_bot.send_text_message(
                                receive_id,
                                ack_text,
                                receive_id_type=receive_id_type,
                            )
                        except Exception:
                            logger.exception("Failed to send feishu decision ack message")

                        result = None
                        async for event in workflow_app.astream(Command(resume=human_input), config):
                            logger.info(f"Workflow event: {event}")
                            result = event

                        if not result:
                            return

                        state = await workflow_app.aget_state(config)
                        if not state or not state.values:
                            await feishu_bot.send_text_message(
                                receive_id,
                                "处理失败：无法读取论文状态",
                                receive_id_type=receive_id_type,
                            )
                            return

                        values = state.values
                        status = values.get("status")
                        if status == "completed":
                            await feishu_bot.send_completion_message(
                                receive_id=receive_id,
                                title=values.get("title", "<unknown>"),
                                decision=decision,
                                craft_item_id=values.get("craft_collection_item_id"),
                                craft_reading_doc_id=values.get("craft_reading_doc_id"),
                                receive_id_type=receive_id_type,
                            )
                            return

                        if status == "failed":
                            error_message = values.get("error_message") or "未提供错误信息"
                            craft_item_id = values.get("craft_collection_item_id")
                            craft_reading_doc_id = values.get("craft_reading_doc_id")
                            extra_links = ""
                            if craft_item_id:
                                extra_links += f"\nCraft 归档: craft://x-callback-url/open?blockId={craft_item_id}"
                            if craft_reading_doc_id:
                                extra_links += f"\n精读文档: craft://x-callback-url/open?blockId={craft_reading_doc_id}"
                            await feishu_bot.send_text_message(
                                receive_id,
                                f"处理失败：{error_message}{extra_links}",
                                receive_id_type=receive_id_type,
                            )
                            return
                    except Exception as e:
                        logger.exception(f"Workflow resume failed for {paper_id}: {e}")
                        try:
                            await feishu_bot.send_text_message(
                                receive_id,
                                f"处理失败：{str(e)}",
                                receive_id_type=receive_id_type,
                            )
                        except Exception:
                            logger.exception("Failed to send feishu resume failure message")

                background_tasks.add_task(run_workflow)

        return {"message": "ok"}

    # 文本消息事件：event.message.message_type == text
    if event_data.get("message", {}).get("message_type") == "text":
        sender_id = (
            event_data.get("sender", {}).get("sender_id", {}).get("open_id")
            or event_data.get("sender", {}).get("open_id")
        )
        chat_id = event_data.get("message", {}).get("chat_id")
        receive_id = chat_id or sender_id
        receive_id_type = "chat_id" if chat_id else "open_id"
        message_content = json.loads(event_data.get("message", {}).get("content", "{}"))
        text = message_content.get("text", "")

        message_id = _extract_feishu_message_id(event_data)
        logger.info(f"Received message: sender={sender_id} chat_id={chat_id} message_id={message_id} text={text}")

        if _remember_feishu_message_once(message_id):
            logger.info(f"Skip duplicate message: message_id={message_id}")
            return {"message": "ok"}

        if _is_thoughts_message(text):
            # 感想写入可能超过飞书 3s 超时：放入后台任务，避免回调重试导致重复写入
            background_tasks.add_task(
                _process_thoughts_message,
                sender_id=sender_id,
                chat_id=chat_id,
                receive_id=receive_id,
                receive_id_type=receive_id_type,
                text=text,
            )
            return {"message": "ok"}

        ctx_key = _chat_context_key(sender_id, chat_id)

        url = feishu_bot.extract_url_from_message(text)
        if not url:
            url = await llm_client.extract_paper_url(text)

        if not url:
            try:
                await feishu_bot.send_text_message(
                    receive_id,
                    "未找到论文链接，请发送论文链接（arXiv/DOI/PDF 等）",
                    receive_id_type=receive_id_type,
                )
            except Exception:
                logger.exception("Failed to send feishu no-link message")
            return {"message": "ok"}

        if "arxiv.org" not in url:
            try:
                await feishu_bot.send_text_message(
                    receive_id,
                    f"已识别到论文链接：{url}\n\n但当前版本仅支持 arXiv 链接（例如 https://arxiv.org/abs/xxxx.xxxxx）。",
                    receive_id_type=receive_id_type,
                )
            except Exception:
                logger.exception("Failed to send feishu unsupported-link message")
            return {"message": "ok"}

        paper_id = PaperParser.generate_paper_id(url)
        if ctx_key:
            _chat_last_paper_id[ctx_key] = paper_id
        config = {"configurable": {"thread_id": paper_id}}

        state = await workflow_app.aget_state(config)
        if state and state.values:
            current_status = state.values.get("status")
            if current_status == "waiting_decision":
                values = state.values
                try:
                    await feishu_bot.send_text_message(
                        receive_id,
                        "该论文已处理到决策点，请在卡片中选择下一步。",
                        receive_id_type=receive_id_type,
                    )
                except Exception:
                    logger.exception("Failed to send feishu waiting_decision hint message")

                try:
                    await feishu_bot.send_decision_card(
                        receive_id=receive_id,
                        paper_id=values.get("paper_id", paper_id),
                        title=values.get("title", "<unknown>"),
                        summary=values.get("triage_summary", "") or "",
                        contributions=values.get("triage_contributions", "") or "",
                        relevance=values.get("triage_relevance", 3) or 3,
                        suggested_action=getattr(
                            values.get("triage_suggested_action"),
                            "value",
                            values.get("triage_suggested_action", "skim"),
                        ),
                        suggested_tags=values.get("triage_suggested_tags", []) or [],
                        receive_id_type=receive_id_type,
                    )
                except Exception:
                    logger.exception("Failed to resend feishu decision card")

                return {"message": "ok"}

            if current_status == "completed":
                values = state.values
                try:
                    await feishu_bot.send_completion_message(
                        receive_id=receive_id,
                        title=values.get("title", "<unknown>"),
                        decision=getattr(values.get("human_decision"), "value", values.get("human_decision", "completed")),
                        craft_item_id=values.get("craft_collection_item_id"),
                        craft_reading_doc_id=values.get("craft_reading_doc_id"),
                        receive_id_type=receive_id_type,
                    )
                except Exception:
                    logger.exception("Failed to send feishu completion message")
                return {"message": "ok"}

            if current_status in ["ingesting", "extracting", "triaging", "deep_reading"]:
                try:
                    await feishu_bot.send_text_message(
                        receive_id,
                        f"该论文已在处理中（状态: {current_status}）",
                        receive_id_type=receive_id_type,
                    )
                except Exception:
                    logger.exception("Failed to send feishu duplicate-status message")
                return {"message": "ok"}

        try:
            await feishu_bot.send_text_message(
                receive_id,
                f"链接有效：{url}\n正在处理论文，请稍候...",
                receive_id_type=receive_id_type,
            )
        except Exception:
            logger.exception("Failed to send feishu processing message")

        async with _paper_locks[paper_id]:
            state = await workflow_app.aget_state(config)
            if state and state.values and state.values.get("status") not in [None, "failed"]:
                return {"message": "ok"}

            initial_state: PaperState = {
                "paper_id": paper_id,
                "source_url": url,
                "source_type": "arxiv",
                "status": "ingesting",
            }

            async def run_workflow():
                try:
                    async for event in workflow_app.astream(initial_state, config):
                        logger.info(f"Workflow event: {event}")
                except GraphInterrupt:
                    logger.info(f"Workflow interrupted (waiting decision): {paper_id}")
                except Exception as e:
                    logger.error(f"Workflow failed: {e}")
                    try:
                        await feishu_bot.send_text_message(
                            receive_id,
                            f"处理失败：{str(e)}",
                            receive_id_type=receive_id_type,
                        )
                    except Exception:
                        logger.exception("Failed to send feishu workflow failure message")
                    return

                state = await workflow_app.aget_state(config)
                if not state or not state.values:
                    try:
                        await feishu_bot.send_text_message(
                            receive_id,
                            "处理失败：无法读取论文状态",
                            receive_id_type=receive_id_type,
                        )
                    except Exception:
                        logger.exception("Failed to send feishu state-read failure message")
                    return

                values = state.values
                if values.get("status") == "failed":
                    try:
                        craft_item_id = values.get("craft_collection_item_id")
                        craft_reading_doc_id = values.get("craft_reading_doc_id")
                        extra_links = ""
                        if craft_item_id:
                            extra_links += f"\nCraft 归档: craft://x-callback-url/open?blockId={craft_item_id}"
                        if craft_reading_doc_id:
                            extra_links += f"\n精读文档: craft://x-callback-url/open?blockId={craft_reading_doc_id}"
                        await feishu_bot.send_text_message(
                            receive_id,
                            f"处理失败：{values.get('error_message') or '未提供错误信息'}{extra_links}",
                            receive_id_type=receive_id_type,
                        )
                    except Exception:
                        logger.exception("Failed to send feishu failed-status message")
                    return

                if values.get("status") == "waiting_decision":
                    try:
                        await feishu_bot.send_decision_card(
                            receive_id=receive_id,
                            paper_id=values["paper_id"],
                            title=values["title"],
                            summary=values.get("triage_summary", ""),
                            contributions=values.get("triage_contributions", ""),
                            relevance=values.get("triage_relevance", 3),
                            suggested_action=getattr(
                                values.get("triage_suggested_action"),
                                "value",
                                values.get("triage_suggested_action", "skim"),
                            ),
                            suggested_tags=values.get("triage_suggested_tags", []),
                            receive_id_type=receive_id_type,
                        )
                    except Exception:
                        logger.exception("Failed to send feishu decision card")

            background_tasks.add_task(run_workflow)

        return {"message": "ok"}

    return {"message": "ok"}


@router.post("/feishu/action")
@router.post("/feishu/action/")
async def feishu_action_handler(request: Request, background_tasks: BackgroundTasks):
    """
    飞书卡片动作处理

    Args:
        request: 原始请求

    Returns:
        响应
    """
    payload = await _read_json_body(request)
    payload_keys = list(payload.keys()) if isinstance(payload, dict) else []
    logger.info(f"Feishu card callback received: path={request.url.path} keys={payload_keys}")

    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Invalid payload")

    # 验证请求
    token = _extract_feishu_token(payload)
    if not feishu_bot.verify_request(token):
        raise HTTPException(status_code=403, detail="Invalid token")

    # 处理卡片动作
    event_data = payload.get("event") or {}
    if (payload.get("type") == "event_callback" or payload.get("schema")) and event_data:
        user_id = event_data.get("operator", {}).get("open_id")
        chat_id = (
            event_data.get("open_chat_id")
            or (event_data.get("context") or {}).get("open_chat_id")
            or (event_data.get("message") or {}).get("chat_id")
        )
        receive_id = chat_id or user_id
        receive_id_type = "chat_id" if chat_id else "open_id"
        raw_value = event_data.get("action", {}).get("value")
        action_value = _parse_feishu_action_value(raw_value)
        if not action_value:
            logger.warning(
                f"Feishu card action value parse failed: receive_id_type={receive_id_type} receive_id={receive_id} raw_type={type(raw_value).__name__}"
            )
            return {"message": "ok"}

        paper_id = action_value.get("paper_id")
        decision = action_value.get("decision")

        logger.info(f"Card action from {user_id}: {paper_id} -> {decision}")

        if paper_id and decision:
            # Backlog 已移除：为兼容旧卡片点击，将其按速读处理
            if decision == "backlog":
                decision = "skim"

            ctx_key = _chat_context_key(user_id, chat_id)
            if ctx_key:
                _chat_last_paper_id[ctx_key] = paper_id

            config = {"configurable": {"thread_id": paper_id}}

            # 检查状态：必须在 waiting_decision
            state = await workflow_app.aget_state(config)
            if not state or not state.values:
                try:
                    await feishu_bot.send_text_message(receive_id, "论文状态未找到", receive_id_type=receive_id_type)
                except Exception:
                    logger.exception("Failed to send feishu not-found message")
                return {"message": "ok"}

            current_status = state.values.get("status")
            if current_status != "waiting_decision":
                try:
                    await feishu_bot.send_text_message(
                        receive_id,
                        f"无法从当前状态恢复: {current_status}",
                        receive_id_type=receive_id_type,
                    )
                except Exception:
                    logger.exception("Failed to send feishu invalid-status message")
                return {"message": "ok"}

            # 获取锁
            async with _paper_locks[paper_id]:
                # 双重检查
                state = await workflow_app.aget_state(config)
                if state.values.get("status") != "waiting_decision":
                    return {"message": "ok"}

                # 构建人工决策输入
                human_input = {
                    "decision": decision,
                    "tags": [],
                    "comment": ""
                }

                # 异步恢复工作流
                async def run_workflow():
                    try:
                        result = None
                        async for event in workflow_app.astream(Command(resume=human_input), config):
                            logger.info(f"Workflow event: {event}")
                            result = event

                        # 工作流完成，发送完成通知
                        if result:
                            state = await workflow_app.aget_state(config)
                            values = state.values

                            if values.get("status") == "completed":
                                await feishu_bot.send_completion_message(
                                    receive_id=receive_id,
                                    title=values["title"],
                                    decision=decision,
                                    craft_item_id=values.get("craft_collection_item_id"),
                                    craft_reading_doc_id=values.get("craft_reading_doc_id"),
                                    receive_id_type=receive_id_type,
                                )

                    except Exception as e:
                        logger.exception(f"Workflow resume failed for {paper_id}: {e}")
                        try:
                            await feishu_bot.send_text_message(
                                receive_id,
                                f"处理失败：{str(e)}",
                                receive_id_type=receive_id_type,
                            )
                        except Exception:
                            logger.exception("Failed to send feishu resume failure message")

                background_tasks.add_task(run_workflow)

    return {"message": "ok"}


async def _read_json_body(request: Request) -> dict:
    """
    读取请求体 JSON（尽量兼容不同 Content-Type）
    """
    try:
        data = await request.json()
        if isinstance(data, dict):
            return data
    except Exception:
        pass

    body = await request.body()
    if not body:
        return {}

    try:
        data = json.loads(body.decode("utf-8"))
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    return data


def _extract_feishu_token(payload: dict) -> str:
    """
    提取飞书回调 token（兼容旧/新结构）
    """
    if not isinstance(payload, dict):
        return ""

    token = payload.get("token")
    if token:
        return str(token)

    header = payload.get("header") or {}
    if isinstance(header, dict) and header.get("token"):
        return str(header.get("token"))

    return ""
