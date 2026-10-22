FROM python:3.12-slim
# git is needed for local-repository import (git archive / git diff).
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:0.13.1 /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev
COPY . .
RUN useradd --create-home devpilot && mkdir -p /data && chown devpilot /data
USER devpilot
ENV PATH="/app/.venv/bin:$PATH" DEVPILOT_DATA_DIR=/data
EXPOSE 8000
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips=*"]
