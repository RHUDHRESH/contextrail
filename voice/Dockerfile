# ContextRail voice door — Python 3.12 is required: the Vobiz-Sarvam base uses `audioop`, removed in 3.13.
# Buildable once voice/ holds the adapted clone (checklist T194+): server.py, agent.py, engine_client.py, requirements.txt.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app

COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY . .
RUN useradd --system --uid 10002 --home /app voice && chown -R voice /app
USER voice

EXPOSE 8100
HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8100/health', timeout=2)"

CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8100", "--proxy-headers", "--forwarded-allow-ips", "*"]
