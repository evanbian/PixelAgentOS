# PixelAgentOS vs HiClaw 全方位对比报告

---

## 一、项目定位

**PixelAgentOS** 是一个像素风多智能体协作平台。用户扮演"创始人"角色，在一个 Phaser 渲染的像素风办公室里招聘 AI Agent、分配任务，由内置的 PM Agent 自动拆解任务、分发给 Worker、审查质量、合成最终交付物。核心卖点是"可视化 + 可交互的 AI 团队管理模拟器"。

**HiClaw** 是 Higress 团队开源的 Agent Teams 系统，定位为"Team 版 OpenClaw"。它在 OpenClaw（单 Agent 编码助手）的基础上引入 Manager Agent 角色，通过 Matrix 即时通讯协议实现多 Agent 协作，强调生产级安全（凭证隔离）和基础设施级部署（AI Gateway + Docker）。核心卖点是"安全的、可部署到生产环境的多 Agent 团队"。

| 维度 | PixelAgentOS | HiClaw |
|------|-------------|--------|
| 一句话定位 | 可视化 AI 团队办公模拟器 | 生产级多 Agent 协作系统 |
| 目标用户 | 开发者/创客/AI 爱好者 | 企业开发团队 |
| 核心隐喻 | 像素风办公室 | IM 群聊工作空间 |
| 开源时间 | 个人项目 | 2026-03-04 |
| GitHub 星数 | — | ~299 stars |
| 许可证 | — | Apache 2.0 |

---

## 二、技术栈对比

### 前端

| 维度 | PixelAgentOS | HiClaw |
|------|-------------|--------|
| 框架 | React 19 + TypeScript | Element Web（Matrix 客户端） |
| 游戏引擎 | Phaser 3.88 | 无 |
| 状态管理 | Zustand | Matrix SDK（自带状态同步） |
| 构建工具 | Vite 7.3 | — |
| UI 风格 | 自定义像素风 CSS | Element IM 界面（标准 IM） |
| 移动端 | 无 | 支持（Element Mobile / FluffyChat） |

PixelAgentOS 的前端是完全自研的，用 Phaser 3 渲染了一个像素风办公室场景，包含 9 个工位、PM 办公桌、白板、档案柜等交互元素。每个 Agent 有独立的精灵动画（idle/working/thinking/communicating）和表情气泡系统。

HiClaw 则直接复用了 Element Web 作为前端——本质上就是一个 Matrix 聊天客户端。用户在群聊里与 Manager 和 Worker 对话，不需要单独开发 UI。这意味着 HiClaw 天然支持任何 Matrix 客户端（Web、iOS、Android、桌面端）。

### 后端

| 维度 | PixelAgentOS | HiClaw |
|------|-------------|--------|
| 语言 | Python (FastAPI) | 基于 OpenClaw（TypeScript/Node.js） |
| 数据库 | SQLite + aiosqlite | — |
| 向量存储 | ChromaDB | — |
| LLM 接入 | LiteLLM（多模型抽象层） | Higress AI Gateway（统一代理） |
| 编排框架 | LangGraph | OpenClaw 内置 Agent 循环 |
| 通信协议 | WebSocket（自定义） | Matrix 协议（标准 IM） |
| 文件存储 | 本地文件系统 (workspaces/) | MinIO（对象存储） |
| 任务调度 | APScheduler (cron) | — |

### 基础设施

| 维度 | PixelAgentOS | HiClaw |
|------|-------------|--------|
| 部署方式 | `./start.sh`（本地启动） | `curl \| bash` 一键 Docker 部署 |
| 容器化 | 无 | Docker Compose（多容器） |
| API 网关 | 无 | Higress AI Gateway |
| IM 服务器 | 无 | Tuwunel（Matrix 服务器） |
| 最低配置 | 轻量（SQLite 即可跑） | 2C4G（推荐 4C8G） |
| 多架构 | — | amd64 + arm64 |

---

## 三、架构对比

### PixelAgentOS 架构

```
用户 (浏览器)
  │
  ├── React + Phaser 前端（像素办公室）
  │     └── WebSocket 连接
  │
  └── FastAPI 后端
        ├── PM Agent（任务拆解 → 审查 → 合成）
        ├── Worker Agents（并行执行子任务）
        ├── Tool 系统（搜索、代码执行、文件写入、数据分析…）
        ├── SQLite 数据库
        ├── ChromaDB 向量存储（语义记忆）
        └── 本地文件系统（workspaces/）
```

**特点**：单体架构，前后端分离但部署在同一台机器上。所有 Agent 运行在同一个 Python 进程中，通过 asyncio 实现并发。

### HiClaw 架构

```
用户 (Element Web / Mobile)
  │
  └── Matrix 协议
        │
        ├── Tuwunel（Matrix IM 服务器）
        │     └── Matrix Rooms（Manager ↔ Worker 对话）
        │
        ├── Manager Agent Container
        │     ├── OpenClaw（Manager 角色）
        │     └── Higress AI Gateway
        │           ├── LLM API 代理（持有真实 API Key）
        │           └── MCP Gateway（GitHub/Slack/Notion…）
        │
        ├── Worker Agent Container 1 (Alice)
        │     └── OpenClaw（只持有 consumer token）
        │
        ├── Worker Agent Container 2 (Bob)
        │     └── OpenClaw（只持有 consumer token）
        │
        └── MinIO（共享文件系统）
```

**特点**：微服务架构，每个 Worker 是独立的 Docker 容器。Manager 和 Worker 通过 Matrix 协议通信，凭证通过 Gateway 隔离。

### 关键架构差异

| 维度 | PixelAgentOS | HiClaw |
|------|-------------|--------|
| Agent 隔离 | 同一进程内（asyncio） | 独立 Docker 容器 |
| 通信方式 | 内存中共享 + WebSocket 广播 | Matrix 协议（跨容器） |
| 扩展性 | 垂直扩展（单机） | 水平扩展（加容器） |
| 故障隔离 | 一个 Agent 崩溃可能影响全局 | 容器级别隔离 |
| 延迟 | 极低（进程内调用） | 较高（网络 + Matrix 协议开销） |

---

## 四、Agent 系统对比

### 角色体系

**PixelAgentOS** 有 8 个预定义角色，每个角色有专属工具集和系统 Prompt：

- Developer（💻）：代码执行 + 文档写入
- Researcher（🔍）：网页搜索 + 文本摘要
- Analyst（📊）：数据分析 + 文档写入
- Writer（✍️）：文档写入
- Designer（🎨）：文档写入 + 计划创建
- PM（📋）：计划创建 + 文档写入
- DevOps（🔧）：代码执行 + HTTP 请求
- QA（🧪）：代码执行 + 数据分析

**HiClaw** 的 Worker 不区分角色，每个 Worker 是一个通用的 OpenClaw 实例，通过 Manager 的自然语言指令来定义职责（如"创建一个名为 alice 的前端开发 Worker"）。Worker 可以从 skills.sh 按需拉取社区技能。

| 维度 | PixelAgentOS | HiClaw |
|------|-------------|--------|
| 角色定义 | 预定义 8 种，代码级别 | 自然语言定义，动态创建 |
| 工具分配 | 按角色固定绑定 + 按需加载 | 通用 + 按需技能加载 |
| 技能扩展 | `find_skill` / `install_skill`（skills.sh 社区生态）+ 个人 SKILL.md | skills.sh 社区技能 |
| Agent 创建 | UI 弹窗选择角色/模型/技能 | Manager 自然语言指令 |

### 任务编排

**PixelAgentOS** 的任务流是一个 6 阶段的 LangGraph 图：

1. PM 拆解（将任务分解为子任务）
2. 并行执行（Worker 按依赖关系并行运行）
3. PM 审查（逐个审查子任务产出，可退回返工 1 次）
4. Worker 合成（指定 Agent 撰写最终交付物）
5. PM 验收（最终质量检查）
6. 完成归档

**HiClaw** 的编排更接近自然对话模式：

1. 用户在群聊中给 Manager 下达任务
2. Manager 创建/指派 Worker
3. Worker 在各自的 Matrix Room 中工作
4. Manager 定期心跳检查 Worker 状态
5. Worker 卡住时 Manager 自动告警

| 维度 | PixelAgentOS | HiClaw |
|------|-------------|--------|
| 编排模式 | 结构化流水线（LangGraph） | 对话式协调（IM + 心跳） |
| 子任务依赖 | 显式声明（depends_on, read_from） | Manager 自然语言协调 |
| 并行执行 | asyncio.gather() | 独立容器天然并行 |
| 质量审查 | PM 自动审查 + 退回返工 | Manager 监控 + 人工干预 |
| 任务调度 | Cron 定时任务 | — |

---

## 五、安全模型对比

这是两个项目差异最大的领域。

**PixelAgentOS**：

- API Key 存储在 SQLite 数据库，API 响应中做掩码处理（`****`）
- 代码执行有 30 秒超时限制
- 每个子任务有独立的工作目录（contextvars 隔离）
- 无凭证代理层——每个 Agent 直接持有 API Key

**HiClaw**：

- Worker **永远不持有真实凭证**——只有 Higress 发放的 consumer token
- 真实的 API Key、GitHub PAT 等存储在 AI Gateway 中
- Worker → Higress AI Gateway → LLM API / GitHub API
- 即使 Worker 被攻陷，攻击者也拿不到真实密钥
- 防惊群设计：Agent 只有被 @ 时才触发 LLM 调用
- 每个 Worker 可配置独立的访问权限

| 维度 | PixelAgentOS | HiClaw |
|------|-------------|--------|
| 凭证隔离 | ❌ Agent 直接持有 Key | ✅ Gateway 代理，Worker 只持 token |
| 代码沙箱 | subprocess + timeout | Docker 容器级隔离 |
| 文件隔离 | contextvars 目录隔离 | 容器级文件系统隔离 + MinIO |
| 攻击面 | Agent 被攻陷 = Key 泄露 | Agent 被攻陷 ≠ Key 泄露 |
| 权限控制 | 按角色固定工具集 | 每个 Worker 独立 MCP 权限 |
| 生产安全 | 适合开发环境 | 适合生产环境 |

---

## 六、通信与协作模型

### Agent 间通信

**PixelAgentOS**：

- 共享记事板（Scratchpad）：线程安全的 Key-Value 存储，Agent 通过 `write_scratchpad()` / `read_scratchpad()` 交换信息
- 直接消息：`request_help(to_agent_id, question)` 发起跨 Agent 对话
- 文件共享：通过 `read_from` 依赖关系访问上游子任务的工作目录
- 所有协作产物在内存/本地文件系统中

**HiClaw**：

- Matrix Rooms：每个 Agent 在群聊中发送消息，管理员可以看到所有对话
- MinIO 共享文件系统：工作中间产物不发到群聊，通过底层对象存储交换
- @ 机制：Agent 只有被 @ 时才响应，避免惊群
- 原生支持任何 Matrix 客户端

| 维度 | PixelAgentOS | HiClaw |
|------|-------------|--------|
| 协议 | 自定义 WebSocket + 内存共享 | Matrix（标准 IM 协议） |
| 消息可见性 | 前端 InteractionLog 组件 | 任何 Matrix 客户端实时可见 |
| 人工干预 | 点击 Agent → 发送聊天消息 | 在群聊中直接 @ Agent |
| 文件共享 | 本地 workspaces/ 目录 | MinIO 对象存储 |
| 审计追踪 | SQLite 日志 | Matrix 消息历史（永久） |

### Human-in-the-Loop

**PixelAgentOS**：

- 点击工位招聘 Agent
- 点击白板创建/管理任务
- 点击 Agent 精灵查看详情或聊天
- 点击 ▶ 触发任务执行
- 实时动画反馈（状态变化、表情气泡）
- 档案柜查看交付物

**HiClaw**：

- 在群聊中自然语言创建 Worker
- 在群聊中分配任务
- 随时在群聊中 @ 任何 Agent 干预
- 手机端随时查看和指挥
- Manager 自动告警卡住的 Worker

---

## 七、记忆与上下文管理

**PixelAgentOS** 有一个精心设计的三层记忆模型：

- **短期记忆**：最近 20 条消息
- **长期摘要**：短期溢出时 LLM 生成摘要
- **任务历史**：最近 10 个已完成任务的标题和结果
- **语义检索**：ChromaDB 向量存储，按相关性召回过去的经验
- **Agent 画像**：自动提取专长、偏好、事实

**HiClaw**：

- 基于 OpenClaw 的内置上下文管理
- Matrix 消息历史作为天然的对话记忆
- Worker 容器生命周期决定记忆范围

| 维度 | PixelAgentOS | HiClaw |
|------|-------------|--------|
| 记忆层次 | 三层（短期 + 长期 + 语义） | OpenClaw 内置 |
| 向量检索 | ✅ ChromaDB | — |
| 跨任务记忆 | ✅ Agent 画像持久化 | Worker 容器生命周期 |
| 上下文预算 | ~1300 token 固定窗口 | OpenClaw 默认策略 |

---

## 八、可观测性与调试

| 维度 | PixelAgentOS | HiClaw |
|------|-------------|--------|
| 执行指标 | Task metrics 持久化到 DB（工具分布、反思次数、耗时） | Manager 心跳监控 |
| 实时状态 | Agent 精灵动画 + 表情气泡 | Matrix 群聊消息流 |
| 日志 | agent_tasks.log + 控制台 | Docker 容器日志 |
| 看板 | 白板看板（todo/doing/done） | — |
| 流式输出 | ✅ LLM 输出实时流式到前端 | Matrix 消息 |

---

## 九、外部工具集成

### PixelAgentOS 内置工具

- `web_search()`：Tavily API
- `code_execute()`：Python 子进程（含 pandas/numpy/matplotlib）
- `write_document()`：本地文件写入
- `analyze_data()`：JSON/CSV 数据分析
- `read_file()`：读取工作区文件
- `http_request()`：外部 API 调用
- `summarize_text()`：文本摘要
- `create_plan()`：结构化计划
- `request_help()` / `send_message()`：Agent 间通信
- `recall()` / `remember()`：语义记忆
- `find_skill()`：搜索 skills.sh 开源技能生态（`npx skills find`）
- `install_skill()`：安装社区技能到 Agent 个人库（`npx skills add`）
- `read_skill()`：加载已安装技能的使用说明

PixelAgentOS 的技能系统采用**三层优先级策略**：有个人技能的 Agent 优先使用已安装技能（Layer 1），然后搜索 skills.sh 社区生态（Layer 2），最后才回退到内置工具（Layer 3）。没有个人技能的 Agent 则从 Layer 2 开始。系统还包含自动规划阶段，在执行前分析任务需求、检测技能缺口并自动安装所需技能。

### HiClaw MCP 集成

- 通过 Higress MCP Gateway + mcporter 访问外部服务
- 预置连接器：GitHub、Slack、Notion、Linear 等
- 自定义 MCP 服务器接入
- 每个 Worker 可配置独立的 MCP 访问权限
- skills.sh 生态系统

| 维度 | PixelAgentOS | HiClaw |
|------|-------------|--------|
| 工具协议 | LangChain @tool 装饰器 | MCP（Model Context Protocol） |
| 技能生态 | ✅ skills.sh（`find_skill` + `install_skill`）+ 个人 SKILL.md | ✅ skills.sh + MCP 连接器 |
| 外部服务 | Tavily + HTTP 请求 | MCP Gateway（GitHub/Slack/Notion…） |
| 扩展方式 | 写 Python 工具函数 + skills.sh 安装 | 标准 MCP 服务器 + skills.sh |

---

## 十、优劣势总结

### PixelAgentOS 的优势

1. **视觉体验独特**：像素风办公室 + Agent 动画 + 表情系统，有"游戏感"
2. **精细的任务编排**：6 阶段流水线、依赖管理、审查-返工机制
3. **深度记忆系统**：三层记忆 + ChromaDB 语义检索 + Agent 画像
4. **低门槛启动**：SQLite + 本地文件，不需要 Docker
5. **丰富的内置工具**：代码执行、数据分析、网页搜索、文件管理一应俱全
6. **实时可观测**：精灵动画、流式输出、白板看板、执行指标
7. **定时任务**：支持 cron 表达式定期执行
8. **技能生态接入**：通过 `find_skill` / `install_skill` 接入 skills.sh 社区生态，Agent 可自主搜索并安装所需技能
9. **白板看板系统**：内置 Kanban Board（todo/in_progress/done），支持创建任务、查看子任务进度、点击查看交付物

### PixelAgentOS 的劣势

1. **安全性弱**：Agent 直接持有 API Key，无凭证隔离
2. **隔离性差**：所有 Agent 同进程运行，无容器级隔离
3. **扩展性有限**：单机部署，难以水平扩展
4. **无标准协议**：自定义 WebSocket，非标准 IM/MCP
5. **无移动端**：仅支持浏览器访问

### HiClaw 的优势

1. **生产级安全**：凭证永不离开 Gateway，Worker 即使被攻陷也安全
2. **强隔离**：Docker 容器级隔离，Agent 互不影响
3. **标准协议**：基于 Matrix（开放 IM 标准）+ MCP
4. **多端支持**：Element Web、iOS、Android、任意 Matrix 客户端
5. **MCP 生态**：Higress MCP Gateway 连接器（GitHub/Slack/Notion…）+ skills.sh 社区技能
6. **水平扩展**：加 Worker 容器即可扩展团队规模
7. **企业级部署**：AI Gateway 统一管理 LLM 访问、按 Worker 分配权限

### HiClaw 的劣势

1. **资源消耗大**：最低 2C4G，多 Worker 需要 4C8G+
2. **无可视化**：没有游戏化的办公室 UI，只有 IM 聊天界面
3. **依赖 Docker**：部署需要容器化环境
4. **编排相对松散**：基于对话协调，缺少 PixelAgentOS 那样的结构化流水线
5. **缺少内置看板**：无任务管理白板/看板（PixelAgentOS 有完整的 Kanban Board）
6. **记忆系统简单**：缺少 PixelAgentOS 的多层语义记忆

---

## 十一、适用场景

| 场景 | 推荐 | 理由 |
|------|------|------|
| 个人学习/实验 AI 多 Agent | PixelAgentOS | 启动简单，可视化有趣，学习曲线低 |
| 企业内部开发团队 | HiClaw | 安全隔离、Docker 部署、MCP 生态 |
| 内容创作/研究分析 | PixelAgentOS | 内置搜索/分析/写作工具，任务编排精细 |
| 多人协作编程 | HiClaw | Matrix 多端支持，Worker 容器隔离 |
| Demo/展示 | PixelAgentOS | 像素风办公室视觉效果出色 |
| 生产环境部署 | HiClaw | 凭证隔离、容器化、Gateway 统管 |
| 定时自动化任务 | PixelAgentOS | 内置 APScheduler cron 调度 |
| 接入大量外部服务 | HiClaw | MCP Gateway 原生连接器更丰富（两者均支持 skills.sh） |

---

## 十二、结论

PixelAgentOS 和 HiClaw 虽然都是"多 Agent 协作系统"，但走的路线截然不同。

PixelAgentOS 更像是一个**功能完备的单机产品**——它在 Agent 编排的深度（6 阶段流水线、依赖管理、审查返工）、记忆系统的完备性（三层记忆 + 向量检索）、任务管理的可视化（白板看板系统）、技能生态的接入（`find_skill` / `install_skill` 对接 skills.sh 社区生态）、以及用户体验的趣味性（像素风办公室）上下了大量功夫。适合个人使用、学习、demo 展示、以及内容创作等场景。

HiClaw 则是一个**面向生产环境的基础设施级方案**——它通过 Higress AI Gateway 实现凭证隔离、通过 Docker 实现 Agent 隔离、通过 Matrix 实现标准化通信、通过 MCP 实现标准化工具接入。在安全性、可扩展性和标准化协议上具有明显优势，适合企业团队在真实项目中使用。

值得注意的是，两个项目在技能生态上都对接了 skills.sh 社区（PixelAgentOS 通过 `npx skills find/add`，HiClaw 通过 OpenClaw 内置机制），因此技能生态并非某一方的独占优势。PixelAgentOS 还额外拥有白板看板、三层技能优先级策略、以及自动规划阶段等特色功能。

简单来说：PixelAgentOS 是"功能丰富、好用又好玩的 AI 团队模拟器"，HiClaw 是"安全可靠的 AI 团队基础设施"。
