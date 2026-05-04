# PLANLLM: Make LLM Output Operationally Useful

## Goal

Turn the LLM from a light metadata generator into a decision engine that:

1. proposes concrete `video`, `app`, and `SaaS` opportunities,
2. groups related opportunities into thoughtful strategic clusters,
3. produces high-conviction "big calls" with rationale and risk,
4. exports directly into Idea Factory in a format ready for execution.

This plan intentionally avoids code changes for now and defines implementation steps only.

## Current Gap (Why It Feels Useless)

- Core topic ranking is largely settled before LLM runs.
- LLM output mainly fills `summary/hooks/channel relevance` fields.
- Heuristic fallback often substitutes for weak LLM outputs.
- There is no durable artifact for strategic ideas (video/app/SaaS) beyond short hooks.
- Export payload for Topic Factory is too thin for execution planning.

## North-Star Output

For each run, produce:

1. Topic-level analysis (short summary + evidence).
2. Idea-level proposals across three formats:
   - Video idea
   - App idea
   - SaaS idea
3. Grouped strategic themes (clusters) with "why now".
4. 3-7 "Big Calls" ranked by conviction and expected impact.
5. Idea Factory-ready payload with execution metadata.

## Target Data Model (New Conceptual Objects)

### 1) `idea_candidates`

Per topic, multiple ideas with strict structure:

- `idea_id`
- `topic_id`
- `idea_type` (`video|app|saas`)
- `title`
- `one_liner`
- `problem_statement`
- `target_audience`
- `distribution_channel`
- `evidence` (source references + trend signals)
- `novelty_angle`
- `build_scope` (`small|medium|large`)
- `time_to_value_days`
- `confidence` (0..1)
- `risks`
- `next_step`

### 2) `idea_groups`

Cross-topic thematic clusters:

- `group_id`
- `theme_name`
- `thesis`
- `why_now`
- `included_idea_ids`
- `included_topic_ids`
- `market_window`
- `execution_sequence` (ordered moves)
- `group_score`

### 3) `big_calls`

High-conviction bets (the output users actually act on):

- `call_id`
- `headline`
- `bet_type` (`content_play|product_play|saas_play|hybrid`)
- `thesis`
- `supporting_groups`
- `expected_upside`
- `key_assumptions`
- `kill_criteria`
- `90_day_plan`
- `owner_profile`
- `conviction_score`

## LLM Workflow Redesign

## Phase 1: Topic Interpretation Pass

Purpose: normalize noisy trend inputs into reliable thematic summaries.

Inputs:

- clustered topics + source metrics
- source provenance (YouTube/Reddit/Trends)
- optional focus query/objective

LLM output:

- concise topic narrative
- durable trend signal classification (fad vs persistent)
- opportunity hints by format (`video/app/saas`)

Notes:

- Keep this pass analytical, not ideation-heavy.
- Force strict JSON schema.

## Phase 2: Idea Generation Pass (Core Value)

Purpose: generate practical ideas with execution context.

For each high-priority topic, ask for up to N ideas in each class:

- Video: hook format, segment angle, packaging title concepts.
- App: single-user utility concepts with MVP scope.
- SaaS: repeatable B2B/B2C workflow painkiller concepts.

Hard constraints in prompt design:

- no generic platitudes,
- require evidence linkage to topic/source signals,
- require explicit audience and acquisition path,
- require a concrete first step in <= 7 days.

Output must include confidence + uncertainty reasons.

## Phase 3: Grouping + Strategic Synthesis Pass

Purpose: convert many ideas into coherent strategic direction.

LLM tasks:

- cluster ideas into 3-8 groups by shared market/problem/theme,
- produce a thesis per group,
- identify cannibalization/conflicts,
- propose sequencing (what to launch first, second, third).

This pass is where "big grouped thoughtful calls" are produced.

## Phase 4: Big Calls Pass

Purpose: force prioritization into decisions.

LLM should output a limited set of bets (3-7 max):

- each call must map to one or more idea groups,
- each call must include assumptions and kill criteria,
- each call must include a 30/60/90 day action outline,
- each call must identify what success looks like quantitatively.

## Ranking and Selection Logic (Planned)

Current ranking should be augmented by idea utility scoring:

`final_idea_score = trend_strength + audience_clarity + distribution_fit + build_feasibility + monetization_potential + novelty - execution_risk`

Scoring dimensions to persist per idea:

- `trend_strength`
- `evidence_strength`
- `audience_clarity`
- `distribution_fit`
- `build_feasibility`
- `monetization_potential`
- `novelty`
- `execution_risk`
- `confidence`

Use this score for:

- top ideas in Idea Factory,
- inclusion threshold for grouping,
- big call candidate pool.

## Prompt Strategy (Planned)

Use separate prompts per phase instead of one overloaded prompt.

1. Interpreter prompt (facts + signal quality)
2. Generator prompt (video/app/saas ideas)
3. Synthesizer prompt (grouping + sequencing)
4. Investment-committee prompt (big calls + kill criteria)

Prompt requirements:

- strict JSON outputs only,
- explicit schema keys per phase,
- short rationale fields (bounded length),
- no chain-of-thought storage,
- deterministic-ish temperature profile (lower in synthesis and big calls).

## Idea Factory Integration Plan

## Export Contract v2 (Planned)

Extend current export shape so Idea Factory receives:

- `ideas[]` (typed idea objects)
- `idea_groups[]`
- `big_calls[]`
- `score_breakdowns`
- `evidence_links`
- `recommended_next_actions`

Minimal per-idea fields for Idea Factory UI:

- title
- type
- one-liner
- confidence
- feasibility
- monetization potential
- first 7-day task
- linked topic + evidence

## UI/UX Consumption Plan

Idea Factory should have 3 tabs:

1. `Ideas` (sortable by type and score)
2. `Groups` (theme-level strategy)
3. `Big Calls` (decision-grade bets)

Default landing: `Big Calls` (because this is the action surface).

## Reliability + Guardrails

- Keep fallback mode if LLM fails (existing topic ranking still works).
- Persist provenance for every generated idea (which topics/signals were used).
- Reject malformed LLM payloads with schema validation and retry.
- Mark low-confidence ideas clearly; do not mix with high-conviction bets.
- Add anti-generic checks (ban empty buzzword ideas).

## Metrics of Success

Success criteria after rollout:

1. At least 70% of top exported items include concrete 7-day executable steps.
2. At least 60% of runs produce >= 3 valid big calls.
3. Idea Factory click-through/select rate increases on exported items.
4. Human reviewers rate outputs as "actionable" at higher frequency than current hook-only output.
5. Rank movement after LLM passes is meaningful (not static pre-LLM ordering).

## Rollout Plan

## Milestone A: Schema + Prompts

- define all JSON schemas,
- define four prompts,
- add validation rules,
- dry-run on historical runs.

## Milestone B: Idea Generation + Storage

- generate typed ideas per topic,
- persist score breakdowns and provenance,
- expose ideas in run results.

## Milestone C: Grouping + Big Calls

- generate group artifacts,
- generate big calls,
- expose in API response.

## Milestone D: Idea Factory Export v2

- add new export payload,
- wire to Idea Factory tabs,
- add diagnostics for confidence and risk.

## Milestone E: Evaluation Loop

- add review rubric,
- collect acceptance/rejection feedback,
- tune prompts and weights from feedback.

## Open Decisions

1. Should big calls optimize for fast content wins, product bets, or balanced portfolio by default?
2. Should SaaS ideas target solo-creator tools first or SMB workflows first?
3. How strict should feasibility gating be for app/SaaS concepts in early runs?
4. Should one run output one primary strategic lane, or multiple independent lanes?

## Deliverable of This Plan

After implementation, the LLM output should no longer be "nice-to-have text." It should become a structured decision artifact that directly feeds Idea Factory with prioritized, grouped, and execution-ready video/app/SaaS opportunities.
