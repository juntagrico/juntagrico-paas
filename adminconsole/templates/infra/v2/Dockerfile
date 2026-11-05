# syntax=docker/dockerfile:1.4
ARG pythonversion={{ default_python_version }}
FROM python:$pythonversion-alpine AS django
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1
RUN pip install --upgrade --root-user-action=ignore "pip>=26.2.2"
# install psycopg for postgres & git to enable pip install from repos
RUN apk add --update --virtual .build-deps gcc musl-dev postgresql-dev git \
    && pip install --root-user-action=ignore psycopg[c] --no-cache-dir

FROM django AS app
COPY code/requirements*.txt /
RUN pip install --root-user-action=ignore --upgrade -r requirements.txt
WORKDIR /code/
CMD ["gunicorn","--bind","127.0.0.1:{{ app.port }}","-t", "600","{{ app.wsgi_path }}","&"]
