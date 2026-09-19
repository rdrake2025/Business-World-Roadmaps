# Runs both the agent fleet and the public web surface.
FROM python:3.11-slim

# dig is used by the doctor to verify SPF/DMARC before allowing any send.
RUN apt-get update && apt-get install -y --no-install-recommends \
        dnsutils sqlite3 ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY answerrank/ ./answerrank/
COPY web/ ./web/
COPY run.py ./

# Business state lives here. Mount it as a volume or you lose everything
# on redeploy.
RUN mkdir -p /app/data
VOLUME ["/app/data"]

ENV PYTHONUNBUFFERED=1 \
    ANSWERRANK_DATABASE_PATH=/app/data/answerrank.db \
    ANSWERRANK_OUTPUT_DIR=/app/data/output

EXPOSE 8000

HEALTHCHECK --interval=60s --timeout=10s --start-period=15s --retries=3 \
    CMD python3 -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health',timeout=5).status==200 else 1)"

# Default to the web surface; the fleet runs as a second service.
CMD ["python3", "run.py", "web", "--port", "8000"]
