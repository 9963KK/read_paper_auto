"""
论文解析模块 - 支持 arXiv 和 PDF
"""
import re
import hashlib
import asyncio
from typing import Dict, Any, Optional
import arxiv
import PyPDF2
from io import BytesIO
import httpx
from loguru import logger


class PaperParser:
    """论文解析器"""
    
    @staticmethod
    def generate_paper_id(url: str) -> str:
        """生成论文唯一 ID"""
        return hashlib.md5(url.encode()).hexdigest()[:16]
    
    @staticmethod
    def extract_arxiv_id(url: str) -> Optional[str]:
        """从 URL 提取 arXiv ID"""
        patterns = [
            r'arxiv\.org/abs/(\d+\.\d+)',
            r'arxiv\.org/pdf/(\d+\.\d+)',
            r'(\d{4}\.\d{4,5})'
        ]
        
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1)
        return None
    
    async def parse_arxiv(self, url: str) -> Dict[str, Any]:
        """
        解析 arXiv 论文
        
        Args:
            url: arXiv URL
            
        Returns:
            包含 paper_id, title, authors, year, abstract, pdf_url, source_url
        """
        arxiv_id = self.extract_arxiv_id(url)
        if not arxiv_id:
            raise ValueError(f"Invalid arXiv URL: {url}")
        
        logger.info(f"Parsing arXiv paper: {arxiv_id}")

        def _fetch_paper():
            search = arxiv.Search(id_list=[arxiv_id])
            return next(search.results())

        # arxiv 库是同步请求：放到线程池避免阻塞事件循环
        paper = await asyncio.to_thread(_fetch_paper)
        
        # 获取 PDF URL（不下载，直接传给 OpenAI）
        pdf_url = paper.pdf_url
        
        result = {
            "paper_id": self.generate_paper_id(url),
            "source_url": url,
            "source_type": "arxiv",
            "title": paper.title,
            "authors": [author.name for author in paper.authors],
            "year": paper.published.year,
            "abstract": paper.summary,
            "pdf_url": pdf_url,  # 保存 PDF URL 供 LLM 使用
            "status": "extracting"
        }
        
        logger.info(f"ArXiv paper parsed: {paper.title}, PDF URL: {pdf_url}")
        return result
    
    async def _extract_pdf_text_from_url(self, pdf_url: str) -> str:
        """从 URL 下载 PDF 并提取文本"""
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.get(pdf_url)
            response.raise_for_status()
            pdf_content = response.content
        
        return self._extract_pdf_text(pdf_content)
    
    @staticmethod
    def _extract_pdf_text(pdf_content: bytes) -> str:
        """从 PDF 内容提取文本"""
        try:
            pdf_file = BytesIO(pdf_content)
            pdf_reader = PyPDF2.PdfReader(pdf_file)
            
            text_parts = []
            for page in pdf_reader.pages:
                text = page.extract_text()
                if text:
                    text_parts.append(text)
            
            full_text = "\n\n".join(text_parts)
            logger.info(f"Extracted {len(full_text)} characters from PDF")
            return full_text
        except Exception as e:
            logger.error(f"Failed to extract PDF text: {e}")
            return ""
    
    async def parse_pdf_file(self, pdf_content: bytes, filename: str) -> Dict[str, Any]:
        """
        解析上传的 PDF 文件
        
        Args:
            pdf_content: PDF 文件内容
            filename: 文件名
            
        Returns:
            包含 paper_id, title, full_text 等
        """
        logger.info(f"Parsing PDF file: {filename}")
        
        full_text = self._extract_pdf_text(pdf_content)
        
        # 尝试从文本中提取标题（通常是第一行）
        lines = full_text.split("\n")
        title = lines[0].strip() if lines else filename
        
        result = {
            "paper_id": self.generate_paper_id(filename),
            "source_url": f"file://{filename}",
            "source_type": "pdf",
            "title": title,
            "authors": [],
            "year": None,
            "abstract": "",
            "full_text": full_text,
            "status": "extracting"
        }
        
        logger.info(f"PDF file parsed: {title}")
        return result


# 全局解析器实例
paper_parser = PaperParser()
