FROM python:3.12-slim

WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends libpq5 && rm -rf /var/lib/apt/lists/*
COPY requirements.txt requirements-lock.txt ./
RUN pip install --no-cache-dir -r requirements-lock.txt
COPY . .
RUN chmod +x docker-entrypoint.sh \
    && useradd --create-home --uid 10001 applypilot \
    && mkdir -p /data/storage \
    && chown -R applypilot:applypilot /data

# The API never needs root inside the container.
USER applypilot
EXPOSE 8000
ENTRYPOINT ["./docker-entrypoint.sh"]
