# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

论文自动归档系统 - 基于 LangGraph 的半自动论文管理工作流，通过飞书机器人实现人机协作。

核心流程：论文 URL → LLM Triage 分析 → 人工决策（飞书卡片）→ 归档到 Craft

## Commands

```bash
# 安装依赖
pip install -r requirements.txt

# 配置环境变量
cp .env.example .env

# 运行开发服务器
uvicorn src.main:app --reload --host 0.0.0.0 --port 8000
```

## Architecture

### 工作流节点流程
```
Ingest → Extract → Triage (LLM) → Archive Base → Decision (INTERRUPT)
                                                        ↓
                              ┌─────────────────────────┴─────────────────────────┐
                              ↓                                                   ↓
                        Deep Read (LLM)                                    Update Archive
                              ↓                                                   ↓
                        Create Craft Doc                                        END
                              ↓
                        Update Archive → END
```

### 核心模块

**服务层** (`src/services/`):
- `llm_client.py` - OpenAI 客户端，支持 PDF URL 直接传输（无需下载）
- `craft_client.py` - Craft API 客户端，管理 Collection 和精读文档
- `paper_parser.py` - arXiv 论文解析器

**工作流节点** (`src/workflow/nodes/`):
- 使用 LangGraph 的 `interrupt()` 机制在 `decision_node` 暂停等待人工决策
- 通过 `thread_id` 恢复工作流

**状态管理** (`src/workflow/state.py`):
- `PaperState` TypedDict 定义工作流状态
- `DecisionType` 枚举：`deep_read`, `skim`, `drop`

### 外部服务集成

- **Craft API**: 归档论文到 Collection，创建精读文档
- **飞书机器人**: 消息入口，决策卡片交互
- **LLM (OpenAI)**: Triage 分析和 Deep Read 生成

## Key Patterns

- 所有服务客户端使用异步（`async/await`）
- 配置通过 `pydantic-settings` 从 `.env` 加载
- 全局客户端实例在模块底部导出（如 `llm_client`, `craft_client`）
- LLM 响应解析支持 JSON 和 markdown 代码块格式

## Configuration

必需环境变量：
- `LLM_API_KEY`, `LLM_BASE_URL`, `LLM_MODEL_NAME`
- `CRAFT_API_BASE_URL`, `CRAFT_COLLECTION_ID`, `CRAFT_READING_TEMPLATE_ID`
- `FEISHU_APP_ID`, `FEISHU_APP_SECRET`, `FEISHU_VERIFICATION_TOKEN`
