FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential curl \
  && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY . /app

RUN mkdir -p /app/data

ENV PORT=8080
EXPOSE 8080

CMD ["bash", "-lc", "python -m apps.cli.main db-init && uvicorn apps.api.main:app --host 0.0.0.0 --port 8080"]
