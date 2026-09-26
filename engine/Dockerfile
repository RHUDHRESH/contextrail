# ContextRail engine — Python 3.12 (not 3.13: the voice door shares the runtime choice; CLAUDE.md §3).
# Installs exactly what engine/uv.lock pins; runs as a non-root user.
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.12.13 /uv /usr/local/bin/uv

ENV PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

# Dependencies first so code edits don't bust the dependency layer.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project

COPY contextrail ./contextrail
RUN uv sync --frozen --no-dev \
 && useradd --system --uid 10001 --home /app cr \
 && chown -R cr /app

USER cr
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2)"

CMD ["uvicorn", "contextrail.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
