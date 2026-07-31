FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY monitor.py .

# PRAW's submission stream reconnects and backs off on its own; if the
# process does die (network blip, Reddit outage), restart: unless-stopped in
# docker-compose.yml brings it back rather than needing a supervisor here.
CMD ["python", "-u", "monitor.py"]
