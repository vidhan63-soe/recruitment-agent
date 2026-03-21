# ============================================================
# RecruitAI — Backend Dockerfile
# Python 3.11 slim, CPU-only (GPU via host runtime flags)
# ============================================================

FROM python:3.11-slim

WORKDIR /app

# System dependencies for pdfplumber, docx, etc.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies first (layer cache)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create runtime directories
RUN mkdir -p logs vectorstore

# Non-root user for security
RUN useradd -m appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

CMD ["python", "main.py"]
