# 🎮 PixelAgentOS — 像素风多智能体协作平台

<img width="3024" height="1706" alt="image" src="https://github.com/user-attachments/assets/bacf4e20-cd42-4696-ae0d-849192a4956a" />

**PixelAgentOS** 是一个可视化的多智能体协作平台。你扮演创始人，在像素风办公室中雇佣 AI 员工、分配任务，看他们自主分解工作、通过结构化 Scratchpad 共享数据、协作完成交付——全程实时可见。

> 🚧 **早期阶段** — 这是一个个人项目，正在持续建设中。非常欢迎贡献，尤其需要**像素原画师**帮忙制作角色的行走、坐姿等多方向动画。详见[参与贡献](#-参与贡献)。

---

## ✨ 核心亮点

### 🧠 渐进式工具披露
Agent 不是一开始就拿到所有工具，而是**按需动态匹配**：
- 任务开始前，零成本关键词匹配已安装的技能
- 仅在需要专业能力时才搜索社区生态 + 自动安装
- Planning 阶段直接将技能指令注入 agent 上下文，省去冗余的 `read_skill()` 调用

### 📋 结构化 Scratchpad 协议
轻量级的 agent 间通信方案，避免上下文膨胀：
- `write_document()` 自动生成**结构化元数据索引**（章节标题、行号、关键数据点），而不是倒入全文
- 下游 agent 使用 `grep_workspace()` 和 `read_file_lines()` **定向检索**——上下文消耗降低 5-10 倍
- JSON 类型化条目（`file_deliverable`、`data_export`、`status_update`）支持程序化解析

### 🤝 Agent 间多通道通信
多种协作方式：
- **Scratchpad**：带可见性路由的结构化数据共享（每个 subtask 只看到相关的上游数据）
- **跨工作区文件访问**：`read_from` 机制授予对上游 agent 输出文件的只读权限
- **request_help()**：同步的 agent 间问答，带递归保护
- **通信光束**：agent 之间交换消息时的可视化动画

### 🎯 PM 驱动的质量闭环
PM Agent 负责整个流水线的编排：
- **任务分解**：带明确验收标准和迭代预算的 subtask 拆分
- **三级评审**（pass / minor / fail）—— minor 问题只需 2 轮快速修复，不触发完整 rework
- **失败重规划** —— subtask 失败时 PM 重新编排剩余工作，自动继承 read_from 可见性
- **合成跳过** —— 启发式检测最后一个 subtask 是否已经产出了最终交付物

### 🏢 像素风办公室
- Phaser 3 画布：可交互的工位、白板、文件柜
- 按角色区分的精灵表，状态驱动动画（idle 浮动、working 抖动、thinking 歪头）
- Twemoji 表情气泡 + 随机休闲行为
- 后端 agent 状态与像素精灵的实时同步

---

## 🚀 快速开始

### 前置条件
- Python 3.9+（含 venv）
- Node.js 18+
- 至少一个 LLM API Key（DeepSeek / OpenAI / Anthropic 等）

### 1. 克隆 & 配置

```bash
git clone https://github.com/evanbian/PixelAgentOS.git
cd PixelAgentOS
cp backend/.env.example backend/.env
```

编辑 `backend/.env`：
```env
# Worker Agent LLM（也可在 UI 中为每个 agent 单独设置）
DEEPSEEK_API_KEY=sk-...

# PM Agent LLM（在 Settings 页面设置）
# 支持：deepseek/deepseek-chat, openai/gpt-4o, anthropic/claude-sonnet-4 等

# 可选
TAVILY_API_KEY=tvly-...          # 网络搜索
OPENROUTER_API_KEY=sk-or-...     # 图像生成技能
```

### 2. 启动

```bash
./start.sh
```

打开 **http://localhost:5173**

### 3. 使用

1. **点击空工位** → 雇佣 agent（选择角色 + LLM 模型）
2. **打开白板**（右上角）→ 创建任务
3. **分配 agent** 并点击 ▶ **Run**
4. 观察 PM 分解任务、agent 搜索研究和写作、PM 评审和交付
5. **点击文件柜** → 查看最终交付物

---

## 🏗 架构

```
┌──────────────────────────────────────────────────┐
│  前端 (React 18 + Phaser 3 + Zustand)            │
│  ├── Phaser 画布 — 像素办公室、精灵动画           │
│  ├── React UI — 白板、聊天、交付物查看            │
│  └── WebSocket — 实时事件流                       │
└──────────────────┬───────────────────────────────┘
                   │ ws://localhost:8000/ws
┌──────────────────▼───────────────────────────────┐
│  后端 (FastAPI + LangGraph + LiteLLM)            │
│  ├── PM Agent — 分解、评审、重规划、合成           │
│  ├── Worker Agent — 带反思的工具调用循环           │
│  ├── Scratchpad — 结构化 agent 间数据共享         │
│  ├── Skill System — 社区生态搜索 + 自动安装       │
│  └── SQLite — agent、任务、指标持久化             │
└──────────────────────────────────────────────────┘
```

### 编排流程

```
用户任务
  → PM 分解（subtask + 依赖关系 + 迭代预算）
    → 并行执行（agent 调用工具，写入 scratchpad）
      → PM 评审（三级：通过 / 小修 / 打回重做）
        → 合成（如最后一个 subtask 已集成则跳过）
          → PM 验收 → 最终交付物
```

---

## 🔧 技术细节

### 工具体系（30 个）
网络搜索、代码执行、文档写作、数据分析、HTTP 请求、文件操作、网页抓取、文本差异、ZIP 压缩、计算器、正则提取、JSON 查询、模板渲染、日期计算、Shell 执行等。另有**技能生态系统**支持社区扩展的搜索 / 安装 / 使用。

### Agent 角色
| 角色 | 专长 | 常用工具 |
|------|------|----------|
| Researcher | 信息搜集、多源分析 | web_search, scrape_webpage, analyze_data |
| Developer | 编码、自动化、技术实现 | code_execute, shell_execute, write_document |
| Analyst | 数据处理、可视化、对比 | code_execute, analyze_data, calculate |
| Writer | 报告、文档、内容创作 | write_document, web_search, translate_text |
| Designer | 视觉素材、UI/UX、创意 | code_execute, shell_execute（+ 技能） |

### LLM 支持
通过 LiteLLM 支持所有主流模型：`deepseek/deepseek-chat`、`openai/gpt-4o`、`anthropic/claude-sonnet-4`、`openrouter/*` 等。每个 agent 可以使用不同的模型，PM agent 在 Settings 中单独配置。

---

## 📁 项目结构

```
PixelAgentOS/
├── frontend/src/
│   ├── game/              # Phaser 3 — 场景、精灵、配置
│   ├── components/        # React UI — 白板、面板、弹窗
│   ├── store/             # Zustand 状态管理
│   └── hooks/             # WebSocket + GameBridge hooks
├── backend/
│   ├── main.py            # FastAPI + WebSocket 服务
│   ├── agents/
│   │   ├── graph.py       # 6 阶段编排流水线
│   │   ├── worker.py      # 带反思的 agentic 工具调用循环
│   │   ├── pm_agent.py    # PM：分解、评审、重规划、合成
│   │   ├── scratchpad.py  # 结构化 agent 间数据共享
│   │   ├── tools.py       # 30 个 agent 工具
│   │   ├── file_indexer.py # 文档结构提取
│   │   └── skill_loader.py # 技能生态集成
│   └── database.py        # SQLite 持久化
└── start.sh               # 一键启动
```

---

## 🤝 参与贡献

项目处于**早期阶段**，有很大的成长空间。欢迎任何形式的贡献：

- **🎨 像素原画师** — 角色目前缺少行走循环、坐姿动画和多方向精灵。这是目前**最需要的帮助**。如果你擅长 Kairosoft 风格的 chibi 像素画，你的作品将直接让办公室活起来。
- **🧩 功能开发** — 基于 Tile 的寻路系统、角色移动、更丰富的办公室交互
- **🧠 Agent 智能** — 更好的规划策略、工具选择、上下文管理
- **🎮 游戏设计** — 办公家具、装饰、互动物品、小游戏
- **📝 文档** — 教程、架构深度解析、贡献指南

欢迎提 Issue 或 PR。较大的改动建议先开 Issue 讨论方案。

---

## 📜 许可证

MIT

---

<p align="center">
  <i>用咖啡因和好奇心构建。Agent 打工，你看像素。</i>
</p>
