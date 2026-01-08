"""
LLM API 客户端（支持自定义配置）
支持 OpenAI 的文件 URL 直接传输功能
"""
from typing import Dict, Any, Optional
from openai import AsyncOpenAI
from loguru import logger
import json
import re
from pathlib import Path

from src.config import settings


class LLMClient:
    """LLM 客户端"""
    
    def __init__(self):
        self.client = AsyncOpenAI(
            base_url=settings.llm_base_url,
            api_key=settings.llm_api_key
        )
        self.model = settings.llm_model_name

        aside_base_url = settings.aside_llm_base_url or settings.llm_base_url
        aside_api_key = settings.aside_llm_api_key or settings.llm_api_key
        aside_model = settings.aside_llm_model_name or settings.llm_model_name
        self.aside_client = AsyncOpenAI(base_url=aside_base_url, api_key=aside_api_key)
        self.aside_model = aside_model

        logger.info(f"LLM main model: {self.model}")
        logger.info(f"LLM aside model: {self.aside_model}")

    @staticmethod
    def _load_text_file(path: str, max_chars: int = 8000) -> str:
        if not path:
            return ""
        try:
            file_path = Path(path)
            if not file_path.exists() or not file_path.is_file():
                return ""
            text = file_path.read_text(encoding="utf-8").strip()
            if max_chars > 0 and len(text) > max_chars:
                return text[: max_chars - 1].rstrip() + "…"
            return text
        except Exception as e:
            logger.warning(f"Failed to load text file: path={path} error={e}")
            return ""

    async def generate_triage(
        self,
        title: str,
        abstract: str,
        pdf_url: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        生成 Triage 分析
        
        Args:
            title: 论文标题
            abstract: 摘要
            pdf_url: PDF 文件 URL（如果提供，将直接传给 OpenAI）
            
        Returns:
            包含 summary, contributions, limitations, relevance, suggested_action, suggested_tags
        """
        system_prompt = """你是一个专业的AI研究论文分析助手。请分析论文并提供以下信息：

1. 概要（summary）：用2-3句话概括论文的核心内容
2. 贡献点（contributions）：列出3-5个主要贡献点
3. 局限性（limitations）：指出2-3个局限性或未来改进方向
4. 相关性评分（relevance）：1-5分，评估论文的重要性和影响力
5. 建议动作（suggested_action）：deep_read（精读）、skim（速读）或 drop（放弃）
6. 建议标签（suggested_tags）：从以下标签中选择1-3个最相关的：
   - AI Infra
   - MultiMode
   - Agent
   - Context Engineering
   - Memory
   - Agent协作
   - Coding
   - Reasoning
   - Bench
   - Pre-Training
   - LLM
   - Post-Training
   - RAG

请以 JSON 格式返回结果，格式如下：
{
  "summary": "...",
  "contributions": "...",
  "limitations": "...",
  "relevance": 4,
  "suggested_action": "deep_read",
  "suggested_tags": ["Agent", "Reasoning"]
}"""
        
        # 构建用户消息内容
        content = []
        
        # 添加文本提示
        user_text = f"""论文标题：{title}

摘要：
{abstract}

请分析这篇论文。"""
        
        content.append({
            "type": "input_text",
            "text": user_text
        })
        
        # 如果有 PDF URL，添加文件
        if pdf_url:
            content.append({
                "type": "input_file",
                "file_url": pdf_url
            })
        
        logger.info(f"Generating triage for: {title}")
        if pdf_url:
            logger.info(f"Using PDF URL: {pdf_url}")
        
        try:
            try:
                response = await self.client.responses.create(
                    model=self.model,
                    instructions=system_prompt,
                    input=[{"role": "user", "content": content}],
                    temperature=0.7,
                )
                content_text = getattr(response, "output_text", None)
                if not content_text:
                    try:
                        content_text = response.output[0].content[0].text
                    except Exception:
                        content_text = ""
            except Exception as e:
                logger.warning(f"Responses API failed; falling back to chat completions: {e}")
                response = await self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_text},
                    ],
                    temperature=0.7,
                )
                content_text = response.choices[0].message.content
            
            # 解析 JSON 响应
            result = self._parse_json_response(content_text)
            logger.info(f"Triage generated successfully for: {title}")
            return result
            
        except Exception as e:
            logger.error(f"Failed to generate triage: {e}")
            # 返回默认值
            return {
                "summary": f"分析失败：{str(e)}",
                "contributions": "解析失败",
                "limitations": "解析失败",
                "relevance": 3,
                "suggested_action": "skim",
                "suggested_tags": ["LLM"]
            }
    
    async def generate_deep_read(
        self,
        title: str,
        abstract: str,
        triage_summary: str,
        pdf_url: Optional[str] = None
    ) -> Dict[str, str]:
        """
        生成精读笔记
        
        Args:
            title: 论文标题
            abstract: 摘要
            triage_summary: Triage 概要
            pdf_url: PDF 文件 URL
            
        Returns:
            包含 overview, innovations, directions
        """
        system_prompt = """你是一个专业的AI研究论文精读助手。请深入分析论文并提供：

1. 文章概述（overview）：详细描述论文的研究背景、问题定义、方法论和主要结果（300-500字）
2. 创新点（innovations）：深入分析论文的创新之处，包括技术创新、方法创新、应用创新等（200-300字）
3. 可能结合的方向（directions）：基于论文内容，提出3-5个可能的研究方向或应用场景

请用中文撰写，语言专业且易懂。

请以 JSON 格式返回结果，格式如下：
{
  "overview": "...",
  "innovations": "...",
  "directions": "..."
}"""

        style_guide = self._load_text_file(settings.deep_read_style_guide_path or "")
        if style_guide:
            system_prompt += (
                "\n\n# 用户精读偏好指南（必须遵循）\n"
                + style_guide
                + "\n\n请在不改变 JSON 字段结构的前提下，尽可能贴合该偏好指南输出。"
            )
        
        # 构建用户消息内容
        content = []
        
        user_text = f"""论文标题：{title}

摘要：
{abstract}

Triage 概要：
{triage_summary}

请进行深度分析。"""
        
        content.append({
            "type": "input_text",
            "text": user_text
        })
        
        # 如果有 PDF URL，添加文件
        if pdf_url:
            content.append({
                "type": "input_file",
                "file_url": pdf_url
            })
        
        logger.info(f"Generating deep read for: {title}")
        
        try:
            try:
                response = await self.client.responses.create(
                    model=self.model,
                    instructions=system_prompt,
                    input=[{"role": "user", "content": content}],
                    temperature=0.7,
                )
                content_text = getattr(response, "output_text", None)
                if not content_text:
                    try:
                        content_text = response.output[0].content[0].text
                    except Exception:
                        content_text = ""
            except Exception as e:
                logger.warning(f"Responses API failed; falling back to chat completions: {e}")
                response = await self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_text},
                    ],
                    temperature=0.7,
                )
                content_text = response.choices[0].message.content
            
            # 解析 JSON 响应
            result = self._parse_json_response(content_text)
            logger.info(f"Deep read generated successfully for: {title}")
            return result
            
        except Exception as e:
            logger.error(f"Failed to generate deep read: {e}")
            return {
                "overview": f"分析失败：{str(e)}",
                "innovations": "待补充",
                "directions": "待补充"
            }
    
    def _parse_json_response(self, content: str) -> Dict[str, Any]:
        """解析 LLM 返回的 JSON 响应"""
        try:
            # 尝试提取 JSON
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[1].split("```")[0].strip()
            
            return json.loads(content)
        except Exception as e:
            logger.warning(f"Failed to parse JSON response: {e}")
            # 如果解析失败，返回原始内容
            raise ValueError(f"Invalid JSON response: {content[:200]}")

    @staticmethod
    def _strip_fences(text: str) -> str:
        text = (text or "").strip()
        if "```" in text:
            parts = text.split("```")
            if len(parts) >= 3:
                text = parts[1].strip()
                if text.lower().startswith("json"):
                    text = text[4:].strip()
        return text.strip().strip('"').strip("'").strip()

    @staticmethod
    def _extract_first_url(text: str) -> Optional[str]:
        if not text:
            return None
        match = re.search(r"https?://[^\s<>\"]+", text)
        if not match:
            return None
        url = match.group(0).rstrip(").,;]}>\"'")
        return url

    @staticmethod
    def _extract_doi(text: str) -> Optional[str]:
        if not text:
            return None
        match = re.search(r"\b10\.\d{4,9}/[^\s\"<>]+", text)
        if not match:
            return None
        return match.group(0).rstrip(").,;]}>\"'")

    @staticmethod
    def _is_url_grounded(url: str, user_text: str) -> bool:
        if not url or not user_text:
            return False
        if url in user_text:
            return True

        doi = LLMClient._extract_doi(user_text)
        if doi and url.startswith("https://doi.org/") and doi in url:
            return True

        return False

    async def _extract_paper_url_with_client(
        self,
        client: AsyncOpenAI,
        model: str,
        system_prompt: str,
        user_text: str,
    ) -> Optional[str]:
        # 不同代理/中转对 OpenAI Responses API 支持不一致：
        # - 有些仅支持 Chat Completions
        # - OpenAI Python SDK 总是带有 .responses 属性，不能用 hasattr 判断
        # 这里优先用 chat；失败再尝试 responses
        try:
            resp = await client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_text},
                ],
                temperature=0,
            )
            content_text = resp.choices[0].message.content or ""
        except Exception:
            resp = await client.responses.create(
                model=model,
                instructions=system_prompt,
                input=user_text,
                temperature=0,
            )
            content_text = getattr(resp, "output_text", None) or ""

        content_text = self._strip_fences(content_text)
        if not content_text or "未获取到正确论文" in content_text:
            return None

        url = self._extract_first_url(content_text) or content_text.strip()
        if not url.startswith("http"):
            return None

        if not self._is_url_grounded(url, user_text):
            return None

        return url

    async def optimize_comment(self, raw_comment: str, paper_title: Optional[str] = None) -> str:
        """
        使用 ASIDE_LLM 优化用户评论内容。

        Args:
            raw_comment: 用户原始评论
            paper_title: 论文标题（可选，用于上下文）

        Returns:
            优化后的评论内容
        """
        system_prompt = """你是"论文评论优化助手"。任务：优化用户对学术论文的评论，使其更专业、清晰、有条理。

规则：
1) 保持原意：不改变用户的核心观点和评价
2) 语言优化：
   - 使用更专业的学术表达
   - 结构化表述（如有多个要点，用分点列出）
   - 修正明显的语法错误或口语化表达
3) 简洁性：控制在原文的 1.5 倍长度以内，避免过度扩展
4) 保留情感：保持用户的正面/负面倾向
5) 输出格式：纯文本，不要 markdown 格式标记（如 **、##、- 等）

输出示例：
输入："这篇文章方法不错但实验不够"
输出："文章提出的方法具有一定创新性，但实验部分验证不够充分，建议补充更多对比实验。"

输入："创新点很有意思 可以关注一下"
输出："论文的创新点值得关注，相关思路对后续研究有启发价值。"

禁止输出解释性文字，只输出优化后的评论内容。"""

        context_info = f"论文标题：{paper_title}\n\n" if paper_title else ""
        user_text = f"{context_info}用户评论：{raw_comment}\n\n请优化上述评论。"

        # 优先用 ASIDE_LLM；若失败则回退到主 LLM
        try:
            resp = await self.aside_client.chat.completions.create(
                model=self.aside_model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_text},
                ],
                temperature=0.3,  # 较低温度保证稳定性
            )
            optimized = (resp.choices[0].message.content or "").strip()
            if optimized:
                logger.info(f"Comment optimized by aside LLM: {len(raw_comment)} -> {len(optimized)} chars")
                return optimized
        except Exception as e:
            logger.warning(f"Aside LLM optimize comment failed, falling back to main LLM: {e}")

        try:
            resp = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_text},
                ],
                temperature=0.3,
            )
            optimized = (resp.choices[0].message.content or "").strip()
            if optimized:
                logger.info(f"Comment optimized by main LLM: {len(raw_comment)} -> {len(optimized)} chars")
                return optimized
        except Exception as e:
            logger.warning(f"Main LLM optimize comment failed, returning original: {e}")

        # 失败时返回原始评论
        return raw_comment

    async def extract_paper_url(self, user_text: str) -> Optional[str]:
        """
        使用 ASIDE_LLM 从文本中抽取论文链接。

        Returns:
            论文链接；若无法确定则返回 None
        """
        system_prompt = """你是"论文链接提取器"。任务：从用户输入中提取一个最可能指向论文入口的链接；若无法确定为论文链接则返回统一提示。

规则：
1) 只从输入里实际出现的内容提取，禁止编造/补全不存在的链接。
2) 论文链接判定标准（满足其一即可）：
   - 论文落地页：arxiv.org/abs、openreview.net/forum、aclanthology.org、dl.acm.org/doi、ieeexplore.ieee.org/document、link.springer.com、sciencedirect.com、nature.com、science.org、proceedings.mlr.press、papers.nips.cc 等
   - DOI：形如 10.xxxx/xxxxx（如输入只有 DOI 字符串，也算论文；输出时规范化为 https://doi.org/<DOI>）
   - 直接 PDF：URL 以 .pdf 结尾或明显是论文 PDF 下载链接（含 pdf 关键路径/参数）
3) 如果有多个候选，优先级：论文落地页 > DOI > PDF；返回最可能的一个。
4) 若无法找到满足判定标准的链接，或只有明显非论文链接（社交媒体/图片/广告/普通仓库主页等），则输出固定字符串：未获取到正确论文
5) 输出只允许两种形式之一：
   - 论文链接本身（纯文本）
   - 固定字符串：未获取到正确论文
禁止输出其他任何内容、标点、解释或 JSON。"""

        # 优先用 ASIDE_LLM；若因配置/鉴权失败，则回退到主 LLM，保证链路可用
        try:
            return await self._extract_paper_url_with_client(
                client=self.aside_client,
                model=self.aside_model,
                system_prompt=system_prompt,
                user_text=user_text,
            )
        except Exception as e:
            logger.warning(f"Aside LLM extract url failed: {e}")

        try:
            return await self._extract_paper_url_with_client(
                client=self.client,
                model=self.model,
                system_prompt=system_prompt,
                user_text=user_text,
            )
        except Exception as e:
            logger.warning(f"Main LLM extract url failed: {e}")
            return None


# 全局客户端实例
llm_client = LLMClient()
