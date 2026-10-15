# Nightlight API on Cloud Run. Dependencies come from the committed uv.lock.
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.12.7 /uv /usr/local/bin/uv
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PYTHONUNBUFFERED=1
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
RUN uv sync --frozen --no-dev
EXPOSE 8080
CMD ["uv", "run", "--no-sync", "uvicorn", "nightlight_api.main:app", "--host", "0.0.0.0", "--port", "8080"]
