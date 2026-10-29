# syntax=docker/dockerfile:1.4
ARG pythonversion=3.11
FROM python:$pythonversion-alpine AS django

ARG appuser=appuser
ARG appuid=10001
# Create a non-root user
RUN addgroup -g "$appuid" "$appuser" \
    && adduser -D -u "$appuid" -G "$appuser" "$appuser"

ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --root-user-action=ignore --upgrade pip

# install psycopg for postgres & git to enable pip install from repos
RUN apk add --update --virtual .build-deps gcc musl-dev postgresql-dev git

RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --root-user-action=ignore 'psycopg[c]' 'svglib<1.6.0'

FROM django AS app
# install requirements
COPY code/requirements*.txt /
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --root-user-action=ignore --upgrade -r requirements.txt

# Switch to the non-root user
USER "$appuser"

WORKDIR /code
CMD ["gunicorn","--bind","127.0.0.1:{{ app.port }}","-t", "600","{{ app.wsgi_path }}","&"]