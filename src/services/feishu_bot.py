"""
飞书机器人服务
"""
import json
import ast
import re
import time
import httpx
from typing import Dict, Any, Optional, List, Iterable
from loguru import logger

from src.config import settings


class FeishuBot:
    """飞书机器人客户端"""

    def __init__(self):
        self.app_id = settings.feishu_app_id
        self.app_secret = settings.feishu_app_secret
        self.verification_token = settings.feishu_verification_token
        self.client = httpx.AsyncClient(timeout=30.0)
        self._access_token: Optional[str] = None
        self._access_token_expires_at: float = 0.0

    def _invalidate_access_token(self):
        self._access_token = None
        self._access_token_expires_at = 0.0

    @staticmethod
    def _is_invalid_access_token_error(response: httpx.Response) -> bool:
        # 99991663: Invalid access token for authorization
        try:
            data = response.json()
        except Exception:
            return False
        return isinstance(data, dict) and data.get("code") == 99991663

    @staticmethod
    def _get_api_error_code(response: httpx.Response) -> Optional[int]:
        try:
            data = response.json()
        except Exception:
            return None
        if not isinstance(data, dict):
            return None
        code = data.get("code")
        return code if isinstance(code, int) else None

    async def close(self):
        """关闭客户端"""
        await self.client.aclose()

    async def get_access_token(self) -> str:
        """
        获取飞书访问令牌

        Returns:
            访问令牌
        """
        now = time.time()
        if self._access_token and now < (self._access_token_expires_at - 60):
            return self._access_token

        url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
        payload = {
            "app_id": self.app_id,
            "app_secret": self.app_secret
        }

        response = await self.client.post(url, json=payload)
        response.raise_for_status()

        result = response.json()
        if not isinstance(result, dict) or result.get("code") not in (None, 0):
            raise RuntimeError(f"Failed to get Feishu tenant access token: {result}")

        token = result.get("tenant_access_token")
        if not token:
            raise RuntimeError(f"Feishu token missing in response: {result}")

        expire_seconds = 7200.0
        try:
            if result.get("expire") is not None:
                expire_seconds = float(result["expire"])
        except Exception:
            expire_seconds = 7200.0

        self._access_token = token
        self._access_token_expires_at = time.time() + expire_seconds

        logger.info("Feishu access token obtained")
        return self._access_token

    def verify_request(self, token: str) -> bool:
        """
        验证飞书请求

        Args:
            token: 验证 token

        Returns:
            是否验证通过
        """
        return token == self.verification_token

    def extract_url_from_message(self, text: str) -> Optional[str]:
        """
        从消息文本中提取论文 URL

        Args:
            text: 消息文本

        Returns:
            提取的 URL，如果没有则返回 None
        """
        if not text:
            return None

        patterns = [
            # arXiv abs
            r"https?://arxiv\.org/abs/[^\s]+",
            # arXiv pdf
            r"https?://arxiv\.org/pdf/[^\s]+",
        ]

        for pattern in patterns:
            match = re.search(pattern, text)
            if not match:
                continue
            url = match.group(0)
            # 去掉常见尾随标点（飞书里粘贴链接经常带上）
            url = url.rstrip(").,，。!！？?;；:：\"'”’】】》>】]")
            return url or None

        return None

    @staticmethod
    def _truncate_text(text: str, max_chars: int) -> str:
        if not text:
            return ""
        text = str(text).strip()
        if len(text) <= max_chars:
            return text
        return text[: max_chars - 1].rstrip() + "…"

    @staticmethod
    def _maybe_parse_list_literal(value: Any) -> Any:
        if not isinstance(value, str):
            return value
        text = value.strip()
        if not (text.startswith("[") and text.endswith("]")):
            return value
        try:
            parsed = ast.literal_eval(text)
        except Exception:
            return value
        return parsed

    @classmethod
    def _format_md_list(
        cls,
        value: Any,
        max_items: int = 6,
        max_item_chars: int = 220,
        bullet: str = "•",
    ) -> str:
        value = cls._maybe_parse_list_literal(value)

        if value is None:
            return ""

        if isinstance(value, str):
            text = value.strip()
            if not text:
                return ""
            # Already looks like list markdown
            if "\n" in text:
                return text
            return text

        if isinstance(value, Iterable):
            items: List[str] = []
            for item in value:
                item_text = cls._truncate_text(str(item).strip(), max_item_chars)
                if item_text:
                    items.append(item_text)

            if not items:
                return ""

            overflow = len(items) > max_items
            items = items[:max_items]
            if overflow:
                items.append("更多略…")

            return "\n".join([f"{bullet} {it}" for it in items])

        return cls._truncate_text(str(value).strip(), max_item_chars)

    @staticmethod
    def _format_tags(tags: Any, max_items: int = 8) -> str:
        if not tags:
            return "—"
        if isinstance(tags, str):
            return tags.strip() or "—"
        if isinstance(tags, Iterable):
            cleaned: List[str] = []
            for t in tags:
                s = str(t).strip()
                if s:
                    cleaned.append(s)
            cleaned = cleaned[:max_items]
            return " ".join([f"`{t}`" for t in cleaned]) if cleaned else "—"
        return str(tags).strip() or "—"

    @staticmethod
    def _format_action_label(action: Any) -> str:
        value = getattr(action, "value", action)
        return {
            "deep_read": "精读",
            "skim": "速读",
            # Backlog 已移除：为兼容旧数据，按速读展示
            "backlog": "速读",
            "drop": "Drop",
        }.get(str(value), str(value))

    async def send_text_message(
        self,
        receive_id: str,
        text: str,
        receive_id_type: str = "open_id"
    ):
        """
        发送文本消息

        Args:
            receive_id: 接收者 ID
            text: 消息文本
            receive_id_type: ID 类型（open_id, user_id, chat_id）
        """
        url = "https://open.feishu.cn/open-apis/im/v1/messages"
        params = {
            "receive_id_type": receive_id_type
        }
        payload = {
            "receive_id": receive_id,
            "msg_type": "text",
            "content": json.dumps({"text": text})
        }

        response: Optional[httpx.Response] = None
        for attempt in range(2):
            access_token = await self.get_access_token()
            headers = {
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            }
            response = await self.client.post(url, headers=headers, params=params, json=payload)
            if attempt == 0 and self._is_invalid_access_token_error(response):
                logger.warning("Feishu access token invalid; refreshing and retrying once")
                self._invalidate_access_token()
                continue
            break

        assert response is not None
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as e:
            body = (e.response.text or "")[:2000]
            logger.error(
                f"Feishu send_text_message HTTP error: status={e.response.status_code} receive_id_type={receive_id_type} receive_id={receive_id} body={body}"
            )
            raise

        # 飞书部分错误会返回 200 + code!=0
        try:
            result = response.json()
            if isinstance(result, dict) and result.get("code") not in (None, 0):
                logger.error(
                    f"Feishu send_text_message API error: code={result.get('code')} msg={result.get('msg')} receive_id_type={receive_id_type} receive_id={receive_id}"
                )
        except Exception:
            pass

        logger.info(f"Text message sent to {receive_id}")

    async def list_chat_messages(self, chat_id: str, page_size: int = 20) -> List[Dict[str, Any]]:
        """
        获取群聊消息列表（需要飞书权限：im:message.group_msg）。

        Args:
            chat_id: 群聊 chat_id（通常以 oc_ 开头）
            page_size: 拉取条数（1-50）

        Returns:
            消息 item 列表（原样返回 dict）
        """
        url = "https://open.feishu.cn/open-apis/im/v1/messages"
        params = {
            "container_id_type": "chat",
            "container_id": chat_id,
            "sort_type": "ByCreateTimeDesc",
            "page_size": max(1, min(int(page_size), 50)),
        }

        response: Optional[httpx.Response] = None
        for attempt in range(2):
            access_token = await self.get_access_token()
            headers = {
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            }
            response = await self.client.get(url, headers=headers, params=params)
            if attempt == 0:
                if self._is_invalid_access_token_error(response):
                    logger.warning("Feishu access token invalid; refreshing and retrying once")
                    self._invalidate_access_token()
                    continue

                # 230027: 权限不足（可能刚刚完成授权/发布，旧 token 未刷新）
                if self._get_api_error_code(response) == 230027:
                    logger.warning("Feishu permission error; refreshing token once and retrying")
                    self._invalidate_access_token()
                    continue
            break

        assert response is not None

        result: Any = None
        try:
            result = response.json()
        except Exception:
            result = None

        if response.status_code >= 400:
            body = (response.text or "")[:2000]
            code = result.get("code") if isinstance(result, dict) else None
            msg = result.get("msg") if isinstance(result, dict) else None
            logger.error(
                f"Feishu list_chat_messages HTTP error: status={response.status_code} chat_id={chat_id} code={code} msg={msg} body={body}"
            )
            if code is not None:
                raise RuntimeError(f"Feishu list_chat_messages failed: code={code} msg={msg}")
            response.raise_for_status()

        if not isinstance(result, dict) or result.get("code") not in (None, 0):
            raise RuntimeError(f"Feishu list_chat_messages API error: {result}")

        data = result.get("data") or {}
        items = data.get("items") or []
        if not isinstance(items, list):
            return []
        return [it for it in items if isinstance(it, dict)]

    async def send_decision_card(
        self,
        receive_id: str,
        paper_id: str,
        title: str,
        summary: str,
        contributions: Any,
        relevance: int,
        suggested_action: Any,
        suggested_tags: Any,
        receive_id_type: str = "open_id"
    ):
        """
        发送决策卡片

        Args:
            receive_id: 接收者 ID
            paper_id: 论文 ID
            title: 论文标题
            summary: 概要
            contributions: 贡献点
            relevance: 相关性评分
            suggested_action: 建议动作
            suggested_tags: 建议标签
            receive_id_type: ID 类型
        """
        summary_text = self._truncate_text(summary or "", 420)
        contributions_text = self._format_md_list(contributions, max_items=5, bullet="•")
        tags_text = self._format_tags(suggested_tags)
        action_text = self._format_action_label(suggested_action)
        suggested_action_value = str(getattr(suggested_action, "value", suggested_action) or "")
        if suggested_action_value == "backlog":
            suggested_action_value = "skim"

        # 构建卡片 JSON
        card = {
            "header": {
                "title": {
                    "tag": "plain_text",
                    "content": "📄 论文 Triage 结果"
                },
                "template": "blue"
            },
            "elements": [
                {
                    "tag": "div",
                    "text": {
                        "tag": "lark_md",
                        "content": f"**标题**\n{self._truncate_text(title, 180)}"
                    }
                },
                {
                    "tag": "div",
                    "text": {
                        "tag": "lark_md",
                        "content": f"**概要**\n{summary_text or '—'}"
                    }
                },
                {
                    "tag": "div",
                    "fields": [
                        {
                            "is_short": True,
                            "text": {"tag": "lark_md", "content": f"**评分**\n{relevance}/5"},
                        },
                        {
                            "is_short": True,
                            "text": {"tag": "lark_md", "content": f"**建议动作**\n{action_text}"},
                        },
                        {
                            "is_short": False,
                            "text": {"tag": "lark_md", "content": f"**建议标签**\n{tags_text}"},
                        },
                    ],
                },
                {
                    "tag": "div",
                    "text": {
                        "tag": "lark_md",
                        "content": f"**贡献点**\n{contributions_text or '—'}"
                    }
                },
                {
                    "tag": "div",
                    "text": {
                        "tag": "lark_md",
                        "content": "请选择下一步："
                    }
                },
                {
                    "tag": "hr"
                },
                {
                    "tag": "action",
                    "actions": [
                        {
                            "tag": "button",
                            "text": {
                                "tag": "plain_text",
                                "content": "📖 精读"
                            },
                            "type": "primary" if suggested_action_value == "deep_read" else "default",
                            "value": {"paper_id": paper_id, "decision": "deep_read"}
                        },
                        {
                            "tag": "button",
                            "text": {
                                "tag": "plain_text",
                                "content": "👀 速读"
                            },
                            "type": "primary" if suggested_action_value == "skim" else "default",
                            "value": {"paper_id": paper_id, "decision": "skim"}
                        },
                        {
                            "tag": "button",
                            "text": {
                                "tag": "plain_text",
                                "content": "🗑️ Drop"
                            },
                            "type": "danger",
                            "value": {"paper_id": paper_id, "decision": "drop"}
                        }
                    ]
                }
            ]
        }

        # 清理默认按钮样式：不设置 type 即为 default（减少兼容性问题）
        for el in card.get("elements", []):
            if isinstance(el, dict) and el.get("tag") == "action":
                for btn in el.get("actions", []) or []:
                    if isinstance(btn, dict) and btn.get("type") == "default":
                        btn.pop("type", None)

        url = "https://open.feishu.cn/open-apis/im/v1/messages"
        params = {
            "receive_id_type": receive_id_type
        }
        payload = {
            "receive_id": receive_id,
            "msg_type": "interactive",
            "content": json.dumps(card)
        }

        response: Optional[httpx.Response] = None
        for attempt in range(2):
            access_token = await self.get_access_token()
            headers = {
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            }
            response = await self.client.post(url, headers=headers, params=params, json=payload)
            if attempt == 0 and self._is_invalid_access_token_error(response):
                logger.warning("Feishu access token invalid; refreshing and retrying once")
                self._invalidate_access_token()
                continue
            break

        assert response is not None
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as e:
            body = (e.response.text or "")[:2000]
            logger.error(
                f"Feishu send_decision_card HTTP error: status={e.response.status_code} receive_id_type={receive_id_type} receive_id={receive_id} paper_id={paper_id} body={body}"
            )
            raise

        try:
            result = response.json()
            if isinstance(result, dict) and result.get("code") not in (None, 0):
                logger.error(
                    f"Feishu send_decision_card API error: code={result.get('code')} msg={result.get('msg')} receive_id_type={receive_id_type} receive_id={receive_id} paper_id={paper_id}"
                )
        except Exception:
            pass

        logger.info(f"Decision card sent to {receive_id} for paper {paper_id}")

    async def send_completion_message(
        self,
        receive_id: str,
        title: str,
        decision: str,
        craft_item_id: Optional[str] = None,
        craft_reading_doc_id: Optional[str] = None,
        receive_id_type: str = "open_id"
    ):
        """
        发送完成通知

        Args:
            receive_id: 接收者 ID
            title: 论文标题
            decision: 决策
            craft_item_id: Craft Collection Item ID
            craft_reading_doc_id: Craft 精读文档 ID
            receive_id_type: ID 类型
        """
        # 构建消息
        message = f"✅ 论文处理完成\n\n标题: {title}\n决策: {decision}"

        if craft_item_id:
            message += f"\n\nCraft 归档链接: craft://x-callback-url/open?blockId={craft_item_id}"

        if craft_reading_doc_id:
            message += f"\n精读文档链接: craft://x-callback-url/open?blockId={craft_reading_doc_id}"

        if str(decision) == "deep_read" and craft_reading_doc_id:
            message += (
                "\n\n如需记录你的精读感想，可直接回复：\n"
                "- 感想 这里写你的感想（默认写入最近一篇精读）\n"
                "- 感想 https://arxiv.org/abs/xxxx.xxxxx 这里写你的感想（指定论文，abs/pdf 均可）"
            )

        await self.send_text_message(receive_id, message, receive_id_type)


# 全局飞书机器人实例
feishu_bot = FeishuBot()
