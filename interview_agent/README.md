# AI Interviewer — Smart Interview Platform

An advanced AI-powered interviewer that conducts professional interviews for **any role** (SDE, IBD, PM, Data Science, Marketing, etc.) with real-time confidence scoring, cheating detection, adaptive difficulty, and detailed feedback reports.

**100% Free to run** — uses only free-tier APIs and open-source models.

## Free Services Used

| Service | Purpose | Free Tier |
|---------|---------|-----------|
| **Groq** | LLM brain (llama-3.3-70b) | Free, no credit card |
| **Ollama** | Local LLM fallback | Fully local |
| **Whisper** | Speech-to-Text | Local (HuggingFace) |
| **SarvamAI** | Indian English TTS/STT | Rs 1000 free credits |
| **Coqui TTS** | Local TTS fallback | Open source |
| **ChromaDB** | RAG memory | Local |
| **LiveKit** | Real-time audio | Free tier |

## Quick Start

```bash
# 1. Get API keys (free)
#    Groq:   https://console.groq.com
#    Sarvam: https://dashboard.sarvam.ai

# 2. Setup
cp .env.example .env     # Edit with your keys
pip install -r requirements.txt

# 3. Start Ollama (separate terminal)
ollama serve && ollama pull llama3.2:3b

# 4. Run
python app.py
# Open http://localhost:5000
```

## Interview Flow

INTRO -> BEHAVIORAL (STAR) -> SCENARIO -> CLOSING -> REPORT

### Scoring (7 Dimensions)
- Communication (15%), Confidence (10%), Domain Knowledge (25%)
- Behavioral Competency (20%), Problem Solving (15%)
- Cultural Fit (10%), Integrity (5%)

### Confidence Analysis (Real-time)
- Speech rate, filler words, hesitation, response latency, voice energy

### Cheating Detection
- Frontend: tab switch, copy-paste, DevTools, focus loss
- Voice: reading cadence, vocabulary jumps, contradictions, timing anomalies

## Project Structure

```
ai-interviewer/
  app.py                 # Main orchestrator and Flask server
  interview_engine.py    # State machine, questions, adaptive difficulty
  confidence_analyzer.py # Voice confidence analysis
  cheating_detector.py   # Multi-signal cheating detection
  scoring.py             # 7-dimension scoring and report
  processing.py          # STT + LLM + RAG
  output_handler.py      # TTS and audio output
  input_handler.py       # LiveKit audio input and VAD
  input_ws.py            # WebSocket browser mic input
  static/index.html      # Interview dashboard UI
```
