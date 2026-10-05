FROM oven/bun:1.3.12 AS frontend
WORKDIR /src
COPY package.json bun.lock ./
COPY frontend/package.json ./frontend/package.json
COPY packages ./packages
RUN bun install --frozen-lockfile
COPY frontend ./frontend
ENV VITE_API_URL=""
RUN bun run --filter frontend build

FROM python:3.14-slim
COPY --from=ghcr.io/astral-sh/uv:0.12.23 /uv /usr/local/bin/uv
WORKDIR /src
COPY pyproject.toml uv.lock ./
COPY backend ./backend
RUN uv sync --locked --package app --no-dev
COPY --from=frontend /src/backend/app/frontend ./backend/app/frontend
COPY proof ./proof
RUN useradd --uid 10001 --create-home runner && chown -R runner:runner /src
USER runner
ENV PATH="/src/.venv/bin:$PATH"
WORKDIR /src/backend
CMD ["uvicorn","app.main:app","--host","0.0.0.0","--port","8000"]
