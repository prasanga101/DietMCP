FROM python:3.13-slim
WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY src ./src
RUN pip install --no-cache-dir uv && uv sync --frozen --no-dev
RUN useradd --create-home --uid 10001 diet && mkdir /data && chown diet:diet /data
USER diet
ENV DATA_DIR=/data FASTMCP_HOME=/data/fastmcp
EXPOSE 8000
CMD ["/app/.venv/bin/fitness", "serve"]
