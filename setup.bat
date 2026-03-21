@echo off
REM ============================================
REM AI Recruitment Agent — Quick Setup (Windows)
REM ============================================

echo.
echo  ╔══════════════════════════════════════════╗
echo  ║  AI Recruitment Agent — Setup Script     ║
echo  ╚══════════════════════════════════════════╝
echo.

REM Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found. Install Python 3.10+ from python.org
    pause
    exit /b 1
)

REM Create virtual environment
if not exist "venv" (
    echo [1/5] Creating virtual environment...
    python -m venv venv
) else (
    echo [1/5] Virtual environment exists, skipping...
)

REM Activate
echo [2/5] Activating environment...
call venv\Scripts\activate.bat

REM Install PyTorch with CUDA (for NVIDIA GPU)
echo [3/5] Installing PyTorch with CUDA support...
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu121

REM Install requirements
echo [4/5] Installing dependencies...
pip install -r requirements.txt

REM Copy env file
if not exist ".env" (
    echo [5/5] Creating .env file...
    copy .env.example .env
    echo.
    echo  !! IMPORTANT: Edit .env to match your GPU !!
    echo.
    echo  For GTX 1650 Ti (4GB VRAM):
    echo    EMBEDDING_MODEL=all-MiniLM-L6-v2
    echo    OLLAMA_MODEL=phi3:mini
    echo.
    echo  For RTX 3050 (6GB VRAM):
    echo    EMBEDDING_MODEL=all-MiniLM-L6-v2
    echo    OLLAMA_MODEL=mistral:7b-instruct-q4_K_M
    echo.
) else (
    echo [5/5] .env already exists, skipping...
)

echo.
echo  ============================================
echo  Setup complete!
echo.
echo  Next steps:
echo    1. Install Ollama: https://ollama.com/download
echo    2. Pull your LLM model:
echo       ollama pull mistral:7b-instruct-q4_K_M
echo       (or: ollama pull phi3:mini  for 1650Ti)
echo    3. Start the server:
echo       python app.py
echo    4. Open: http://localhost:8000/docs
echo  ============================================
echo.
pause
