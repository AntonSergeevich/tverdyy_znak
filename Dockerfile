# Многостадийная сборка: колёса собираем отдельно, в рантайм тащим только их.
FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1
WORKDIR /build

RUN apt-get update && apt-get install --no-install-recommends -y \
        build-essential libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip wheel --wheel-dir /wheels -r requirements.txt


FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    DJANGO_SETTINGS_MODULE=config.settings.prod

# Приложение работает от непривилегированного пользователя, не от root.
RUN groupadd --gid 1000 app && useradd --uid 1000 --gid app --create-home app

RUN apt-get update && apt-get install --no-install-recommends -y \
        libpq5 postgresql-client gettext curl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /wheels /wheels
COPY requirements.txt .
RUN pip install --no-index --find-links=/wheels -r requirements.txt && rm -rf /wheels

WORKDIR /app
COPY --chown=app:app . /app

# Каталоги, которые монтируются томами: права выставляем заранее.
RUN mkdir -p /app/staticfiles /app/media /app/private-media /app/logs \
    && chown -R app:app /app/staticfiles /app/media /app/private-media /app/logs

USER app

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/healthz || exit 1

# Sync-воркеры: async-вью в проекте не используются, см. docs/ARCHITECTURE.md.
CMD ["gunicorn", "config.wsgi:application", \
     "--bind", "0.0.0.0:8000", \
     "--workers", "3", \
     "--threads", "2", \
     "--timeout", "60", \
     "--graceful-timeout", "30", \
     "--max-requests", "1000", \
     "--max-requests-jitter", "100", \
     "--access-logfile", "-", \
     "--error-logfile", "-"]
