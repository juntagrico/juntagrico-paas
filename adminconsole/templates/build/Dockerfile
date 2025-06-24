ARG pythonversion=3.9
FROM python:$pythonversion-alpine

ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

RUN pip install --upgrade pip

# install psycopg for postgres
RUN apk add --update --virtual .build-deps gcc musl-dev postgresql-dev \
    && pip install psycopg[c] --no-cache-dir

ADD code/requirements.txt /

RUN pip install --upgrade -r requirements.txt

WORKDIR /code/

CMD ["gunicorn","--bind","127.0.0.1:{{ app.port }}","-t", "6000","{{ app.wsgi_path }}","&"]
