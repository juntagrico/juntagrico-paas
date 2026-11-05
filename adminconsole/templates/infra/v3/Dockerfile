# syntax=docker/dockerfile:1.4
ARG pythonversion={{ default_python_version }}

FROM python:$pythonversion-slim AS base

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*


FROM base AS fetcher
ARG git_repo
ARG git_ref=main
RUN test -n "$git_repo" && git clone --depth 1 --branch "$git_ref" "$git_repo" /code


FROM base AS builder
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

ARG gunicorn_ver=">=25.1.0"
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install --system --link-mode=copy 'psycopg[binary]' 'svglib<1.6.0' "gunicorn${gunicorn_ver}"

# install requirements
COPY --from=fetcher /code/requirements*.txt /code/
WORKDIR /code
RUN echo "Break Docker Cache: {% now "Y-m-d H:i:s.u" %}"
RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install --system --link-mode=copy -r requirements.txt


FROM python:$pythonversion-alpine AS app

ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1
ENV PYTHONNOUSERSITE 1

# Create normal user
ARG appuser=appuser
ARG appuid=10001
RUN groupadd -g "${appuid}" "${appuser}" \
    && useradd -u "${appuid}" -g "${appuser}" -s /sbin/nologin "${appuser}"

# Copy only relevant libs
COPY --from=builder /usr/local/lib /usr/local/lib
COPY --from=builder /usr/local/bin/gunicorn* /usr/local/bin/
COPY --from=fetcher /code /code

# Remove unused packages, so they can do no harm
RUN pip uninstall -y pip \
    && rm -rf /usr/local/lib/python*/ensurepip \
    && rm -rf /usr/local/lib/python*/venv \
    && rm -rf /usr/local/lib/python*/idlelib \
    && rm -rf /usr/local/lib/python*/tkinter \
    && rm -rf /usr/local/lib/python*/turtle.py \
    && rm -rf /usr/local/lib/python*/turtledemo \
    && rm -rf /usr/local/lib/python*/lib2to3 \
    && rm -rf /usr/local/lib/python*/test

# Make Python libraries read-only for the app user to prevent installing packages
RUN chown -R root:root /usr/local/lib \
    && chmod -R a-w /usr/local/lib

RUN mkdir -p /code/internal_files && chown -R "$appuser" /code/internal_files

WORKDIR /code
USER "$appuser"

# Healthcheck to detect unresponsive app processes
# Fakes the Host header from JUNTAGRICO_DOMAINS so Django ALLOWED_HOSTS accepts the request
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD HOST=$(echo "$JUNTAGRICO_DOMAINS" | cut -d, -f1) wget --no-verbose --tries=1 --spider --header="Host: $HOST" http://127.0.0.1:{{ app.port }}/ || exit 1

CMD ["gunicorn", "--no-control-socket", "--bind","127.0.0.1:{{ app.port }}", "-t", "600", "{{ app.wsgi_path }}"]
