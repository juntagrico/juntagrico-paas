# syntax=docker/dockerfile:1.4
ARG pythonversion=3.11
FROM python:$pythonversion-slim AS git

RUN apt-get update && apt-get install -y --no-install-recommends git


FROM git AS fetcher
ARG git_repo
ARG git_ref=main
RUN test -n "$git_repo" && git clone --depth 1 --branch "$git_ref" "$git_repo" /code


FROM git AS builder
ARG gunicorn_ver=">=25.1.0"
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --root-user-action=ignore --upgrade pip \
    && pip install --root-user-action=ignore 'psycopg[binary]' 'svglib<1.6.0' "gunicorn${gunicorn_ver}"

# install requirements
COPY --from=fetcher /code/requirements*.txt /code/
WORKDIR /code
RUN echo "Break Docker Cache: {% now "Y-m-d H:i:s.u" %}"
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --root-user-action=ignore --upgrade -r requirements.txt


FROM python:$pythonversion-slim AS app

# Create normal user
ARG appuser=appuser
ARG appuid=10001
RUN groupadd -g "${appuid}" "${appuser}" \
    && useradd -u "${appuid}" -g "${appuser}" -s /sbin/nologin "${appuser}"

# Copy only relevant libs
COPY --from=builder /usr/local/lib /usr/local/lib
COPY --from=builder /usr/local/bin/gunicorn* /usr/local/bin/
COPY --from=fetcher /code /code

RUN mkdir -p /code/internal_files && chown -R "$appuser" /code/internal_files

WORKDIR /code
USER "$appuser"

CMD ["gunicorn", "--no-control-socket", "--bind","127.0.0.1:{{ app.port }}", "-t", "600", "{{ app.wsgi_path }}"]
