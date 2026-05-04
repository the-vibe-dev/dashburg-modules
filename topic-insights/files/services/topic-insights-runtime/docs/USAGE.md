# Usage

## CLI
Initialize DB:
```bash
python -m apps.cli.main db-init
```

Run a scan:
```bash
python -m apps.cli.main run --query "laundry stains remove" --topic "household" --limit 60
```

Outputs:
- `data/reports/latest_report.html`
- `data/reports/latest_report.json`

## API
Start:
```bash
uvicorn apps.api.main:app --host 0.0.0.0 --port 8080
```

Endpoints:
- `GET /api/clusters`
- `GET /api/ideas?cluster_id=...`
