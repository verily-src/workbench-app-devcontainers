#!/bin/bash
# Development startup script

echo "🚀 Starting Cohort Multimodal Dashboard in dev mode..."

# Install backend deps
echo "📦 Installing backend dependencies..."
cd backend
python3.11 -m venv .venv
.venv/bin/pip install -q -e .

# Install frontend deps
echo "📦 Installing frontend dependencies..."
cd ../frontend
npm install --silent

echo "✅ Dependencies installed!"
echo ""
echo "To start development:"
echo "  Terminal 1: cd backend && .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8080 --reload"
echo "  Terminal 2: cd frontend && npm run dev"
echo ""
echo "Access at: http://localhost:5173 (dev) or http://localhost:8080 (production)"
