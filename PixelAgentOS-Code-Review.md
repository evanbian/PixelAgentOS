# PixelAgentOS 代码审查与优化建议

## 测试结果概览

| 指标 | 结果 |
|------|------|
| 后端单元测试 | **100 通过 / 1 失败 / 12 跳过** |
| 前端 TypeScript 编译 | **通过** (0 错误) |
| 前端 ESLint | **4 个错误** |
| 日志文件 | 2.1 MB / 6566 行（持续增长，无轮转） |
| 数据库 | 512 KB |

---

## 一、后端关键问题

### 1. 安全性问题 🔴

**代码执行沙箱不完善** (`agents/tools.py`)

当前使用黑名单方式阻止危险代码，但存在绕过风险：

- `__import__('subprocess')` 未被拦截（只检查了字符串 `subprocess`，未检查动态导入）
- `exec("任意代码")` 的检测不完整
- `open('/etc/passwd')` 等敏感文件读取未阻止
- Shell 命令黑名单可通过空格变形、分号拼接等方式绕过

**建议**：改用白名单机制，或在 Docker 容器中执行代码。

**Web 搜索回退返回假数据** (`tools.py`)

当 Tavily API Key 未配置时，返回模拟搜索结果（"Simulated result..."），Agent 无法区分真假数据，可能导致输出包含虚构内容。

**建议**：直接返回错误信息，而非伪造结果。

### 2. 数据库连接效率 🟡

**每次操作都创建新连接** (`database.py`)

所有数据库函数都使用 `async with aiosqlite.connect(DB_PATH)` 独立创建连接。在高频操作（如任务执行期间频繁更新状态）下，连接开销会累积。

**建议**：引入连接池，或使用全局持久连接。

```python
# 当前：每个函数独立连接
async def get_agent(agent_id: str):
    async with aiosqlite.connect(DB_PATH) as db:  # 每次新连接
        ...

# 建议：使用全局连接或连接池
_db_pool: Optional[aiosqlite.Connection] = None

async def get_db():
    global _db_pool
    if _db_pool is None:
        _db_pool = await aiosqlite.connect(DB_PATH)
    return _db_pool
```

### 3. 并发竞态条件 🟡

**Scratchpad 写入冲突** (`agents/graph.py`)

多个并行子任务同时写同一个 scratchpad key 时，采用 filter + append 方式更新，可能丢失写入：

```python
# 有竞态风险
task.scratchpad = [e for e in task.scratchpad if e.key != key] + [entry]
```

**任务取消竞态** (`routes/tasks.py`)

取消任务时检查状态与实际取消操作之间存在时间窗口，可能导致状态不一致。

**建议**：使用数据库事务保证原子性操作。

### 4. PM Agent 容错不足 🟡

**LLM 调用无全局超时** (`agents/graph.py`, `agents/pm_agent.py`)

PM 的分解、审查、重规划等步骤虽有重试逻辑（3次指数退避），但缺少整体超时限制。如果 LLM API 持续无响应，任务会无限挂起。

**审查解析失败时自动通过** (`pm_agent.py`)

当审查结果 JSON 解析失败时，默认返回 `{"approved": True}`，可能掩盖质量问题。

**建议**：解析失败时应返回 `approved: false`，强制重做。

### 5. 重复代码 🟢

**DeepSeek DSML 标签清理** 在 `graph.py`、`pm_agent.py`、`worker.py` 三处重复实现。

**建议**：抽取为公共工具函数：

```python
# utils.py
import re

def clean_deepseek_tags(text: str) -> str:
    """Remove DeepSeek DSML wrapper tags."""
    return re.sub(r'<[｜|]DSML[｜|][^>]*>', '', text).strip()
```

### 6. 失败的测试

`test_skill_loader.py::test_filtered_by_ids` — `build_available_skills_xml(["web-search"])` 返回空 XML，说明 web-search 技能未正确注册或过滤逻辑有误。

---

## 二、前端关键问题

### 1. ESLint 错误（4个）

| 文件 | 问题 |
|------|------|
| `AgentCreateModal.tsx:140` | `modelId` 应使用 `const` |
| `DeliverableViewer.tsx:20,23` | `node` 定义未使用 |
| `useWebSocket.ts:351` | `connect` 在声明前被引用（重连逻辑） |

其中 `useWebSocket.ts` 的问题最关键——`connect` 函数在 `useCallback` 声明前被另一个 `useCallback` 引用，可能导致重连时使用过期的闭包。

**建议**：将 `connect` 的 `useCallback` 定义移到引用它的 `useCallback` 之前。

### 2. WebSocket 数据无运行时校验 🟡

所有从服务端接收的数据都使用 `as unknown as Type` 强制转换，没有运行时验证：

```typescript
// 当前做法 —— 危险
addAgent(data as unknown as Agent);

// 建议：使用 Zod 等库做运行时校验
const parsed = AgentSchema.safeParse(data);
if (parsed.success) addAgent(parsed.data);
```

### 3. 性能优化空间 🟡

**Store 订阅触发过多重渲染** (`App.tsx`)

多个状态字段订阅导致任意变更都触发完整重渲染。

```typescript
// 当前
const { wsConnected, agents, showTaskDashboard, tasks } = useStore();

// 建议：使用选择器精细订阅
const wsConnected = useStore(s => s.wsConnected);
const agentCount = useStore(s => s.agents.length);
```

**流式事件无节流** (`useWebSocket.ts`)

`subtask:stream` 事件高频触发 store 更新，每个 token chunk 都造成一次重渲染。

**建议**：添加 `requestAnimationFrame` 节流或批量更新。

**O(n×m) 查找** (`useWebSocket.ts`)

流式更新中对 tasks 数组的线性扫描在数据量大时性能堪忧。

**建议**：使用 `Map<taskId, Task>` 替代数组，实现 O(1) 查找。

### 4. 内存泄漏风险 🟡

**OfficeScene 订阅覆盖** (`game/scenes/OfficeScene.ts`)

activity feed 的 store 订阅赋值给了 `bridgeUnsubscribers`，但随后的 `storeUnsub` 覆盖了第一个订阅引用，导致 activity 订阅永远不会被清理。

### 5. 无障碍性 🟢

任务面板大量使用 emoji 作为按钮文本（如 DEL 删除按钮），缺少 ARIA 标签，对屏幕阅读器不友好。

---

## 三、架构层优化建议

### 1. 日志轮转

当前日志文件已达 2.1MB 且持续增长，没有轮转机制。

```python
# 建议：使用 RotatingFileHandler
from logging.handlers import RotatingFileHandler

handler = RotatingFileHandler(
    LOG_FILE, maxBytes=5*1024*1024, backupCount=3, encoding="utf-8"
)
```

### 2. CORS 配置

生产环境不应使用 `allow_origins=["*"]`，应限制为前端实际域名。

### 3. API 限流

聊天接口 (`/api/agents/{id}/chat`) 每次调用都会触发 LLM 请求，没有任何限流保护。高频调用可能导致巨额 API 费用。

**建议**：添加 per-agent 或 per-IP 限流中间件。

### 4. 任务工作区清理

删除任务时不会清理 `/workspaces/{task_id}/` 目录下的文件，长期运行会积累大量孤立文件。

### 5. 错误分类

LLM 调用的重试逻辑不区分暂时性错误（429 限流、503 不可用）和永久性错误（401 认证失败、400 参数错误），导致在认证失败时也会无意义地重试。

---

## 五、生产测试发现的 Bug 及修复记录（2026-03-03）

以下 Bug 均通过"主流 AI Agent框架调研"任务的生产测试发现并修复验证。

### Bug 1 (Critical): write_document({}) 空参数 — DeepSeek max_tokens 截断

**现象**：Writer agent 连续 4 次调用 `write_document({})`，参数为空 JSON。

**根因**：`max_tokens=4000` 对所有角色统一设置。DeepSeek V3.2 的 reasoning token 先消耗配额，导致 tool_call arguments JSON 被截断为 `{}`。

**修复**（`worker.py`）：
- `_streaming_llm_call` / `_blocking_llm_call` 新增 `max_tokens` 参数，不再硬编码
- `_run_agentic_loop` 中 role-aware max_tokens：Writer/Analyst/Designer → 8000，其余 → 4000
- Empty args fallback 增强：检查 `last_content` 作为备选内容源，阈值降至 200 chars

### Bug 2 (Medium): PM review 看不到上游 scratchpad

**现象**：PM 审阅下游子任务（如 Writer）时，只看到 41 chars 的 scratchpad 数据，缺失上游 Researcher 产出。

**根因**：PM review 的 scratchpad 过滤只用 `draft:{current_subtask_id}:` 前缀。

**修复**（`graph.py`）：
- 扩展 scratchpad 前缀列表，包含所有 `read_from` 上游子任务 + `file:` 全局前缀
- 同时包含上游 workspace 文件列表（带 `[upstream:title]` 标签）

### Bug 3 (Medium): Replan 丢失 max_iterations 预算

**现象**：Replan 后子任务 max_iter 全部重置为默认值 10，无视 PM 分配的预算。

**根因**：`pm_agent.py` 的 `replan()` 未在 prompt 中要求返回 `max_iterations`，也未在解析时提取。

**修复**（`pm_agent.py`）：
- Replan prompt 新增 rule 6 要求包含 `max_iterations`（4-10）
- SubTask 创建时解析并 clamp `max_iterations`

### Bug 4 (Minor): Skill 关键词匹配过于激进

**现象**：几乎每个 agent 都匹配到不相关的 skill（如 best-practices、keyword-research）。

**根因**：`_match_skills_to_task` 使用 3 字符最小 token 长度 + 1 个重叠即匹配。

**修复**（`worker.py`）：
- 最小 token 长度 3 → 5
- 新增 38 词 stopwords 集合
- 重叠阈值 1 → 2

### Bug 5 (Medium): Final Deliverable 显示 agent 回复而非文档内容

**现象**：前端 Final Deliverable 显示 agent 的"进度评估"文本（"我已经完成了..."），而非 `write_document()` 写入的实际报告。

**根因**：`execute_worker_task()` 返回的 `result_str` 是 agentic loop 的 `last_content`（LLM 最后一段文本回复），不是文档内容。当 `synthesis_needed=False` 时，`subtask_results[matched_id]` 就是这段汇报文本。

**修复**（`graph.py`）：
- 新增 `_read_best_workspace_file(ws_dir)` 工具函数 — 从 workspace 目录读取最佳文档文件（优先 `.md`，按 mtime 最新 + size 最大排序）
- `needed=False` 路径：从 `workspace_dir/agent_id/subtask_id` 读取实际文件
- `needed=True` 路径：从 `synth_ws`（synthesis agent 的 workspace）读取文件
- 两者都有 fallback 到 agent last response

**架构要点**：deliverable 的来源应该是 workspace 磁盘上的文件，而非 LLM 对话的最后一段回复。`write_document()` 写入磁盘 → graph 从磁盘读取 → 存入 `task.output` → 前端展示。

---

## 六、关键架构知识

### 1. 任务执行全流程（6-phase）

```
Phase 1: PM Decompose — PM 将任务拆分为子任务（含 max_iterations 预算）
Phase 2: Parallel Execute — 按依赖顺序并行执行子任务（scratchpad 共享）
Phase 3: PM Review — PM 逐个审阅子任务（1 次 rework 机会）
Phase 3.5: Worker Synthesis — PM 评估是否需要综合（1 次 LLM 调用）
Phase 4: PM Acceptance — PM 验证最终交付物质量（只读）
Phase 5: Finalize — 更新 DB + WebSocket 广播
```

### 2. Deliverable 流转路径

```
Agent 调用 write_document(filename, content)
  → 文件写入 workspace: workspaces/{task_id}/{agent_id}/{subtask_id}/{filename}
  → Auto-sync: scratchpad 写入 file:{filename} 元数据（JSON，含 path/size/brief）

PM evaluate_and_pick_synthesis()
  ├→ needed=False → graph 从 workspace 读取文件 → synthesis_result
  └→ needed=True  → synthesis agent 执行 → write_document → graph 从 synth_ws 读取 → synthesis_result

synthesis_result → PM acceptance check → final_output → task.output → DB
                                                      → ws "task:update" → 前端 DeliverableViewer
```

### 3. DeepSeek V3.2 使用注意

- 支持 parallel tool calls（实测 5x web_search、5x scrape_webpage 并行）
- Reasoning token 先于 output token 消耗 max_tokens 配额
- Writer/Analyst 等长输出角色需要 max_tokens ≥ 8000
- 会生成 DSML 标签（`<｜DSML｜...>`），需要在 graph/pm_agent/worker 三处清理
- tool_call arguments JSON 截断时表现为 `{}`，需要 fallback 机制

### 4. Scratchpad 共享机制

- 每个子任务的 scratchpad key 格式：`draft:{subtask_id}:{custom_key}`
- 文件引用 key 格式：`file:{filename}`（由 write_document auto-sync 生成）
- 下游子任务通过 `read_from` 依赖声明获得上游 scratchpad 读取权限
- PM review 时需要同时看到当前 + 上游 scratchpad entries

### 5. Workspace 目录结构

```
workspaces/
  {task_id}/
    {agent_id}/
      {subtask_id}/
        report.md          ← write_document 产物
        data.json           ← write_document 产物
      {synthesis_st_id}/    ← synthesis agent 的工作目录
        final_report.md
```

### 6. 前端交付物展示

- `DeliverableViewer.tsx` 渲染 `task.output` 为 Markdown
- 支持两个 Tab：Subtasks（各子任务输出）/ Scratchpad（共享数据）
- 底部固定显示 Final Deliverable（`task.output`）
- WebSocket 事件 `task:update` 携带 `output` 字段推送到前端

---

## 七、优先级排序

### 立即修复（高优先级）

1. **代码执行安全加固** — 安全风险最大
2. **WebSocket `connect` 声明顺序** — 影响重连可靠性
3. **Web 搜索假数据回退** — 影响输出可信度
4. **审查解析失败自动通过** — 影响任务质量保障

### 近期优化（中优先级）

5. 数据库连接池化
6. 日志轮转
7. Store 订阅精细化 + 流式事件节流
8. LLM 调用全局超时
9. DSML 清理代码去重
10. 任务取消原子操作

### 长期改善（低优先级）

11. WebSocket 数据运行时校验（Zod）
12. CORS 生产环境配置
13. API 限流中间件
14. 工作区文件清理
15. 无障碍性改进
