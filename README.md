# 🎮 PixelAgentOS — Multi-Agent Collaboration with Pixel Art Office

[中文版 README](./README_CN.md)

<img width="3024" height="1706" alt="image" src="https://github.com/user-attachments/assets/bacf4e20-cd42-4696-ae0d-849192a4956a" />

**PixelAgentOS** is a visual multi-agent orchestration platform where AI agents work together in a pixel-art office. Hire agents with different roles, assign complex tasks, and watch them decompose work, share data through structured scratchpads, and deliver results — all in real time.

> 🚧 **Early Stage** — This is a personal side project under active development. Contributions are very welcome, especially from **pixel artists** who can help bring the characters to life with walk cycles and animations. See [Contributing](#-contributing).

---

## ✨ Highlights

### 🧠 Progressive Tool Disclosure
Agents don't get a fixed toolset. The system **dynamically matches tools and skills** to each task:
- Zero-cost keyword matching against installed skills before each subtask
- Ecosystem search + auto-install only when specialized tools are needed
- Planning phase injects skill instructions directly into agent context — no redundant `read_skill()` calls

### 📋 Structured Scratchpad Protocol
Lightweight inter-agent communication without context bloat:
- `write_document()` auto-generates **structured metadata indexes** (section headings, line numbers, key data points) instead of dumping full content
- Downstream agents use `grep_workspace()` and `read_file_lines()` for **targeted retrieval** — 5-10x context savings vs full file reads
- JSON-typed entries (`file_deliverable`, `data_export`, `status_update`) enable programmatic parsing

### 🤝 Agent-to-Agent Communication
Agents collaborate through multiple channels:
- **Scratchpad**: structured data sharing with visibility routing (each subtask sees only relevant upstream data)
- **Cross-workspace file access**: `read_from` grants read-only access to upstream agents' output files
- **request_help()**: synchronous agent-to-agent Q&A with recursion guards
- **Communication beam**: visual animation when agents exchange messages

### 🎯 PM-Driven Quality Loop
A Project Manager agent orchestrates the entire pipeline:
- **Decomposition** with explicit acceptance criteria and iteration budgets per subtask
- **Three-tier review** (pass / minor / fail) — minor issues get 2-iteration quick fix, not full rework
- **Replan on failure** — PM restructures remaining work when a subtask fails, with read_from inheritance
- **Synthesis skip** — heuristic detects when the last subtask already produced the final deliverable

### 🏢 Pixel Art Office
- Phaser 3 canvas with interactive workstations, whiteboard, and filing cabinet
- Per-role character spritesheets with status-driven animations (idle bob, working shake, thinking tilt)
- Emote system with Twemoji bubbles and random idle behaviors
- Real-time status sync between backend agent states and pixel sprites

---

## 🚀 Quick Start

### Prerequisites
- Python 3.9+ with venv
- Node.js 18+
- At least one LLM API key (DeepSeek, OpenAI, Anthropic, etc.)

### 1. Clone & Setup

```bash
git clone https://github.com/evanbian/PixelAgentOS.git
cd PixelAgentOS
cp backend/.env.example backend/.env
```

Edit `backend/.env`:
```env
# Worker agent LLM (set per-agent in UI, or use default)
DEEPSEEK_API_KEY=sk-...

# PM agent LLM (set in Settings page)
# Supports: deepseek/deepseek-chat, openai/gpt-4o, anthropic/claude-sonnet-4, etc.

# Optional
TAVILY_API_KEY=tvly-...          # Web search
OPENROUTER_API_KEY=sk-or-...     # Image generation skills
```

### 2. Start

```bash
./start.sh
```

Open **http://localhost:5173**

### 3. Play

1. **Click an empty desk** → Hire an agent (choose role + LLM model)
2. **Open Whiteboard** (top-right) → Create a task
3. **Assign agents** and click ▶ **Run**
4. Watch PM decompose the task, agents research & write, PM review & deliver
5. **Click Filing Cabinet** → View final deliverables

---

## 🏗 Architecture

```
┌─────────────────────────────────────────────────┐
│  Frontend (React 18 + Phaser 3 + Zustand)       │
│  ├── Phaser Canvas — pixel office, sprites      │
│  ├── React UI — whiteboard, chat, deliverables  │
│  └── WebSocket — real-time event stream         │
└──────────────────┬──────────────────────────────┘
                   │ ws://localhost:8000/ws
┌──────────────────▼──────────────────────────────┐
│  Backend (FastAPI + LangGraph + LiteLLM)        │
│  ├── PM Agent — decompose, review, synthesize   │
│  ├── Worker Agents — agentic tool-use loop      │
│  ├── Scratchpad — structured inter-agent data   │
│  ├── Skill System — ecosystem search + install  │
│  └── SQLite — agents, tasks, metrics            │
└─────────────────────────────────────────────────┘
```

### Orchestration Flow

```
User Task
  → PM Decompose (subtasks + dependencies + iteration budgets)
    → Parallel Execute (agents use tools, write to scratchpad)
      → PM Review (three-tier: pass / minor fix / fail + rework)
        → Synthesis (skip if last subtask already integrated)
          → PM Acceptance → Final Deliverable
```

---

## 🔧 Key Technical Details

### Tool System (30 tools)
Web search, code execution, document writing, data analysis, HTTP requests, file operations, scrape, diff, zip, calculate, regex, JSON query, template rendering, datetime, shell execute, and more. Plus a **skill ecosystem** with find/install/read for community extensions.

### Agent Roles
| Role | Specialty | Typical Tools |
|------|-----------|--------------|
| Researcher | Information gathering, multi-source analysis | web_search, scrape_webpage, analyze_data |
| Developer | Code, automation, technical implementation | code_execute, shell_execute, write_document |
| Analyst | Data processing, visualization, comparison | code_execute, analyze_data, calculate |
| Writer | Reports, documentation, content creation | write_document, web_search, translate_text |
| Designer | Visual assets, UI/UX, creative work | code_execute, shell_execute (+ skills) |

### LLM Support
Any model supported by LiteLLM: `deepseek/deepseek-chat`, `openai/gpt-4o`, `anthropic/claude-sonnet-4`, `openrouter/*`, and more. Each agent can use a different model. PM agent configured separately in Settings.

---

## 📁 Project Structure

```
PixelAgentOS/
├── frontend/src/
│   ├── game/              # Phaser 3 — scenes, sprites, config
│   ├── components/        # React UI — whiteboard, panels, modals
│   ├── store/             # Zustand state management
│   └── hooks/             # WebSocket + GameBridge hooks
├── backend/
│   ├── main.py            # FastAPI + WebSocket server
│   ├── agents/
│   │   ├── graph.py       # 6-phase orchestration pipeline
│   │   ├── worker.py      # Agentic tool-use loop with reflection
│   │   ├── pm_agent.py    # PM: decompose, review, replan, synthesize
│   │   ├── scratchpad.py  # Structured inter-agent data sharing
│   │   ├── tools.py       # 30 agent tools
│   │   ├── file_indexer.py # Document structure extraction
│   │   └── skill_loader.py # Skill ecosystem integration
│   └── database.py        # SQLite persistence
└── start.sh               # One-command startup
```

---

## 🤝 Contributing

This project is in its **early stages** and there's a lot of room to grow. Contributions of all kinds are welcome:

- **🎨 Pixel Artists** — The characters need walk cycles, sitting animations, and multi-direction sprites. This is the #1 need right now. If you can create Kairosoft-style chibi sprites, your work will directly make the office come alive.
- **🧩 Feature Development** — Tile-based pathfinding, agent movement system, richer office interactions
- **🧠 Agent Intelligence** — Better planning strategies, tool selection, context management
- **🎮 Game Design** — Office furniture, decorations, interactive objects, mini-games
- **📝 Documentation** — Tutorials, architecture deep-dives, contribution guides

Please feel free to open issues or PRs. For larger changes, open an issue first to discuss the approach.

---

## 📜 License

MIT

---

<p align="center">
  <i>Built with caffeine and curiosity. Agents do the work, you watch the pixels.</i>
</p>
