# 🎮 PixelAgentOS

A pixel-art multi-agent collaboration platform. Play as a founder, hire AI agents, assign tasks, and watch them work in your virtual pixel office.

## Quick Start

### 1. Setup API Keys

```bash
cp backend/.env.example backend/.env
# Edit backend/.env and add:
# ANTHROPIC_API_KEY=sk-ant-...
# OPENAI_API_KEY=sk-...  (optional)
# TAVILY_API_KEY=tvly-... (optional, for web search)
```

### 2. Start Everything

```bash
./start.sh
```

Or manually:

```bash
# Terminal 1 — Backend
cd backend
.venv/bin/python -m uvicorn main:app --reload

# Terminal 2 — Frontend
cd frontend
npm run dev
```

Open **http://localhost:5173**

## How to Play

1. **Click an empty workstation** (desk with 🖥️) → Hire an agent
2. **Choose role**: Developer 💻 | Researcher 🔍 | Analyst 📊 | Writer ✍️
3. **Open Whiteboard** → Create a task and assign agents
4. **Click ▶ Run** → Watch agents work in real-time!
5. **Click an agent** → Chat with them or view details

## Architecture

```
Frontend (React + Phaser 3)
  ├── Phaser 3 Canvas — pixel office scene, agent sprites
  ├── React UI — whiteboard, modals, log panel
  └── Zustand — shared state

Backend (Python FastAPI)
  ├── WebSocket — real-time events
  ├── REST API — CRUD for agents & tasks
  ├── LangGraph — supervisor + worker orchestration
  └── LiteLLM — multi-LLM support (Claude, GPT-4o, etc.)
```

## Features

- 🏢 **Pixel office** with 12 workstations
- 🤖 **4 agent roles**: Developer, Researcher, Analyst, Writer
- 🛠️ **4 tools**: Web Search, Code Execution, Document Writing, Data Analysis
- 📋 **Kanban whiteboard** with auto-subtask decomposition
- 💬 **Real-time interaction log**
- 🤝 **Multi-agent collaboration** via LangGraph supervisor
- 🧠 **Agent memory**: short-term context + long-term history
- 🌐 **Multi-LLM**: Claude Sonnet/Opus/Haiku, GPT-4o, GPT-4o-mini

## File Structure

```
pixel-agent-os/
├── frontend/src/
│   ├── game/           # Phaser 3 scenes & sprites
│   ├── components/     # React UI panels
│   ├── store/          # Zustand state
│   └── hooks/          # WebSocket + GameBridge hooks
├── backend/
│   ├── main.py         # FastAPI + WebSocket
│   ├── agents/         # LangGraph orchestration
│   └── routes/         # REST API routes
└── start.sh            # One-command startup
```
