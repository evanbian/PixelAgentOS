#!/bin/bash
# PixelAgentOS — Start all services

set -e

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
FRONTEND_DIR="$ROOT_DIR/frontend"

# Fix proxy — ensure correct port (avoid stale 7890 from old sessions)
export http_proxy="http://127.0.0.1:7897"
export https_proxy="http://127.0.0.1:7897"
export all_proxy="socks5://127.0.0.1:7897"
export HTTP_PROXY="$http_proxy"
export HTTPS_PROXY="$https_proxy"
export ALL_PROXY="$all_proxy"

echo "🎮 Starting PixelAgentOS..."
echo ""

# Check .env
if [ ! -f "$BACKEND_DIR/.env" ]; then
    echo "⚠️  Creating backend/.env from template..."
    cp "$BACKEND_DIR/.env.example" "$BACKEND_DIR/.env"
    echo "   Please edit backend/.env and add your API keys!"
fi

# Start backend
echo "🐍 Starting FastAPI backend on port 8000..."
cd "$BACKEND_DIR"
.venv/bin/python -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload --reload-exclude "$BACKEND_DIR/workspaces" --reload-exclude "$BACKEND_DIR/agent_homes" &
BACKEND_PID=$!

# Wait for backend to start
sleep 2

# Start frontend
echo "⚛️  Starting React frontend on port 5173..."
cd "$FRONTEND_DIR"
npm run dev &
FRONTEND_PID=$!

echo ""
echo "✅ PixelAgentOS is running!"
echo "   Frontend: http://localhost:5173"
echo "   Backend:  http://localhost:8000"
echo "   API docs: http://localhost:8000/docs"
echo ""
echo "Press Ctrl+C to stop all services"

# Cleanup on exit
cleanup() {
    echo ""
    echo "🛑 Stopping services..."
    kill $BACKEND_PID 2>/dev/null
    kill $FRONTEND_PID 2>/dev/null
    wait
    echo "Goodbye! 👋"
}
trap cleanup INT TERM

wait
