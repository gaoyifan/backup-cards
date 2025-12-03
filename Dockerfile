# syntax=docker/dockerfile:1.7

FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends rsync udev exiftool \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY app.py ./app.py
COPY src ./src

VOLUME ["/data"]
EXPOSE 8080

ENTRYPOINT ["uv", "run", "app.py"]
CMD ["web", "--db-path", "/data/sd-backup.db", "--web-host", "0.0.0.0", "--web-port", "8080"]
