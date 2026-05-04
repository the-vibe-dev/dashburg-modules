from __future__ import annotations

import asyncio
import json
import re
import time
from collections import defaultdict
from collections.abc import Callable

import httpx

from trend_harvester.config import Settings
from trend_harvester.services.channels import get_channel_profiles, get_channel_records, get_channels
from trend_harvester.services.focus import channel_profile_similarity, focus_relevance_score

CHANNELS = get_channels()


class LLMAnalyzer:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.channel_records = get_channel_records()
        self.channels = get_channels()
        self.channel_profiles = get_channel_profiles()
        self._endpoint_lock = None
        self._endpoint_inflight: dict[str, int] = defaultdict(int)
        self._endpoints = self._build_endpoints()

    def _build_endpoints(self) -> list[str]:
        raw = self.settings.ollama_base_urls.strip()
        if not raw:
            return [self.settings.ollama_base_url.rstrip("/")]
        endpoints = [x.strip().rstrip("/") for x in raw.split(",") if x.strip()]
        if not endpoints:
            endpoints = [self.settings.ollama_base_url.rstrip("/")]
        return list(dict.fromkeys(endpoints))

    @property
    def endpoints(self) -> list[str]:
        return list(self._endpoints)

    @property
    def endpoint_count(self) -> int:
        return max(1, len(self._endpoints))

    async def _choose_endpoint(self) -> str:
        if self._endpoint_lock is None:
            import asyncio

            self._endpoint_lock = asyncio.Lock()
        async with self._endpoint_lock:
            for endpoint in self._endpoints:
                self._endpoint_inflight.setdefault(endpoint, 0)
            chosen = min(self._endpoints, key=lambda ep: self._endpoint_inflight.get(ep, 0))
            self._endpoint_inflight[chosen] += 1
            return chosen

    async def _release_endpoint(self, endpoint: str) -> None:
        if self._endpoint_lock is None:
            return
        async with self._endpoint_lock:
            self._endpoint_inflight[endpoint] = max(0, self._endpoint_inflight.get(endpoint, 0) - 1)

    async def analyze_topic(
        self,
        title: str,
        signals: dict,
        *,
        run_id: str | None = None,
        progress_cb: Callable[[dict], None] | None = None,
    ) -> dict:
        prompt = self._build_prompt(title, signals)
        result = await self._request_with_retries(
            call_kind="analyze_topic",
            run_id=run_id,
            progress_cb=progress_cb,
            system_prompt=(
                "Return strict JSON only. No markdown. No chain-of-thought. "
                "summary must be <=2 short sentences. hooks must be 2-3 short lines."
            ),
            user_prompt=prompt,
            temperature=max(0.0, min(1.0, float(self.settings.llm_analyze_temperature))),
            num_ctx=max(2048, int(self.settings.llm_analyze_num_ctx)),
            num_predict=max(500, int(self.settings.llm_analyze_num_predict)),
        )
        return self._sanitize(result, title=title)

    async def structured_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.2,
        num_ctx: int = 4096,
        num_predict: int = 420,
        run_id: str | None = None,
        call_kind: str = "structured_json",
        progress_cb: Callable[[dict], None] | None = None,
    ) -> dict:
        return await self._request_with_retries(
            call_kind=call_kind,
            run_id=run_id,
            progress_cb=progress_cb,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=temperature,
            num_ctx=num_ctx,
            num_predict=num_predict,
        )

    async def _chat_json(
        self,
        *,
        run_id: str | None,
        call_kind: str,
        logical_attempt: int,
        progress_cb: Callable[[dict], None] | None,
        system_prompt: str,
        user_prompt: str,
        temperature: float,
        num_ctx: int,
        num_predict: int,
    ) -> dict:
        if bool(self.settings.redis_broker_enabled):
            return await self._chat_json_via_redis(
                run_id=run_id,
                call_kind=call_kind,
                logical_attempt=logical_attempt,
                progress_cb=progress_cb,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                temperature=temperature,
                num_ctx=num_ctx,
                num_predict=num_predict,
            )

        primary = await self._choose_endpoint()
        candidates = [primary, *[ep for ep in self._endpoints if ep != primary]]
        payload = {
            "model": self.settings.ollama_model,
            "stream": False,
            # Qwen-family models may consume all tokens in internal reasoning, leaving empty content.
            # Force answer mode so `message.content` contains the JSON payload we need.
            "think": False,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "format": "json",
            "options": {
                "temperature": max(0.0, min(1.0, float(temperature))),
                "num_ctx": max(1024, min(8192, int(num_ctx))),
                "num_predict": max(60, min(4000, int(num_predict))),
            },
        }
        try:
            effective_timeout = max(180.0, float(self.settings.llm_timeout_seconds))
            async with httpx.AsyncClient(timeout=effective_timeout) as client:
                last_exc: Exception | None = None
                for endpoint_attempt, base_url in enumerate(candidates, start=1):
                    self._emit_progress(
                        progress_cb,
                        {
                            "event": "http_attempt_started",
                            "run_id": run_id,
                            "call_kind": call_kind,
                            "logical_attempt": logical_attempt,
                            "endpoint_attempt": endpoint_attempt,
                            "endpoint": base_url,
                        },
                    )
                    try:
                        response = await client.post(f"{base_url}/api/chat", json=payload)
                        response.raise_for_status()
                        data = response.json()
                        parsed = self._parse_response_json(data)
                        self._emit_progress(
                            progress_cb,
                            {
                                "event": "http_attempt_succeeded",
                                "run_id": run_id,
                                "call_kind": call_kind,
                                "logical_attempt": logical_attempt,
                                "endpoint_attempt": endpoint_attempt,
                                "endpoint": base_url,
                                "status_code": response.status_code,
                                "stats": {
                                    "total_duration": data.get("total_duration"),
                                    "load_duration": data.get("load_duration"),
                                    "prompt_eval_count": data.get("prompt_eval_count"),
                                    "prompt_eval_duration": data.get("prompt_eval_duration"),
                                    "eval_count": data.get("eval_count"),
                                    "eval_duration": data.get("eval_duration"),
                                },
                            },
                        )
                        return parsed
                    except Exception as exc:  # noqa: BLE001
                        last_exc = exc
                        self._emit_progress(
                            progress_cb,
                            {
                                "event": "http_attempt_failed",
                                "run_id": run_id,
                                "call_kind": call_kind,
                                "logical_attempt": logical_attempt,
                                "endpoint_attempt": endpoint_attempt,
                                "endpoint": base_url,
                                "error": str(exc)[:320],
                            },
                        )
                if last_exc is not None:
                    raise last_exc
                raise RuntimeError("No Ollama endpoints available")
        finally:
            await self._release_endpoint(primary)

    async def _chat_json_via_redis(
        self,
        *,
        run_id: str | None,
        call_kind: str,
        logical_attempt: int,
        progress_cb: Callable[[dict], None] | None,
        system_prompt: str,
        user_prompt: str,
        temperature: float,
        num_ctx: int,
        num_predict: int,
    ) -> dict:
            base = self.settings.redis_broker_base_url.rstrip("/")
            jobs_path = self.settings.redis_llm_jobs_path.strip() or "/llm/jobs"
            if not jobs_path.startswith("/"):
                jobs_path = f"/{jobs_path}"
            payload = {
                "model": self.settings.ollama_model,
                "stream": False,
                "think": False,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "format": "json",
                "options": {
                    "temperature": max(0.0, min(1.0, float(temperature))),
                    "num_ctx": max(1024, min(8192, int(num_ctx))),
                    "num_predict": max(60, min(4000, int(num_predict))),
                },
            }
            submit = {
                "source_repo": "trendsresearcher",
                "tenant_tag": "default",
                "idempotency_key": f"trends-llm-{int(time.time() * 1000)}",
                "priority": 100,
                "payload": payload,
            }
            timeout = max(60.0, float(self.settings.llm_timeout_seconds))
            redis_attempts = 2
            for endpoint_attempt in range(1, redis_attempts + 1):
                self._emit_progress(
                    progress_cb,
                    {
                        "event": "http_attempt_started",
                        "run_id": run_id,
                        "call_kind": call_kind,
                        "logical_attempt": logical_attempt,
                        "endpoint_attempt": endpoint_attempt,
                        "endpoint": f"{base}{jobs_path}",
                    },
                )
                async with httpx.AsyncClient(timeout=timeout) as client:
                    resp = await client.post(f"{base}{jobs_path}", json=submit)
                    resp.raise_for_status()
                    accepted = resp.json() if resp.content else {}
                    job_id = str(accepted.get("job_id") or "").strip()
                    if not job_id:
                        raise RuntimeError(f"redis submit missing job_id: {accepted}")

                    deadline = time.time() + max(1.0, float(self.settings.redis_broker_timeout_s))
                    last_state = "queued"
                    while time.time() < deadline:
                        status_resp = await client.get(f"{base}/jobs/{job_id}")
                        status_resp.raise_for_status()
                        status = status_resp.json() if status_resp.content else {}
                        state = str(status.get("state") or "").strip().lower()
                        if state:
                            last_state = state
                        if state == "done":
                            break
                        if state in {"failed", "canceled"}:
                            raise RuntimeError(f"redis job failed id={job_id} state={state}: {status.get('error_details')}")
                        await asyncio.sleep(max(0.2, float(self.settings.redis_broker_poll_s)))
                    else:
                        raise RuntimeError(f"redis timeout id={job_id} last_state={last_state}")

                    result_resp = await client.get(f"{base}/jobs/{job_id}/result")
                    result_resp.raise_for_status()
                    result = result_resp.json() if result_resp.content else {}
                    body = result.get("result_payload") if isinstance(result, dict) else None
                    if not isinstance(body, dict):
                        body = result if isinstance(result, dict) else {}

                try:
                    if any(
                        key in body
                        for key in ("summary", "hooks", "channel_relevance", "overall_score", "focus_relevance", "channel_fit")
                    ):
                        parsed = body
                    else:
                        parsed = self._parse_response_json(body)
                    break
                except Exception as exc:
                    done_reason = str(body.get("done_reason") or "").strip().lower()
                    response_text = str(body.get("response") or "").strip()
                    if endpoint_attempt < redis_attempts and (done_reason == "load" or response_text == ""):
                        await asyncio.sleep(1.0)
                        continue
                    raise RuntimeError(f"redis result parse failed: {exc}") from exc

            self._emit_progress(
                progress_cb,
                {
                    "event": "http_attempt_succeeded",
                    "run_id": run_id,
                    "call_kind": call_kind,
                    "logical_attempt": logical_attempt,
                    "endpoint_attempt": 1,
                    "endpoint": f"{base}{jobs_path}",
                    "status_code": 200,
                    "stats": {
                        "provider": "redis_broker",
                    },
                },
            )
            return parsed

    @classmethod
    def _parse_response_json(cls, data: dict) -> dict:
        content = ""
        message = data.get("message")
        if isinstance(message, dict):
            maybe_content = message.get("content", "")
            if isinstance(maybe_content, str):
                content = maybe_content
            elif isinstance(maybe_content, dict):
                return maybe_content

        if not content:
            fallback_response = data.get("response")
            if isinstance(fallback_response, str):
                content = fallback_response
            elif isinstance(fallback_response, dict):
                return fallback_response

        return cls._parse_json_object_from_text(content)

    @staticmethod
    def _parse_json_object_from_text(text: str) -> dict:
        if not isinstance(text, str):
            raise ValueError("Ollama response content is not text")
        stripped = text.strip()
        if not stripped:
            raise ValueError("Ollama response content is empty")

        try:
            loaded = json.loads(stripped)
            if isinstance(loaded, dict):
                return loaded
        except Exception:
            pass

        # Many local models prepend reasoning or prose. Try common wrappers.
        no_think = re.sub(r"<think>.*?</think>", "", stripped, flags=re.DOTALL | re.IGNORECASE).strip()
        fence_matches = re.findall(r"```(?:json)?\s*(.*?)\s*```", no_think, flags=re.DOTALL | re.IGNORECASE)
        for chunk in [no_think, *fence_matches, *_extract_json_like_chunks(no_think)]:
            candidate = chunk.strip()
            if not candidate:
                continue
            try:
                loaded = json.loads(candidate)
                if isinstance(loaded, dict):
                    return loaded
            except Exception:
                continue

        preview = stripped[:180].replace("\n", "\\n")
        raise ValueError(f"No JSON object found in Ollama response content: {preview}")

    async def _request_with_retries(
        self,
        *,
        call_kind: str,
        run_id: str | None,
        progress_cb: Callable[[dict], None] | None,
        system_prompt: str,
        user_prompt: str,
        temperature: float,
        num_ctx: int,
        num_predict: int,
    ) -> dict:
        self._emit_progress(progress_cb, {"event": "logical_call_started", "run_id": run_id, "call_kind": call_kind})
        retries = max(1, int(self.settings.retries))
        for attempt in range(1, retries + 1):
            try:
                result = await self._chat_json(
                    run_id=run_id,
                    call_kind=call_kind,
                    logical_attempt=attempt,
                    progress_cb=progress_cb,
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    temperature=temperature,
                    num_ctx=num_ctx,
                    num_predict=num_predict,
                )
                self._emit_progress(
                    progress_cb,
                    {
                        "event": "logical_call_completed",
                        "run_id": run_id,
                        "call_kind": call_kind,
                        "logical_attempt": attempt,
                    },
                )
                return result
            except Exception as exc:
                if attempt >= retries:
                    self._emit_progress(
                        progress_cb,
                        {
                            "event": "logical_call_failed",
                            "run_id": run_id,
                            "call_kind": call_kind,
                            "logical_attempt": attempt,
                            "error": str(exc)[:320],
                        },
                    )
                    raise
                self._emit_progress(
                    progress_cb,
                    {
                        "event": "logical_call_retry",
                        "run_id": run_id,
                        "call_kind": call_kind,
                        "logical_attempt": attempt,
                        "error": str(exc)[:320],
                    },
                )
                await asyncio.sleep(max(0.0, float(self.settings.backoff_base_seconds)) * (2 ** (attempt - 1)))
        raise RuntimeError("unreachable")

    async def grade_topic_focus(
        self,
        *,
        title: str,
        summary: str,
        signals: dict,
        focus_query: str,
        objective: str,
        channel_relevance: dict[str, float] | None = None,
        run_id: str | None = None,
        progress_cb: Callable[[dict], None] | None = None,
    ) -> dict:
        compact_signals = json.dumps(signals, ensure_ascii=True, separators=(",", ":"))
        channel_profiles_txt = "; ".join(
            f"{record.display_name}: {self.channel_profiles.get(record.display_name, '')[:120]} | queries={','.join(record.query_terms[:3])}"
            for record in self.channel_records
        )
        existing_relevance = channel_relevance if isinstance(channel_relevance, dict) else {}
        prompt = (
            "Grade this trend for practical content production. "
            "Return strict JSON with keys: overall_score (0..1), focus_relevance (0..1), "
            "actionability_video (0..1), actionability_blog (0..1), actionability_app (0..1), "
            f"channel_fit (object with numeric 0..1 values for channels {self.channels}), "
            "reason (max 1 short sentence). "
            f"Focus query: {focus_query[:200]}\n"
            f"Objective: {objective[:120]}\n"
            f"Topic: {title[:220]}\n"
            f"Summary: {summary[:280]}\n"
            f"Existing channel relevance: {json.dumps(existing_relevance, ensure_ascii=True, separators=(',', ':'))}\n"
            f"Topic signals: {compact_signals}\n"
            f"Channel profiles: {channel_profiles_txt[:1800]}"
        )

        raw = await self._request_with_retries(
            call_kind="grade_topic_focus",
            run_id=run_id,
            progress_cb=progress_cb,
            system_prompt="Return strict JSON only. No markdown. No chain-of-thought.",
            user_prompt=prompt,
            temperature=0.1,
            num_ctx=4096,
            num_predict=min(220, max(80, self.settings.llm_num_predict)),
        )
        return self._sanitize_focus_grade(raw, title=title, focus_query=focus_query)

    @staticmethod
    def _emit_progress(progress_cb: Callable[[dict], None] | None, payload: dict) -> None:
        if progress_cb is None:
            return
        try:
            progress_cb(payload)
        except Exception:
            return

    def _sanitize(self, data: dict, *, title: str) -> dict:
        summary = str(data.get("summary", "")).strip()[:400]
        hooks = data.get("hooks", [])
        if not isinstance(hooks, list):
            hooks = []
        hooks = [str(h).strip()[:120] for h in hooks[:3] if str(h).strip()]

        relevance = data.get("channel_relevance", {})
        if not isinstance(relevance, dict):
            relevance = {}

        safe_relevance = {}
        for channel in self.channels:
            val = relevance.get(channel, 0.0)
            try:
                safe_relevance[channel] = max(0.0, min(float(val), 1.0))
            except (TypeError, ValueError):
                safe_relevance[channel] = 0.0
        if max(safe_relevance.values(), default=0.0) <= 0.01:
            safe_relevance = self._heuristic_channel_relevance(title)

        return {
            "summary": summary,
            "hooks": hooks,
            "channel_relevance": safe_relevance,
        }

    def _sanitize_focus_grade(self, data: dict, *, title: str, focus_query: str) -> dict:
        def _f(key: str, default: float = 0.0) -> float:
            try:
                return max(0.0, min(1.0, float(data.get(key, default))))
            except (TypeError, ValueError):
                return default

        raw_channel_fit = data.get("channel_fit", {})
        if not isinstance(raw_channel_fit, dict):
            raw_channel_fit = {}
        channel_fit = {}
        for channel in self.channels:
            try:
                channel_fit[channel] = max(0.0, min(1.0, float(raw_channel_fit.get(channel, 0.0))))
            except (TypeError, ValueError):
                channel_fit[channel] = 0.0
        if max(channel_fit.values(), default=0.0) <= 0.01:
            channel_fit = self._heuristic_channel_relevance(title)

        actionability_video = _f("actionability_video")
        actionability_blog = _f("actionability_blog")
        actionability_app = _f("actionability_app")
        model_overall = _f("overall_score")
        model_focus = _f("focus_relevance")
        heuristic_focus = float(focus_relevance_score(title, focus_query))
        focus_relevance = max(model_focus, heuristic_focus)
        actionability_avg = (actionability_video + actionability_blog + actionability_app) / 3
        overall_score = max(model_overall, (focus_relevance * 0.55) + (actionability_avg * 0.45))
        return {
            "overall_score": round(max(0.0, min(1.0, overall_score)), 4),
            "focus_relevance": round(max(0.0, min(1.0, focus_relevance)), 4),
            "actionability_video": round(actionability_video, 4),
            "actionability_blog": round(actionability_blog, 4),
            "actionability_app": round(actionability_app, 4),
            "channel_fit": channel_fit,
            "reason": str(data.get("reason", "")).strip()[:220],
        }

    def _heuristic_channel_relevance(self, title: str) -> dict[str, float]:
        scores: dict[str, float] = {}
        for channel in self.channels:
            profile = self.channel_profiles.get(channel, "")
            scores[channel] = max(0.0, min(1.0, channel_profile_similarity(title, profile)))
        return scores

    def _build_prompt(self, title: str, signals: dict) -> str:
        source_groups = signals.get("source_groups", [])
        compact_signals = json.dumps(
            {
                "source_count": signals.get("source_count"),
                "source_scores": signals.get("source_scores"),
                "source_counts": signals.get("source_counts"),
                "avg_instance_score": signals.get("avg_instance_score"),
                "max_instance_score": signals.get("max_instance_score"),
                "metric_highlights": signals.get("metric_highlights"),
                "source_groups": source_groups[:8] if isinstance(source_groups, list) else [],
            },
            ensure_ascii=True,
            separators=(",", ":"),
        )
        channel_profiles_txt = "; ".join(
            f"{record.display_name}: {self.channel_profiles.get(record.display_name, '')[:110]} | queries={','.join(record.query_terms[:3])}"
            for record in self.channel_records
        )
        return (
            "Analyze one trend topic for short-form content strategy. "
            "Return JSON object with keys: summary (1-2 sentences), "
            "channel_relevance (object with numeric 0..1 values for channels "
            f"{self.channels}), hooks (2-3 short hook ideas). Use channel profile descriptions to classify fit. "
            "Only return all-zero channel scores when topic is clearly irrelevant to every channel. "
            f"Topic: {title[:220]}\n"
            f"Grouped signals:{compact_signals[:3000]}\n"
            f"Channel profiles: {channel_profiles_txt[:2200]}"
        )


def _extract_json_like_chunks(text: str) -> list[str]:
    chunks: list[str] = []
    in_string = False
    escape = False
    stack: list[str] = []
    start_idx: int | None = None
    closing_for = {"{": "}", "[": "]"}

    for idx, char in enumerate(text):
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue

        if char == '"':
            in_string = True
            continue

        if char in "{[":
            if not stack:
                start_idx = idx
            stack.append(closing_for[char])
            continue

        if char in "}]":
            if not stack:
                continue
            expected = stack[-1]
            if char != expected:
                # reset on malformed bracket sequence
                stack = []
                start_idx = None
                continue
            stack.pop()
            if not stack and start_idx is not None:
                chunks.append(text[start_idx : idx + 1])
                start_idx = None
    return chunks
