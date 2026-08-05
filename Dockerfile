FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY monitor.py .

# The container runs as the vault owner (see `user:` in docker-compose.yml)
# rather than root, so notes land in the Obsidian vault owned by a normal
# user instead of root. Create the seen-state directory with that same
# ownership at build time: Docker seeds a fresh named volume from the image's
# directory, ownership included, so /app/state ends up writable by the
# non-root user. Without this the volume would be root-owned and the
# container couldn't persist its seen-post IDs.
ARG APP_UID=1000
ARG APP_GID=1000
RUN mkdir -p /app/state && chown -R ${APP_UID}:${APP_GID} /app/state

# The poll loop retries with backoff on its own; if the process does die
# (network blip, Reddit outage), restart: unless-stopped in
# docker-compose.yml brings it back rather than needing a supervisor here.
CMD ["python", "-u", "monitor.py"]
