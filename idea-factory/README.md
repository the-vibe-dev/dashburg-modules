# IdeaFactory

Installable Dashburg module pack.

## What is included
- Dashburg host module glue
- Local host-side pages and backend routes
- Uses the bundled TopicInsights/OIE runtime for deeper appgen flows

## Dependencies
- Modules: `topic-insights`
- Core capabilities: none

## Host install
```bash
cd ~/apps/dashgithub
./scripts/manage_modules.sh install idea-factory
```

## Required local runtime
Start `topic-insights` locally first.

## Host env
```bash
TOPIC_BASE_URL=http://127.0.0.1:8080
```

## Validation
- Local topic runtime reachable on `127.0.0.1:8080`
- Host module validates with `./scripts/manage_modules.sh validate idea-factory`

## Notes
- The public host-side IdeaFactory routes are local.
- The heavier OIE/appgen source is bundled through the TopicInsights runtime.
