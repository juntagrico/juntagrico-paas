# syntax=docker/dockerfile:1.4
ARG pythonversion={{ default_python_version }}

FROM python:$pythonversion-alpine AS base

# git is needed in the fetcher; gcc/musl-dev/postgresql-dev only in the builder.
# postgresql-dev can be dropped entirely if requirements.txt contains no packages
# that compile against libpq (everything here uses psycopg[binary] wheels).
RUN apk add --no-cache git \
    && apk add --no-cache --virtual .build-deps gcc musl-dev postgresql-dev


FROM base AS fetcher
ARG git_repo
ARG git_ref=main
# Force the fetcher stage to re-run on every build so COPY --from=fetcher
# in downstream stages always gets the latest fetched files.
# --no-cache-filter fetcher seems insufficient for this purpose
RUN echo "Break Docker Cache: {% now "Y-m-d H:i:s.u" %}"
# Fetch approach also works when git_ref is a commit SHA (unlike `git clone --branch`).
# -b main removes the warning about the initial branch name.
# The checkout is exported via `git archive` so the image never receives .git/,
# keeping remotes, refs, and history out of the final image.
# If git_token secret is provided, use it to authenticate with GitHub (for private repos).
# The token is passed as a BuildKit secret so it never appears in image layers.
{% if has_git_token %}
RUN --mount=type=secret,id=git_token,env=GIT_TOKEN \
    test -n "$git_repo" || (echo "git_repo build arg is required" && exit 1) \
    && git init -b main /code \
    && git -C /code remote add origin "$git_repo" \
    && git -C /code fetch --depth 1 -o "Authorization: Basic $(echo -n "x-access-token:${GIT_TOKEN}" | base64 -w0)" origin "$git_ref" \
    && git -C /code checkout FETCH_HEAD \
    && mkdir /export \
    && git -C /code archive HEAD | tar -x -C /export
{% else %}
RUN test -n "$git_repo" || (echo "git_repo build arg is required" && exit 1) \
    && git init -b main /code \
    && git -C /code remote add origin "$git_repo" \
    && git -C /code fetch --depth 1 origin "$git_ref" \
    && git -C /code checkout FETCH_HEAD \
    && mkdir /export \
    && git -C /code archive HEAD | tar -x -C /export
{% endif %}


FROM base AS builder
# TBD: Pin for reproducibility?
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# Core runtime dependencies, installed first so they can be ommited from the requirements.txt
# svg lib is forced < 1.6.0 due to a cairo dependency
ARG gunicorn_ver=">=25.2.2"
RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install --system --link-mode=copy \
        'psycopg[binary]' \
        'svglib<1.6.0' \
        "gunicorn${gunicorn_ver}"

# Project requirements
COPY --from=fetcher /export/requirements*.txt /code/
WORKDIR /code

# Make sure newest versions are installed
RUN echo "Break Docker Cache: {% now "Y-m-d H:i:s.u" %}"
# Remove pip, setuptools, wheel, and unused stdlib modules before copying to the
# app stage. This avoids doing cleanup in the final image and keeps it lean.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install --system --link-mode=copy -r requirements.txt \
    && rm -rf /usr/local/lib/python*/site-packages/pip* \
            /usr/local/lib/python*/site-packages/setuptools* \
            /usr/local/lib/python*/site-packages/wheel* \
            /usr/local/lib/python*/ensurepip \
            /usr/local/lib/python*/venv \
            /usr/local/lib/python*/idlelib \
            /usr/local/lib/python*/tkinter \
            /usr/local/lib/python*/turtle.py \
            /usr/local/lib/python*/turtledemo \
            /usr/local/lib/python*/lib2to3 \
            /usr/local/lib/python*/test \
    && chown -R root:root /usr/local/lib \
    && chmod -R a-w /usr/local/lib


FROM python:$pythonversion-alpine AS app

ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1
ENV PYTHONNOUSERSITE 1

# We use python:alpine as the base to guarantee the correct Alpine/musl version,
# but copy Python and installed libs from the builder so the base image's Python
# layer is overwritten. The base image layer is shared via Docker's content-
# addressable storage, so it doesn't waste disk space — it just ensures the
# musl libc version matches what Python's shared extensions expect.
# COPY merges content rather than replacing it, so we remove the base image's
# Python installation first to ensure only the builder's files remain.
RUN rm -rf /usr/local/lib/python* /usr/local/lib/dist-packages /usr/local/bin/python* /usr/local/bin/pip* /usr/local/bin/idle* /usr/local/bin/pydoc*
COPY --from=builder /usr/local/lib /usr/local/lib
COPY --from=builder /usr/local/bin/python* /usr/local/bin/
COPY --from=builder /usr/local/bin/gunicorn* /usr/local/bin/
RUN chmod -R a-w /usr/local/bin

# Create normal user
ARG appuser=appuser
ARG appuid=10001
RUN addgroup -g "${appuid}" -S "${appuser}" \
    && adduser -u "${appuid}" -G "${appuser}" -s /sbin/nologin -S "${appuser}"

COPY --from=fetcher /export /code

# set permissions so new volume mounted here later inherits it on creation
RUN mkdir -p /code/internal_files && chown -R "$appuser" /code/internal_files

WORKDIR /code
USER "$appuser"

# Documentation only — gunicorn binds to loopback, so ports must be published
# via a proxy sharing this container's network namespace, not `docker -p`.
EXPOSE {{ app.port }}

# Healthcheck to detect unresponsive app processes
# Fakes the Host header from JUNTAGRICO_DOMAINS so Django ALLOWED_HOSTS accepts the request.
# Requires JUNTAGRICO_DOMAINS to be set at runtime; if it is unset the check
# fails with Django DisallowedHost (empty Host header).
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD HOST=$(echo "$JUNTAGRICO_DOMAINS" | cut -d, -f1); wget --no-verbose --tries=1 --spider --header="Host: $HOST" http://127.0.0.1:{{ app.port }}/ || exit 1

CMD ["gunicorn", "--no-control-socket", "--bind","127.0.0.1:{{ app.port }}", "-t", "600", "{{ app.wsgi_path }}"]