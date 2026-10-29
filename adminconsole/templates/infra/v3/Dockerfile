# syntax=docker/dockerfile:1.4
ARG pythonversion=3.11
FROM python:$pythonversion-alpine AS django

ARG appuser=appuser
ARG appuid=10001
ARG gunicorn_ver=">=25.1.0"

# Create a non-root user
RUN addgroup -g "$appuid" "$appuser" \
    && adduser -D -u "$appuid" -G "$appuser" "$appuser"

ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# install psycopg for postgres & git to enable pip install from repos
RUN apk add --update --virtual .build-deps gcc musl-dev postgresql-dev git

RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --root-user-action=ignore --upgrade pip \
    && pip install --root-user-action=ignore 'psycopg[c]' 'svglib<1.6.0' 'gunicorn${GUNICORN_SPEC}'

FROM django AS app
# git pull
ARG git_repo
ARG git_ref=main
RUN test -n "$git_repo" && git clone --depth 1 --branch "$git_ref" "$git_repo" /code

# install requirements
WORKDIR /code
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --root-user-action=ignore --upgrade -r requirements.txt

RUN mkdir -p /code/internal_files && chown -R "$appuser" /code/internal_files

# Switch to the non-root user
USER "$appuser"

CMD ["gunicorn", "--no-control-socket", "--bind","127.0.0.1:{{ app.port }}", "-t", "600", "{{ app.wsgi_path }}"]
