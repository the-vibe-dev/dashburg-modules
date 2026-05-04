# Top Ideas From DB

Use this command to generate ideas from existing DB clusters/pains without running ingestion:

```bash
python -m apps.cli.main top-from-db --ideas 8 --clusters 80
```

Output table columns:

- `cluster_label`
- `opportunity_score`
- `idea_name`

Notes:

- If in-memory cluster examples are missing (e.g. after restart), idea generation falls back to DB-backed pain examples selected by keyword overlap + urgency/intensity ranking.
- Scoring now merges duplicate cluster labels by canonical form before ranking.
- Theme boosts are configurable in `scoring_config.yaml` under `theme_boosts`.
