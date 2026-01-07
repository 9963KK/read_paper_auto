"""
SQLite Checkpointer - 工作流状态持久化
"""
import asyncio
import sqlite3
from pathlib import Path
from typing import Any, Sequence

from langgraph.checkpoint.sqlite import SqliteSaver
from loguru import logger

from src.config import settings


class SqliteSaverAsyncAdapter(SqliteSaver):
    """在同步 SqliteSaver 上提供异步接口，便于 LangGraph aget_state/astream 调用"""

    async def aget_tuple(self, config):
        return await asyncio.to_thread(self.get_tuple, config)

    async def aput(self, config, checkpoint, metadata, new_versions):
        return await asyncio.to_thread(self.put, config, checkpoint, metadata, new_versions)

    async def aput_writes(self, config, writes: Sequence[tuple[str, Any]], task_id: str, task_path: str = ""):
        return await asyncio.to_thread(self.put_writes, config, writes, task_id, task_path)


def get_checkpointer() -> SqliteSaver:
    """
    获取 SQLite Checkpointer 实例（同步 + 异步适配）

    Returns:
        SqliteSaverAsyncAdapter 实例
    """
    db_path = Path(settings.sqlite_db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    logger.info(f"Initializing SQLite checkpointer at: {db_path}")

    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    checkpointer = SqliteSaverAsyncAdapter(conn)

    logger.info("SQLite checkpointer initialized")
    return checkpointer
