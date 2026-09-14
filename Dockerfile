FROM python:3.11-slim

WORKDIR /app

# Min RAM + reliability env
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    UVICORN_WORKERS=1

# Create non-root user
RUN useradd -m -u 10000 appuser

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && rm -rf /root/.cache

# Copy only runtime files (no tests, no venv, no git)
COPY main.py leasing_client.py ./

USER appuser

EXPOSE 8000

# Docker HEALTHCHECK: /health must return 200 (open endpoint, no API key)
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4).status==200 else 1)"

CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port 8000 --workers 1 --loop asyncio --http h11 --no-access-log"]
