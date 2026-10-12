FROM ghcr.io/astral-sh/uv:0.13.0@sha256:cdc6093146eb3ff6a40107b38f008b789e050e77ad87865e381d9917da55a168 AS uv
FROM python:3.12-slim@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1
COPY --from=uv /uv /usr/local/bin/uv
WORKDIR /app
ENV UV_PYTHON_DOWNLOADS=never \
    UV_LINK_MODE=copy \
    INSTABAY_MODE=dry_run \
    INSTABAY_DB_PATH=/state/demo.sqlite3 \
    INSTABAY_CHECKPOINTS_PATH=/state/checkpoints.sqlite3 \
    INSTABAY_OUTBOX_PATH=/state/outbox \
    PATH="/app/.venv/bin:$PATH"
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
COPY sim ./sim
RUN uv sync --frozen --no-dev
COPY tests/fixtures/llm ./tests/fixtures/llm
COPY config ./config
COPY assets/photos ./assets/photos
RUN mkdir -p /state && chown 10001:10001 /state
USER 10001:10001
ENTRYPOINT ["instabay"]
CMD ["demo"]
