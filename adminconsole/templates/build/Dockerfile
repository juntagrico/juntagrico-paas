# syntax=docker/dockerfile:1
ARG pythonversion=3.9
FROM python:$pythonversion-alpine AS django
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1
RUN pip install --upgrade pip
# install psycopg for postgres & git to enable pip install from repos
RUN --mount=type=cache,target=/var/cache/apk apk add --update --virtual .build-deps gcc musl-dev postgresql-dev git \
    && pip install psycopg[c] --no-cache-dir

FROM django AS app
ADD code/requirements.txt /
RUN --mount=type=cache,target=/root/.cache/pip pip install --upgrade -r requirements.txt
WORKDIR /code/
CMD ["gunicorn","--bind","127.0.0.1:{{ app.port }}","-t", "6000","{{ app.wsgi_path }}","&"]
