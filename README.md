# 论文自动归档系统

基于 LangGraph 构建的半自动论文归档系统，通过飞书机器人实现人机协作的论文管理流程。

## 功能特性

- 🤖 **飞书机器人入口** - 发送论文链接即可启动处理流程
- 🧠 **LLM 自动 Triage** - 自动生成概要、分析贡献点和局限性
- 👤 **人工决策点** - 通过飞书卡片进行精读/速读/Drop 决策
- 📝 **自动归档到 Craft** - 自动创建 Collection 条目和精读文档
- 💬 **飞书感想回填** - 直接回复「感想 ...」即可写入精读文档的「思考和感想」
- 🔧 **可配置 LLM** - 支持自定义 base_url、api_key、model

## 项目状态

**当前进度**: 约 95% 🎉

### ✅ 已完成（核心功能）

- [x] 项目架构设计
- [x] 基础配置管理
- [x] Craft API 客户端
- [x] LLM 客户端（支持 PDF URL 直接传输）
- [x] 论文解析模块（arXiv/PDF）
- [x] 工作流状态定义
- [x] **所有 LangGraph 工作流节点**
- [x] **LangGraph 主图和 interrupt 机制**
- [x] **飞书机器人集成**
- [x] **FastAPI 后端服务**
- [x] **SQLite Checkpointer**
- [x] **Deep Read 精读模块**

### 📋 待完善

- [ ] Docker 部署配置
- [ ] 单元测试
- [ ] 使用文档
- [ ] 错误处理增强

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置环境变量

复制 `.env.example` 为 `.env` 并填写配置：

```bash
cp .env.example .env
```

必填配置项：
- `LLM_API_KEY` - LLM API 密钥
- `CRAFT_API_BASE_URL` - Craft API 地址
- `FEISHU_APP_ID` - 飞书应用 ID
- `FEISHU_APP_SECRET` - 飞书应用密钥

### 3. 运行服务

```bash
# 开发模式
uvicorn src.main:app --reload --host 0.0.0.0 --port 8000
```

## 架构设计

详细的架构设计和实现方案请查看 `plans/implementation_plan.md`。

## 工作流程

1. **用户在飞书发送论文链接** → 机器人接收并启动工作流
2. **自动解析论文** → 提取元信息和全文
3. **LLM Triage 分析** → 生成概要和建议
4. **创建基础归档** → 写入 Craft Collection
5. **发送决策卡片** → 等待用户决策
6. **用户点击按钮** → 继续工作流
7. **执行后续操作** → 精读或直接完成
8. **发送完成通知** → 返回 Craft 链接

## 目录结构

```
read_paper_auto/
├── src/
│   ├── main.py                     # FastAPI 应用入口
│   ├── config.py                   # 配置管理
│   │
│   ├── workflow/
│   │   ├── state.py                # 工作流状态定义
│   │   ├── graph.py                # LangGraph 主图
│   │   └── nodes/                  # 工作流节点
│   │       ├── ingest.py           # 论文输入解析
│   │       ├── extract.py          # 文本提取
│   │       ├── triage.py           # LLM Triage
│   │       ├── archive.py          # Craft 归档
│   │       ├── decision.py         # 人工决策 (interrupt)
│   │       └── deep_read.py        # 精读笔记生成
│   │
│   ├── services/
│   │   ├── craft_client.py         # Craft API 客户端
│   │   ├── llm_client.py           # LLM 客户端
│   │   ├── paper_parser.py         # 论文解析器
│   │   └── feishu_bot.py           # 飞书机器人服务
│   │
│   ├── api/
│   │   ├── routes.py               # API 路由
│   │   └── schemas.py              # Pydantic 模型
│   │
│   └── persistence/
│       └── checkpointer.py         # SQLite Checkpointer
│
├── plans/
│   ├── implementation_plan.md      # 项目规划
│   └── implementation_status.md    # 项目现状
│
├── data/                           # 数据目录（运行时创建）
├── requirements.txt
├── .env.example
├── CLAUDE.md                       # AI 助手指南
└── README.md
```

## 下一步计划

1. **测试和调试** - 端到端功能测试
2. **添加 Docker 配置** - 容器化部署
3. **编写使用文档** - 部署和配置指南
4. **单元测试** - 核心功能测试覆盖
5. **错误处理增强** - 完善异常处理和重试机制
6. **性能优化** - 并发处理和缓存机制

## 技术栈

- **Web 框架**: FastAPI
- **工作流引擎**: LangGraph
- **LLM 集成**: LangChain
- **数据存储**: SQLite
- **论文解析**: arxiv, PyPDF2
- **HTTP 客户端**: httpx

## 许可证

MIT
