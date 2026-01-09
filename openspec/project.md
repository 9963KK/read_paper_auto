# 项目上下文

## Purpose

**论文自动归档系统（Read Paper Auto）** - 基于 LangGraph 的半自动论文管理工作流，通过飞书机器人实现人机协作。

**核心价值**：
- 自动化论文 Triage 分析（LLM 驱动）
- 人工决策介入点（飞书卡片交互）
- 归档到 Craft 知识库
- 可选深度精读笔记生成

**工作流**：
```
论文 URL → LLM Triage → 人工决策（interrupt） → 归档/精读 → Craft 存储
```

---

## 技术栈

### 核心框架
- **Python 3.12.3** - 主语言
- **FastAPI 0.115+** - Web 框架
- **LangGraph 0.2+** - 工作流引擎
- **Uvicorn** - ASGI 服务器
- **Pydantic 2.9+** - 数据验证 & 配置管理

### LLM 集成
- **OpenAI SDK 1.0+** - LLM 客户端（支持自定义 base_url）
- **LangChain 0.3+** - LLM 集成框架
- **langgraph-checkpoint-sqlite** - 工作流状态持久化

### 外部服务
- **Craft API** - 论文归档和精读文档管理
- **飞书开放平台** - 消息入口、决策卡片、群聊历史
- **arXiv API** - 论文元数据获取

### 工具库
- **httpx 0.26** - 异步 HTTP 客户端
- **PyPDF2 3.0** - PDF 处理
- **loguru 0.7** - 日志库
- **aiosqlite 0.19** - 异步 SQLite

---

## 项目约定

### 代码风格

#### 命名约定
- **文件**: 小写蛇形命名 `llm_client.py`, `paper_parser.py`
- **函数**: 小写蛇形命名 `generate_triage()`, `parse_arxiv()`
- **类**: 大驼峰命名 `LLMClient`, `CraftClient`, `PaperState`
- **全局实例**: 小写 `llm_client`, `craft_client`, `settings`
- **私有成员**: 单下划线前缀 `_access_token`, `_parse_json_response()`

#### 格式化规则
- 行宽：无硬性限制（建议 120 字符）
- 缩进：4 空格
- 字符串引号：双引号优先
- 导入顺序：标准库 → 第三方库 → 本地模块

### 异步优先原则
- ✅ 所有服务客户端使用异步 API（`AsyncOpenAI`, `httpx.AsyncClient`）
- ✅ 所有工作流节点使用 `async def`
- ✅ 同步库调用包装在 `asyncio.to_thread()`（如 arxiv 库）
- ✅ 并发控制使用 `asyncio.Lock`

### 错误处理模式
```python
# 节点标准错误处理
async def xxx_node(state: PaperState) -> PaperState:
    try:
        # 业务逻辑
        ...
        return state
    except Exception as e:
        logger.exception(f"XXX failed: {e}")
        state["status"] = "failed"
        state["error_message"] = str(e)
        return state
```

- 使用 `logger.exception()` 自动记录堆栈
- 节点失败设置 `status = "failed"` 和 `error_message`
- HTTP 错误记录响应体前 2000 字符

### 日志约定
- 使用 `loguru` 库（替代标准 logging）
- 全局导入：`from loguru import logger`
- 日志级别：`INFO` 默认，通过 `LOG_LEVEL` 环境变量控制
- 敏感信息脱敏：不记录完整 token、API key

---

## 架构模式

### 工作流节点架构（LangGraph）

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

**节点职责**：
- `ingest_node` - 解析 arXiv 论文元信息
- `extract_node` - 提取论文内容（预留，当前未实现）
- `triage_node` - LLM 分析论文（summary, contributions, limitations）
- `archive_base_node` - 创建 Craft Collection 归档
- `decision_node` - 人工决策暂停点（`interrupt()`）
- `deep_read_node` - 生成精读笔记（LLM）
- `update_archive_node` - 更新 Craft Collection 状态

### 服务层模式

```
src/services/
├── llm_client.py       # LLM 调用封装（Triage, Deep Read, Comment Optimize）
├── craft_client.py     # Craft API 客户端（Collection, Document, Thoughts）
├── paper_parser.py     # arXiv 解析器
└── feishu_bot.py       # 飞书机器人（消息、卡片、历史）
```

**设计原则**：
- 服务单例模式（模块底部导出全局实例）
- 配置注入（从 `config.settings` 读取）
- 异步优先（所有公开方法使用 `async def`）
- 职责单一（每个服务一个外部依赖）

### 状态管理
- `PaperState` TypedDict 定义工作流状态
- SQLite checkpoint 持久化（`langgraph-checkpoint-sqlite`）
- 通过 `thread_id` 恢复工作流
- 并发控制：进程内锁 + 消息去重（TTL 10 分钟）

### Prompt 工程模式
- **外部化**：Prompt 存储在 `/prompt_lab/prompts/*.md`
- **热更新**：重启服务生效（不需要修改代码）
- **风格对齐**：Deep Read 支持个性化风格指南拼接
  - 通过 `build_deep_read_style_guide.py` 脚本从历史笔记提炼用户偏好
  - 定时刷新（cron/systemd timer）

---

## 测试策略

### 当前状态
- ❌ **无测试文件**（MVP 阶段）
- ❌ 无自动化测试覆盖率

### 推荐框架（未来计划）
- **pytest** - Python 标准测试框架
- **pytest-asyncio** - 异步测试支持
- **pytest-mock** - Mock 工具
- **respx** - httpx Mock（替代 responses）

### 测试优先级（建议）
1. 服务层单元测试（`llm_client`, `craft_client`）
2. 节点功能测试（Mock 外部调用）
3. 工作流集成测试（使用测试 checkpoint）
4. API 端到端测试（使用 FastAPI TestClient）

---

## Git 工作流

### 提交规范
- **Conventional Commits** 格式：`<type>(scope): <subject>`
- Type：`feat`, `fix`, `refactor`, `chore`, `docs`, `test`
- Scope：功能模块（如 `llm`, `craft`, `workflow`, `deploy`）

**示例**：
```
feat(llm): 添加智能评论优化功能
refactor(llm): 提示词外部化支持热更新调教
chore(deploy): 添加 systemd 服务配置
```

### 分支策略
- **main** - 生产分支（直接部署）
- 小型项目，无需 feature 分支（直接提交到 main）
- 破坏性变更前需创建 OpenSpec 提案

### 代码审查
- 单人项目，无正式 Code Review
- OpenSpec 提案充当设计审查机制
- Codex Agent 用于质量审查

---

## 领域上下文

### 学术论文管理领域
- **arXiv 生态**：论文标识符格式 `2301.12345`
- **Triage 决策**：Deep Read（精读）, Skim（略读）, Drop（不读）
- **精读笔记结构**：Overview, Innovations, Future Directions
- **标签分类**：Multi-label（论文可有多个标签）

### 人机协作模式
- **LLM 角色**：初步分析论文，给出建议（不做最终决策）
- **人类角色**：最终决策者（通过飞书卡片选择）
- **工作流中断点**：`decision_node` 使用 `interrupt()` 暂停
- **恢复机制**：API 接收飞书回调后通过 `thread_id` 恢复工作流

### Craft 知识库约定
- **Collection**：论文归档列表（含 Triage 结果、标签、决策）
- **Reading Document**：精读笔记文档（基于模板创建）
- **Thoughts**：用户感想评论（追加到精读文档）

---

## 重要约束

### 外部服务依赖
1. **OpenAI API**（或兼容 API）
   - 必须支持 Chat Completions API
   - 可选支持 Responses API（传递 PDF URL）
   - 需要自定义 `base_url` 和 `api_key`

2. **Craft API**
   - 需要预先创建 Collection（获取 `CRAFT_COLLECTION_ID`）
   - 需要创建精读模板（获取 `CRAFT_READING_TEMPLATE_ID`）
   - 需要 Papers 文件夹（可选，`CRAFT_PAPERS_FOLDER_ID`）

3. **飞书开放平台**
   - 需要创建企业自建应用
   - 权限范围：接收消息、发送消息、读取群聊历史
   - 需要配置事件订阅和卡片回调 URL

### 配置管理约束
- ✅ 使用 `.env` 文件（不提交到 Git）
- ✅ `.env.example` 提供完整配置模板
- ✅ 通过 `pydantic-settings` 自动验证
- ❌ 不支持运行时动态修改配置（需重启服务）

### 并发与幂等性
- **并发控制**：
  - 进程内锁（`asyncio.Lock` 按 `paper_id`）
  - 消息去重（TTL 10 分钟）
  - 状态双重检查（锁前/锁内）
- **幂等性**：
  - 同一论文 URL 多次提交仅处理一次
  - 飞书回调重复请求自动去重

### 安全约束
- ❌ 不记录完整 API Key 到日志
- ✅ 飞书请求验证 `verification_token`
- ❌ 无用户认证（内部工具，基于飞书 App 权限控制）

---

## 外部依赖

### 必需服务

| 服务 | 用途 | 环境变量 | 文档 |
|------|------|---------|------|
| OpenAI API | LLM Triage & Deep Read | `LLM_API_KEY`, `LLM_BASE_URL`, `LLM_MODEL_NAME` | https://platform.openai.com/docs |
| Craft API | 论文归档 & 精读笔记 | `CRAFT_API_BASE_URL`, `CRAFT_COLLECTION_ID`, `CRAFT_READING_TEMPLATE_ID` | Craft 内部文档 |
| 飞书开放平台 | 消息入口 & 决策交互 | `FEISHU_APP_ID`, `FEISHU_APP_SECRET`, `FEISHU_VERIFICATION_TOKEN` | https://open.feishu.cn/document |

### 可选服务

| 服务 | 用途 | 环境变量 |
|------|------|---------|
| Aside LLM | 轻量任务（URL 提取、评论优化） | `ASIDE_LLM_BASE_URL`, `ASIDE_LLM_API_KEY`, `ASIDE_LLM_MODEL_NAME` |

### 第三方库依赖
- **arXiv API**：公开 API，无需认证（查询论文元数据）
- **PyPDF2**：本地 PDF 处理（预留功能，当前未使用）

---

## 部署与运维

### 部署方式
- **systemd 服务**：`deploy/systemd/read_paper_auto.service`
  - 自动重启：`Restart=always, RestartSec=10`
  - 工作目录：`/root/read_paper_auto`
  - 服务端口：12312

### 数据持久化
- **SQLite**：`./data/workflow.db`（LangGraph checkpoint）
- **风格指南**：`./data/deep_read_style_guide.md`

### 定时任务
- **Cron**：每月 1 日 3:15 更新精读风格指南
  ```cron
  15 3 1 * * cd /root/read_paper_auto && ./venv/bin/python scripts/build_deep_read_style_guide.py --max-docs 20 --use-llm
  ```

### 监控与日志
- 日志位置：stdout（由 systemd 捕获）
- 日志级别：通过 `LOG_LEVEL` 环境变量控制
- 无专门监控系统（依赖 systemd 自动重启）

---

## 项目规模

- **代码行数**：约 4,900+ 行 Python 代码
- **核心模块**：6 个工作流节点 + 4 个服务客户端
- **配置项**：约 20 个环境变量
- **外部依赖**：约 15 个 PyPI 包

---

## 开发环境设置

```bash
# 1. 克隆仓库
git clone <repo-url>
cd read_paper_auto

# 2. 创建虚拟环境
python3.12 -m venv venv
source venv/bin/activate

# 3. 安装依赖
pip install -r requirements.txt

# 4. 配置环境变量
cp .env.example .env
# 编辑 .env 填充必需配置

# 5. 启动开发服务器
uvicorn src.main:app --reload --host 0.0.0.0 --port 8000
```

---

## OpenSpec 使用约定

### 何时创建提案
- ✅ 新增功能（如"添加论文自动标签分类"）
- ✅ 破坏性变更（如"修改 PaperState 结构"）
- ✅ 架构调整（如"引入 Redis 缓存"）
- ❌ Bug 修复（直接修复）
- ❌ 日志、注释、格式调整（直接修复）

### 提案命名
- **格式**：kebab-case，动词引导
- **示例**：`add-auto-tagging`, `refactor-llm-client`, `update-feishu-card-ui`

### 规范组织
- **按功能模块划分**：`specs/llm-integration/`, `specs/workflow/`, `specs/craft-integration/`
- **单一职责**：每个规范文件聚焦一个功能领域
