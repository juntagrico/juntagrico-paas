FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DJANGO_SETTINGS_MODULE=adminconsole.settings

# Install system dependencies: libpq5 (psycopg runtime), git, and Docker CLI
# We use docker-ce-cli from Docker's official repo instead of docker.io, which is
# unreliable on slim images. docker-buildx is the separate plugin for `docker buildx`.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    git \
    ca-certificates \
    curl \
    && install -m 0755 -d /etc/apt/keyrings \
    && curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc \
    && chmod a+r /etc/apt/keyrings/docker.asc \
    && echo \
        "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/debian \
        $(. /etc/os-release && echo "$VERSION_CODENAME") stable" > /etc/apt/sources.list.d/docker.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends docker-ce-cli docker-buildx-plugin \
    && rm -rf /var/lib/apt/lists/*

# The django user needs access to the mounted Docker socket, which is owned by
# root:docker on the host. We ensure the docker group exists with the host's GID
# so the socket is accessible. Default to 982 (Debian/Ubuntu default).
# Override with DOCKER_GID build arg if your host uses a different GID:
#   docker build --build-arg DOCKER_GID=$(getent group docker | cut -d: -f3) .
ARG DOCKER_GID=982
RUN groupadd -g "${DOCKER_GID}" docker || groupmod -o -g "${DOCKER_GID}" docker && \
    useradd --create-home -G docker django

WORKDIR /app

RUN mkdir static && chown django:django static
RUN mkdir -p /etc/nginx/sites && chown django:django /etc/nginx/sites

COPY requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip pip install -r requirements.txt

COPY --chown=django:django . .

# Must happen before USER django so chmod works (root-only)
COPY docker/entrypoint.sh /docker/entrypoint.sh
RUN chmod +x /docker/entrypoint.sh

USER django

ARG WORK_DIR=/home/django/projects
RUN mkdir ${WORK_DIR}

EXPOSE 8000

ENTRYPOINT ["/docker/entrypoint.sh"]
