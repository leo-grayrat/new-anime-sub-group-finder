FROM python:3.13-slim
COPY --from=ghcr.io/astral-sh/uv:0.12.5 /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY fansub_finder ./fansub_finder
ENV FANSUB_PROXY="" FANSUB_DATA_DIR="/app/data"
EXPOSE 18765
CMD ["/app/.venv/bin/python", "-m", "fansub_finder", "serve", "--host", "0.0.0.0", "--port", "18765"]
