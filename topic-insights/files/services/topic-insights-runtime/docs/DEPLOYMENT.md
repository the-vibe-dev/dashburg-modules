# Deployment

## Environment
Copy `.env.example` to `.env` and set:
- `OPENAI_API_KEY` (preferred) OR run local Ollama and set `OLLAMA_BASE_URL`

## Run with Docker
```bash
docker build -t oie .
docker run --rm -p 8080:8080 --env-file .env -v $(pwd)/data:/app/data oie
```

## Run with docker-compose
```bash
docker compose up --build
```

## Run on a server (systemd)
Example service:
```ini
[Unit]
Description=OIE
After=network.target

[Service]
WorkingDirectory=/opt/oie
EnvironmentFile=/opt/oie/.env
ExecStart=/opt/oie/.venv/bin/uvicorn apps.api.main:app --host 0.0.0.0 --port 8080
Restart=always

[Install]
WantedBy=multi-user.target
```
