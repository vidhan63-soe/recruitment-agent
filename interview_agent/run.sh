#!/bin/bash
# ═══════════════════════════════════════════════════
# AI INTERVIEWER — Quick Setup & Run
# ═══════════════════════════════════════════════════

set -e

echo "══════════════════════════════════════════════════"
echo "  AI INTERVIEWER — Setup"
echo "══════════════════════════════════════════════════"

# 1. Check Python
echo "[1/5] Checking Python..."
python3 --version || { echo "Python 3.8+ required"; exit 1; }

# 2. Install dependencies
echo "[2/5] Installing dependencies..."
pip install -r requirements.txt --break-system-packages 2>/dev/null || pip install -r requirements.txt

# 3. Check Ollama
echo "[3/5] Checking Ollama..."
if command -v ollama &>/dev/null; then
    echo "  Ollama found"
    if ! ollama list 2>/dev/null | grep -q "llama3.2:3b"; then
        echo "  Pulling llama3.2:3b..."
        ollama pull llama3.2:3b
    fi
else
    echo "  Ollama not found. Install from https://ollama.ai"
    echo "  Then run: ollama pull llama3.2:3b"
fi

# 4. Check .env
echo "[4/5] Checking configuration..."
if [ ! -f .env ]; then
    echo "  No .env found. Creating from template..."
    cp .env.example .env
    echo ""
    echo "  EDIT .env WITH YOUR FREE API KEYS:"
    echo "  Groq:    https://console.groq.com (free, no credit card)"
    echo "  Sarvam:  https://dashboard.sarvam.ai (Rs 1000 free credits)"
    echo "  LiveKit: https://livekit.io (free tier)"
fi

# 5. Load .env
echo "[5/5] Loading environment..."
if [ -f .env ]; then
    set -a
    source .env
    set +a
fi

echo ""
echo "══════════════════════════════════════════════════"
echo "  READY! Starting AI Interviewer..."
echo "══════════════════════════════════════════════════"
echo "  Dashboard:  http://localhost:5000"
echo "  WebSocket:  ws://localhost:5001/audio"
echo "  Health:     http://localhost:5000/api/health"
echo "══════════════════════════════════════════════════"
echo ""

python3 app.py
