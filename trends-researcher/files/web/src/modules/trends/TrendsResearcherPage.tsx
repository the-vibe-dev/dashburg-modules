import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import {
  AtSign,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  Circle,
  ExternalLink,
  Flame,
  Info,
  Loader2,
  Play,
  RefreshCw,
  Search,
  Trash2,
  Youtube,
} from "lucide-react";

import {
  useStartTrendsRun,
  useCreateIdeaVaultItem,
  useDeleteTrendsRun,
  useCancelTrendsRun,
  useNudgeTrendsRun,
  useTrendTopicAction,
  useTrendsExport,
  useTrendsImportTopicFactory,
  useEnqueueTopicFactory,
  useTrendsRun,
  useTrendsRunLogs,
  useTrendsRunResults,
  useTrendsRuns,
  useTrendsTopicDetail,
  useTrendsOpenAiKeyStatus,
  useSetTrendsOpenAiKey,
  useTransformSignalToOpportunities,
} from "../../shared/api/hooks";
import type {
  TrendsRun,
  TrendsRunStartRequest,
  TrendsTopicAction,
  TrendsTopicResult,
} from "../../shared/api/types";
import { Button } from "../../shared/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "../../shared/components/ui/card";
import { Input, Textarea } from "../../shared/components/ui/input";
import { PageHeader } from "../../shared/components/ui/page-header";
import { AdvancedRawJson, ObjectReadout } from "../../shared/components/ui/readouts";
import { useStreamingMode } from "../../app/useStreamingMode";
import { withStreamingObfuscation } from "../../app/streamingObfuscation";

type RunSize = "small" | "medium" | "large";
type SourceKey = "youtube" | "trends" | "reddit" | "x_trends";
const FOCUS_QUERY_STORAGE_KEY = "dashburg.trends.focusQuery";
const TRENDS_MODE_STORAGE_KEY = "dashburg.trends.mode";
const DEFAULT_OBJECTIVE = "video_blog_app_ideas";
const DEFAULT_LLM_RERANK_TOP_N = 50;
const DEFAULT_MIN_FOCUS_RELEVANCE = 0.2;
const EPL_SUBREDDITS = ["soccer", "PremierLeague", "FantasyPL", "footballhighlights"];
type TrendsMode = "top" | "focused";
type NormalizedTrendChannel = {
  channel_id: string;
  channel_name: string;
  relevance_pct: number;
  why?: string;
};

const CATEGORY_OPTIONS = [
  "Film & Animation",
  "Autos & Vehicles",
  "Music",
  "Pets & Animals",
  "Sports",
  "Travel & Events",
  "Gaming",
  "People & Blogs",
  "Comedy",
  "Entertainment",
  "News & Politics",
  "Howto & Style",
  "Education",
  "Science & Technology",
  "Nonprofits & Activism",
];
const SUBREDDIT_OPTIONS = ["technology", "worldnews", "todayilearned", "science", "gaming", "movies", "sports", "futurology"];

const DEFAULT_SETTINGS: TrendsRunStartRequest = {
  sources: {
    youtube: { enabled: true, limit: 200 },
    trends: { enabled: true, limit: 60 },
    reddit: { enabled: true, limit: 200 },
    x_trends: { enabled: false, limit: 20 },
  },
  limits: {
    size: "large",
    youtube: 200,
    reddit: 200,
    trends: 60,
    x_trends: 20,
  },
  sources_config: {
    x_trends: {
      enabled: false,
      max_items: 20,
      use_auth: false,
    },
  },
  categories: ["News & Politics", "Entertainment", "Sports", "Gaming", "Science & Technology"],
  subreddits: ["technology", "worldnews", "science", "gaming", "sports", "movies"],
  region: "US",
  query: "",
  objective: DEFAULT_OBJECTIVE,
  use_openai_strategy: true,
  llm_rerank_top_n: DEFAULT_LLM_RERANK_TOP_N,
  min_focus_relevance: DEFAULT_MIN_FOCUS_RELEVANCE,
};

const ACTIONS: TrendsTopicAction[] = ["like", "maybe", "skip", "used", "blacklist"];

function sourceIcon(source: string) {
  const normalized = source.toLowerCase();
  if (normalized === "x" || normalized.includes("x_trends") || normalized === "twitter") return <AtSign size={12} className="text-sky-400" />;
  if (normalized.includes("youtube")) return <Youtube size={12} className="text-danger" />;
  if (normalized.includes("trend")) return <Flame size={12} className="text-warning" />;
  if (normalized.includes("reddit")) return <Circle size={10} className="text-orange-500 fill-orange-500" />;
  return <Search size={12} className="text-muted-foreground" />;
}

function sourceLabel(source: SourceKey | string) {
  if (source === "trends") return "google_trends";
  if (source === "x_trends") return "x_trends";
  return source;
}

function relativeTime(ts: string | null) {
  if (!ts) return "-";
  const normalized = /([zZ]|[+\-]\d{2}:\d{2})$/.test(ts) ? ts : `${ts}Z`;
  const date = new Date(normalized);
  if (Number.isNaN(date.getTime())) return ts;
  const diffSec = Math.max(0, Math.floor((Date.now() - date.getTime()) / 1000));
  if (diffSec < 60) return `${diffSec}s ago`;
  if (diffSec < 3600) return `${Math.floor(diffSec / 60)}m ago`;
  if (diffSec < 86400) return `${Math.floor(diffSec / 3600)}h ago`;
  return `${Math.floor(diffSec / 86400)}d ago`;
}

function ageSeconds(ts: string | null): number | null {
  if (!ts) return null;
  const normalized = /([zZ]|[+\-]\d{2}:\d{2})$/.test(ts) ? ts : `${ts}Z`;
  const date = new Date(normalized);
  if (Number.isNaN(date.getTime())) return null;
  return Math.max(0, Math.floor((Date.now() - date.getTime()) / 1000));
}

function parseRuns(input: unknown): TrendsRun[] {
  if (Array.isArray(input)) return input as TrendsRun[];
  return [];
}

function statusTone(status: string): "warning" | "success" | "danger" | "outline" {
  const normalized = status.toUpperCase();
  if (normalized === "RUNNING" || normalized === "QUEUED") return "warning";
  if (normalized === "SUCCEEDED") return "success";
  if (normalized === "FAILED") return "danger";
  return "outline";
}

function stageIndex(status: string): number {
  const normalized = status.toUpperCase();
  if (normalized === "QUEUED") return 0;
  if (normalized === "RUNNING") return 1;
  if (normalized === "SUCCEEDED") return 2;
  if (normalized === "FAILED") return 3;
  return 0;
}

function canDeleteRun(status: string): boolean {
  const normalized = String(status).toUpperCase();
  return normalized !== "RUNNING";
}

function clampInt(value: number, min: number, max: number): number {
  if (!Number.isFinite(value)) return min;
  return Math.max(min, Math.min(max, Math.round(value)));
}

function clampFloat(value: number, min: number, max: number): number {
  if (!Number.isFinite(value)) return min;
  return Math.max(min, Math.min(max, value));
}

function isEplIntent(query: string): boolean {
  return /(?:\bepl\b|english premier league|premier league|football league)/i.test(query);
}

function normalizeSubreddits(items: string[]): string[] {
  const dedup = new Set<string>();
  for (const item of items) {
    const cleaned = item.trim().replace(/^r\//i, "");
    if (!cleaned) continue;
    dedup.add(cleaned);
    if (dedup.size >= 20) break;
  }
  return Array.from(dedup);
}

function normalizePct(value: unknown): number | null {
  if (typeof value !== "number" || !Number.isFinite(value)) return null;
  const pct = value <= 1 ? value * 100 : value;
  if (!Number.isFinite(pct)) return null;
  return Math.max(0, Math.min(100, pct));
}

function pickChannelWhy(entry: Record<string, unknown>): string | undefined {
  const direct = [
    entry.why,
    entry.reason,
    entry.reason_code,
    entry.debug_reason,
    entry.match_reason,
  ].find((value) => typeof value === "string" && value.trim());
  if (typeof direct === "string" && direct.trim()) return direct.trim();

  const overlap = entry.overlap_terms;
  if (Array.isArray(overlap)) {
    const terms = overlap.map((value) => String(value).trim()).filter(Boolean).slice(0, 6);
    if (terms.length > 0) return `Overlap: ${terms.join(", ")}`;
  }
  return undefined;
}

function normalizeTrendChannels(topic: Record<string, unknown> | null | undefined): NormalizedTrendChannel[] {
  if (!topic || typeof topic !== "object") return [];

  const normalized: NormalizedTrendChannel[] = [];
  const pushChannel = (
    channelId: string,
    channelName: string,
    relevanceRaw: unknown,
    why?: string,
  ) => {
    const relevance = normalizePct(relevanceRaw);
    if (relevance === null || relevance <= 0) return;
    normalized.push({
      channel_id: channelId || channelName.toLowerCase().replace(/\s+/g, "_"),
      channel_name: channelName || channelId,
      relevance_pct: relevance,
      ...(why ? { why } : {}),
    });
  };

  const rankings = topic.channel_rankings;
  if (Array.isArray(rankings)) {
    for (const item of rankings) {
      if (!item || typeof item !== "object") continue;
      const row = item as Record<string, unknown>;
      const channelId = String(row.channel_id ?? row.id ?? row.channel ?? row.channel_key ?? "").trim();
      const channelName = String(row.channel_name ?? row.name ?? row.channel_label ?? channelId).trim();
      const relevance =
        row.relevance_pct ??
        row.relevancePercent ??
        row.relevance ??
        row.match_pct ??
        row.percent ??
        row.score;
      pushChannel(channelId, channelName, relevance, pickChannelWhy(row));
    }
  }

  if (normalized.length === 0) {
    const legacy = topic.channels;
    if (legacy && typeof legacy === "object" && !Array.isArray(legacy)) {
      for (const [channelName, relevance] of Object.entries(legacy as Record<string, unknown>)) {
        pushChannel(channelName, channelName, relevance);
      }
    }
  }

  normalized.sort((a, b) => b.relevance_pct - a.relevance_pct || a.channel_name.localeCompare(b.channel_name));
  return normalized.slice(0, 4);
}

export function TrendsResearcherPage() {
  const { streamingMode } = useStreamingMode();
  const displayChannelRef = (value: string) => withStreamingObfuscation(value, streamingMode, "channel");
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [selectedTopicId, setSelectedTopicId] = useState<string | null>(null);
  const [selectedTopicIds, setSelectedTopicIds] = useState<Set<string>>(new Set());
  const [settings, setSettings] = useState<TrendsRunStartRequest>(DEFAULT_SETTINGS);
  const [runMode, setRunMode] = useState<TrendsMode>("top");
  const [activeSection, setActiveSection] = useState<"bigcalls" | "ideas" | "groups" | "overall" | "sources" | "channels" | "actions">("bigcalls");
  const [toast, setToast] = useState<string | null>(null);
  const [noteDraft, setNoteDraft] = useState<Record<string, string>>({});
  const [actionState, setActionState] = useState<Record<string, { action: TrendsTopicAction; note?: string }>>({});
  const [createdLinks, setCreatedLinks] = useState<string[]>([]);
  const [newSubreddit, setNewSubreddit] = useState("");
  const [showFullRunOutput, setShowFullRunOutput] = useState(false);
  const [showOpenAiKeyModal, setShowOpenAiKeyModal] = useState(false);
  const [openAiKeyInput, setOpenAiKeyInput] = useState("");
  const [pendingStartPayload, setPendingStartPayload] = useState<TrendsRunStartRequest | null>(null);

  const runsQuery = useTrendsRuns();
  const startRun = useStartTrendsRun();
  const createIdeaVault = useCreateIdeaVaultItem();
  const deleteRun = useDeleteTrendsRun();
  const cancelRunMutation = useCancelTrendsRun();
  const nudgeRunMutation = useNudgeTrendsRun();
  const actionMutation = useTrendTopicAction();
  const exportMutation = useTrendsExport();
  const importMutation = useTrendsImportTopicFactory();
  const enqueueTopicFactory = useEnqueueTopicFactory();
  const trendsOpenAiKeyStatus = useTrendsOpenAiKeyStatus(true);
  const setTrendsOpenAiKey = useSetTrendsOpenAiKey();
  const transformSignal = useTransformSignalToOpportunities();

  const runs = useMemo(() => {
    const list = parseRuns(runsQuery.data);
    return list.sort((a, b) => {
      const at = new Date(String(a.started_at ?? "")).getTime() || 0;
      const bt = new Date(String(b.started_at ?? "")).getTime() || 0;
      return bt - at;
    });
  }, [runsQuery.data]);
  const focusQuery = String(settings.query ?? "").trim();
  const settingsValidationError = useMemo(() => {
    if (runMode === "focused" && focusQuery) {
      const llmTopN = Number(settings.llm_rerank_top_n ?? DEFAULT_LLM_RERANK_TOP_N);
      if (!Number.isFinite(llmTopN) || llmTopN < 0 || llmTopN > 100) return "LLM rerank top N must be between 0 and 100.";
      const minRel = Number(settings.min_focus_relevance ?? DEFAULT_MIN_FOCUS_RELEVANCE);
      if (!Number.isFinite(minRel) || minRel < 0 || minRel > 1) return "Min focus relevance must be between 0 and 1.";
    }
    if ((settings.subreddits ?? []).length > 20) return "Maximum 20 subreddits allowed.";
    return null;
  }, [runMode, focusQuery, settings.llm_rerank_top_n, settings.min_focus_relevance, settings.subreddits]);

  useEffect(() => {
    if (runs.length === 0) return;
    const selectedExists = Boolean(selectedRunId && runs.some((run) => run.id === selectedRunId));
    if (!selectedExists) {
      setSelectedRunId(runs[0].id);
      setSelectedTopicId(null);
    }
  }, [runs, selectedRunId]);

  useEffect(() => {
    try {
      const saved = window.sessionStorage.getItem(FOCUS_QUERY_STORAGE_KEY);
      if (saved && !String(settings.query ?? "").trim()) {
        setSettings((prev) => ({ ...prev, query: saved }));
      }
      const savedMode = window.sessionStorage.getItem(TRENDS_MODE_STORAGE_KEY);
      if (savedMode === "top" || savedMode === "focused") setRunMode(savedMode);
    } catch {
      // no-op
    }
  }, []);

  useEffect(() => {
    try {
      const current = String(settings.query ?? "").trim();
      if (current) window.sessionStorage.setItem(FOCUS_QUERY_STORAGE_KEY, current);
      else window.sessionStorage.removeItem(FOCUS_QUERY_STORAGE_KEY);
      window.sessionStorage.setItem(TRENDS_MODE_STORAGE_KEY, runMode);
    } catch {
      // no-op
    }
  }, [settings.query, runMode]);

  const selectedRun = useMemo(() => runs.find((run) => run.id === selectedRunId) ?? null, [runs, selectedRunId]);
  const isRunActive = Boolean(selectedRun && ["QUEUED", "RUNNING"].includes(String(selectedRun.status).toUpperCase()));

  const runStatusQuery = useTrendsRun(selectedRunId, isRunActive);
  const runLogsQuery = useTrendsRunLogs(selectedRunId, 140, Boolean(selectedRunId));
  const effectiveRunStatus = runStatusQuery.data?.status ?? selectedRun?.status ?? "QUEUED";
  const runTotals = (runStatusQuery.data?.totals_json ?? selectedRun?.totals_json ?? {}) as Record<string, unknown>;
  const liveStage = String(runTotals.stage ?? (effectiveRunStatus === "RUNNING" ? "running" : "")).trim();
  const progressPctRaw = Number(runTotals.progress_pct ?? 0);
  const liveProgressPct = Number.isFinite(progressPctRaw) ? Math.max(0, Math.min(100, progressPctRaw)) : 0;
  const heartbeatAt = runTotals.heartbeat_at ? String(runTotals.heartbeat_at) : null;
  const sourceCounts = (runTotals.source_candidate_counts ?? {}) as Record<string, unknown>;
  const keptSourceCounts = (runTotals.kept_candidate_counts ?? {}) as Record<string, unknown>;
  const filteredSourceCounts = (runTotals.filtered_candidate_counts ?? {}) as Record<string, unknown>;
  const sourceWarnings = Array.isArray(runTotals.source_warnings) ? (runTotals.source_warnings as Array<Record<string, unknown> | string>) : [];
  const llmDone = Number(runTotals.llm_done_topics ?? 0);
  const llmTotal = Number(runTotals.llm_total_topics ?? 0);
  const llmCalls = (runTotals.llm_calls ?? {}) as Record<string, unknown>;
  const llmCallsExpected = (llmCalls.expected ?? {}) as Record<string, unknown>;
  const llmCallsActual = (llmCalls.actual ?? {}) as Record<string, unknown>;
  const llmEndpointStats = (llmCalls.endpoint_stats ?? {}) as Record<string, unknown>;
  const llmApiHealth = (llmCalls.api_health ?? {}) as Record<string, unknown>;
  const llmLogicalExpected = Number(llmCallsExpected.total_logical_calls ?? llmTotal ?? 0);
  const llmLogicalCompleted = Number(llmCallsActual.logical_completed ?? llmDone ?? 0);
  const llmLogicalStarted = Number(llmCallsActual.logical_started ?? 0);
  const llmHttpAttemptStarted = Number(llmCallsActual.http_attempt_started ?? 0);
  const llmHttpAttemptSucceeded = Number(llmCallsActual.http_attempt_succeeded ?? 0);
  const llmHttpAttemptFailed = Number(llmCallsActual.http_attempt_failed ?? 0);
  const llmMaxHttpAttempts = Number(llmCallsExpected.max_http_attempts ?? 0);
  const llmRetryCount = Number(llmCallsActual.retries ?? 0);
  const llmEndpointCount = Number(llmCalls.endpoint_count ?? 0);
  const llmLastApiEvent = String(llmApiHealth.last_http_event ?? "").trim();
  const llmLastApiEndpoint = String(llmApiHealth.last_http_endpoint ?? "").trim();
  const llmLastApiError = String(llmApiHealth.last_http_error ?? "").trim();
  const endpointHealthRows = Object.entries(llmEndpointStats)
    .filter((row): row is [string, Record<string, unknown>] => Boolean(row[0]) && Boolean(row[1]) && typeof row[1] === "object")
    .map(([endpoint, stats]) => ({
      endpoint,
      started: Number(stats.started ?? 0),
      succeeded: Number(stats.succeeded ?? 0),
      failed: Number(stats.failed ?? 0),
      lastError: String(stats.last_error ?? "").trim(),
    }));
  const liveEvents = Array.isArray(runTotals.events) ? (runTotals.events as unknown[]).map((e) => String(e)).slice(-12) : [];
  const runLogLines = Array.isArray(runLogsQuery.data?.lines) ? runLogsQuery.data.lines : [];
  const heartbeatAgeSec = ageSeconds(heartbeatAt);
  const heartbeatStale = Boolean(heartbeatAgeSec !== null && heartbeatAgeSec > 120 && isRunActive);
  const progressLabel =
    liveProgressPct > 0
      ? `${Math.round(liveProgressPct)}%`
      : String(effectiveRunStatus).toUpperCase() === "QUEUED"
      ? "Waiting for worker"
      : "In progress";
  const runParams = (runStatusQuery.data?.params_json ?? selectedRun?.params_json ?? {}) as Record<string, unknown>;
  const runQuery = typeof runParams.query === "string" ? runParams.query : "-";
  const runObjective = typeof runParams.objective === "string" ? runParams.objective : "-";
  const runModeLabel = typeof runParams.query === "string" && runParams.query.trim() ? "Focused Trends" : "Top Trends";

  const resultsQuery = useTrendsRunResults(selectedRunId, 25, Boolean(selectedRunId));
  const topicDetailQuery = useTrendsTopicDetail(selectedTopicId);

  useEffect(() => {
    if (runStatusQuery.data?.status !== "MISSING") return;
    if (runs.length === 0) return;
    const fallback = runs.find((run) => run.id !== selectedRunId) ?? runs[0];
    if (fallback && fallback.id !== selectedRunId) {
      setSelectedRunId(fallback.id);
      setSelectedTopicId(null);
      setToast("Selected run is no longer available. Switched to latest run.");
    }
  }, [runStatusQuery.data?.status, runs, selectedRunId]);

  useEffect(() => {
    if (effectiveRunStatus && String(effectiveRunStatus).toUpperCase() === "SUCCEEDED") {
      resultsQuery.refetch();
      runsQuery.refetch();
    }
  }, [effectiveRunStatus]);

  useEffect(() => {
    if (!toast) return;
    const timer = window.setTimeout(() => setToast(null), 2500);
    return () => window.clearTimeout(timer);
  }, [toast]);

  const topOverall = (resultsQuery.data?.top_overall ?? []) as TrendsTopicResult[];
  const byChannel = (resultsQuery.data?.top_per_channel ?? {}) as Record<string, TrendsTopicResult[]>;
  const bySource = (resultsQuery.data?.top_by_source ?? {}) as Record<string, TrendsTopicResult[]>;
  const strategyStatus = (resultsQuery.data?.strategy_status ?? {}) as Record<string, unknown>;
  const strategyState = String(strategyStatus.status ?? "idle").toLowerCase();
  const strategyMode = String(((strategyStatus.artifact as Record<string, unknown> | undefined)?.phase_status as Record<string, unknown> | undefined)?.mode ?? "quick");
  const strategyCurrentPhase = String(strategyStatus.current_phase ?? "").trim();
  const strategyLastError = String(strategyStatus.last_error ?? strategyStatus.error ?? "").trim();
  const strategyQueuedAt = typeof strategyStatus.queued_at === "string" ? strategyStatus.queued_at : null;
  const strategyStartedAt = typeof strategyStatus.started_at === "string" ? strategyStatus.started_at : null;
  const strategyUpdatedAt = typeof strategyStatus.updated_at === "string" ? strategyStatus.updated_at : null;
  const strategyLastTickAt = strategyUpdatedAt || strategyStartedAt || strategyQueuedAt;
  const strategyPhases = (strategyStatus.phases ?? {}) as Record<string, unknown>;
  const strategyEvents = Array.isArray(strategyStatus.events) ? (strategyStatus.events as Array<Record<string, unknown>>) : [];
  const strategyPhaseEntries = Object.values(strategyPhases).filter(
    (value): value is Record<string, unknown> => Boolean(value) && typeof value === "object",
  );
  const strategyPhaseDone = strategyPhaseEntries.filter((phase) => {
    const status = String(phase.status ?? "").toLowerCase();
    return status === "ok" || status === "succeeded" || status === "done";
  }).length;
  const strategyRunning = strategyState === "queued" || strategyState === "running";
  const strategyRunTelemetry = [
    liveStage ? `run stage ${liveStage}` : "",
    `run ${progressLabel.toLowerCase()}`,
    heartbeatAt ? `heartbeat ${relativeTime(heartbeatAt)}` : "",
  ].filter(Boolean);
  const ideaCandidates = useMemo(
    () => (Array.isArray(resultsQuery.data?.idea_candidates) ? (resultsQuery.data?.idea_candidates as Array<Record<string, unknown>>) : []),
    [resultsQuery.data?.idea_candidates],
  );
  const ideaCandidatesByType = useMemo(() => {
    const raw = (resultsQuery.data?.idea_candidates_by_type ?? {}) as Record<string, unknown>;
    const video = Array.isArray(raw.video) ? (raw.video as Array<Record<string, unknown>>) : [];
    const app = Array.isArray(raw.app) ? (raw.app as Array<Record<string, unknown>>) : [];
    const saas = Array.isArray(raw.saas) ? (raw.saas as Array<Record<string, unknown>>) : [];
    if (video.length || app.length || saas.length) return { video, app, saas };
    const grouped = { video: [] as Array<Record<string, unknown>>, app: [] as Array<Record<string, unknown>>, saas: [] as Array<Record<string, unknown>> };
    for (const idea of ideaCandidates) {
      const ideaType = String(idea.idea_type ?? "").toLowerCase();
      if (ideaType in grouped) grouped[ideaType as "video" | "app" | "saas"].push(idea);
    }
    return grouped;
  }, [resultsQuery.data?.idea_candidates_by_type, ideaCandidates]);
  const reviewNotes = useMemo(
    () => (Array.isArray(resultsQuery.data?.review_notes) ? (resultsQuery.data?.review_notes as string[]) : []),
    [resultsQuery.data?.review_notes],
  );
  const ideaGroups = useMemo(
    () => (Array.isArray(resultsQuery.data?.idea_groups) ? (resultsQuery.data?.idea_groups as Array<Record<string, unknown>>) : []),
    [resultsQuery.data?.idea_groups],
  );
  const bigCalls = useMemo(
    () =>
      (Array.isArray(resultsQuery.data?.big_calls) ? (resultsQuery.data?.big_calls as Array<Record<string, unknown>>) : []).sort(
        (a, b) => Number(b.conviction_score ?? 0) - Number(a.conviction_score ?? 0),
      ),
    [resultsQuery.data?.big_calls],
  );
  const scoreBreakdowns = (resultsQuery.data?.score_breakdowns ?? {}) as Record<string, Record<string, unknown>>;

  const sortedTopOverall = useMemo(
    () => [...topOverall].sort((a, b) => Number(b.score ?? 0) - Number(a.score ?? 0)),
    [topOverall],
  );
  const sortedIdeaCandidatesByType = useMemo(() => ({
    video: [...ideaCandidatesByType.video].sort((a, b) => Number(b.confidence ?? 0) - Number(a.confidence ?? 0)),
    app: [...ideaCandidatesByType.app].sort((a, b) => Number(b.confidence ?? 0) - Number(a.confidence ?? 0)),
    saas: [...ideaCandidatesByType.saas].sort((a, b) => Number(b.confidence ?? 0) - Number(a.confidence ?? 0)),
  }), [ideaCandidatesByType]);

  useEffect(() => {
    if (!strategyRunning || !selectedRunId) return;
    const timer = window.setTimeout(() => {
      resultsQuery.refetch();
    }, 8000);
    return () => window.clearTimeout(timer);
  }, [strategyRunning, selectedRunId, resultsQuery.dataUpdatedAt]);
  const allTopicsById = useMemo(() => {
    const map = new Map<string, TrendsTopicResult>();
    for (const topic of topOverall) map.set(topic.topic_id, topic);
    for (const list of Object.values(byChannel)) {
      for (const topic of list ?? []) map.set(topic.topic_id, topic);
    }
    for (const list of Object.values(bySource)) {
      for (const topic of list ?? []) map.set(topic.topic_id, topic);
    }
    return map;
  }, [topOverall, byChannel, bySource]);

  const selectedTopic = useMemo(
    () => topOverall.find((topic) => topic.topic_id === selectedTopicId) ?? null,
    [topOverall, selectedTopicId],
  );
  const selectedTopicChannels = useMemo(
    () => normalizeTrendChannels((topicDetailQuery.data as Record<string, unknown> | undefined) ?? selectedTopic ?? undefined),
    [selectedTopic, topicDetailQuery.data],
  );

  const toggleSelection = (topicId: string) => {
    setSelectedTopicIds((prev) => {
      const next = new Set(prev);
      if (next.has(topicId)) next.delete(topicId);
      else next.add(topicId);
      return next;
    });
  };

  const setRunSize = (size: RunSize) => {
    const limits =
      size === "small"
        ? { youtube: 40, reddit: 40, trends: 20, x_trends: 10 }
        : size === "medium"
        ? { youtube: 80, reddit: 80, trends: 40, x_trends: 20 }
        : { youtube: 120, reddit: 120, trends: 60, x_trends: 30 };

    setSettings((prev) => ({
      ...prev,
      limits: { ...prev.limits, size, ...limits },
      sources: {
        youtube: { ...prev.sources.youtube, limit: limits.youtube },
        reddit: { ...prev.sources.reddit, limit: limits.reddit },
        trends: { ...prev.sources.trends, limit: limits.trends },
        x_trends: { ...(prev.sources.x_trends ?? { enabled: false }), limit: limits.x_trends },
      },
      sources_config: {
        ...(prev.sources_config ?? {}),
        x_trends: {
          ...(prev.sources_config?.x_trends ?? {}),
          max_items: limits.x_trends,
        },
      },
    }));
  };

  const handleSourceToggle = (source: SourceKey) => {
    setSettings((prev) => ({
      ...prev,
      sources: {
        ...prev.sources,
        [source]: {
          ...(prev.sources[source] ?? { enabled: false }),
          enabled: !Boolean(prev.sources[source]?.enabled),
        },
      },
    }));
  };

  const toggleCategory = (cat: string) => {
    setSettings((prev) => {
      const has = prev.categories.includes(cat);
      return {
        ...prev,
        categories: has ? prev.categories.filter((item) => item !== cat) : [...prev.categories, cat],
      };
    });
  };

  const toggleSubreddit = (sub: string) => {
    setSettings((prev) => {
      const has = prev.subreddits.includes(sub);
      return {
        ...prev,
        subreddits: has ? prev.subreddits.filter((item) => item !== sub) : [...prev.subreddits, sub],
      };
    });
  };

  const addCustomSubreddit = () => {
    const raw = newSubreddit.trim().replace(/^r\//i, "");
    if (!raw) return;
    if (settings.subreddits.length >= 20) {
      setToast("Subreddit limit reached (max 20)");
      return;
    }
    toggleSubreddit(raw);
    setNewSubreddit("");
  };

  const buildStartPayload = (): TrendsRunStartRequest => {
    const query = String(settings.query ?? "").trim();
    const objective = String(settings.objective ?? "").trim() || DEFAULT_OBJECTIVE;
    const llm_rerank_top_n = clampInt(Number(settings.llm_rerank_top_n ?? DEFAULT_LLM_RERANK_TOP_N), 0, 100);
    const min_focus_relevance = clampFloat(Number(settings.min_focus_relevance ?? DEFAULT_MIN_FOCUS_RELEVANCE), 0, 1);
    const youtubeLimit = Math.max(0, Number(settings.sources.youtube.limit ?? settings.limits.youtube ?? 200));
    const redditLimit = Math.max(0, Number(settings.sources.reddit.limit ?? settings.limits.reddit ?? 120));
    const trendsLimit = Math.max(0, Number(settings.sources.trends.limit ?? settings.limits.trends ?? 50));
    const xTrendsLimit = Math.max(0, Number(settings.sources.x_trends?.limit ?? settings.limits.x_trends ?? settings.sources_config?.x_trends?.max_items ?? 20));
    let categories = [...(settings.categories ?? [])];
    let subreddits = normalizeSubreddits(settings.subreddits ?? []);

    const isFocused = runMode === "focused" && Boolean(query);
    if (isFocused && isEplIntent(query)) {
      categories = ["Sports"];
      subreddits = [...EPL_SUBREDDITS];
    }

    const payload: TrendsRunStartRequest = {
      ...settings,
      use_openai_strategy: true,
      categories,
      subreddits,
      limits: {
        ...settings.limits,
        youtube: youtubeLimit,
        reddit: redditLimit,
        trends: trendsLimit,
        x_trends: xTrendsLimit,
      },
      sources: {
        youtube: { ...settings.sources.youtube, limit: youtubeLimit },
        reddit: { ...settings.sources.reddit, limit: redditLimit },
        trends: { ...settings.sources.trends, limit: trendsLimit },
        x_trends: {
          ...(settings.sources.x_trends ?? { enabled: false }),
          limit: xTrendsLimit,
        },
      },
      sources_config: {
        ...(settings.sources_config ?? {}),
        x_trends: {
          ...(settings.sources_config?.x_trends ?? {}),
          enabled: Boolean(settings.sources.x_trends?.enabled),
          max_items: xTrendsLimit,
          use_auth: Boolean(settings.sources_config?.x_trends?.use_auth),
        },
      },
    };

    if (isFocused) {
      payload.query = query;
      payload.objective = objective;
      payload.llm_rerank_top_n = llm_rerank_top_n;
      payload.min_focus_relevance = min_focus_relevance;
    } else {
      delete payload.query;
      delete payload.objective;
      delete payload.llm_rerank_top_n;
      delete payload.min_focus_relevance;
    }

    return payload;
  };

  const startRunWithPayload = async (payload: TrendsRunStartRequest) => {
    setSettings(payload);
    const resp = await startRun.mutateAsync(payload);
    setSelectedRunId(resp.run_id);
    setSelectedTopicIds(new Set());
    setSelectedTopicId(null);
    setToast("Trend run started");
    runsQuery.refetch();
  };

  const onStartRun = async () => {
    if (settingsValidationError) {
      setToast(settingsValidationError);
      return;
    }
    const payload = buildStartPayload();
    try {
      if (payload.use_openai_strategy) {
        const status = trendsOpenAiKeyStatus.data;
        if (!status?.configured) {
          setPendingStartPayload(payload);
          setShowOpenAiKeyModal(true);
          setToast("OpenAI API key is required for strategy pass.");
          return;
        }
      }
      await startRunWithPayload(payload);
    } catch (error) {
      setToast(`Failed to start run: ${String(error)}`);
    }
  };

  const onSaveOpenAiKeyAndContinue = async () => {
    const key = openAiKeyInput.trim();
    if (!key) {
      setToast("OpenAI API key is required.");
      return;
    }
    try {
      await setTrendsOpenAiKey.mutateAsync(key);
      setOpenAiKeyInput("");
      setShowOpenAiKeyModal(false);
      await trendsOpenAiKeyStatus.refetch();
      if (pendingStartPayload) {
        await startRunWithPayload(pendingStartPayload);
      }
      setPendingStartPayload(null);
    } catch (error) {
      setToast(`Failed to save OpenAI key: ${String(error)}`);
    }
  };

  const onAction = async (topicId: string, action: TrendsTopicAction) => {
    const previous = actionState[topicId];
    const note = noteDraft[topicId] ?? "";
    setActionState((prev) => ({ ...prev, [topicId]: { action, note } }));
    try {
      await actionMutation.mutateAsync({ topicId, payload: { action, note } });
      setToast(`${action.toUpperCase()} saved`);
    } catch (error) {
      setActionState((prev) => {
        const next = { ...prev };
        if (previous) next[topicId] = previous;
        else delete next[topicId];
        return next;
      });
      setToast(`Action failed: ${String(error)}`);
    }
  };

  const onBulkLike = async () => {
    for (const topicId of selectedTopicIds) {
      await onAction(topicId, "like");
    }
  };

  const onSendToTopicFactory = async () => {
    if (selectedTopicIds.size === 0) {
      setToast("Select at least one topic first");
      return;
    }
    try {
      const topicIds = Array.from(selectedTopicIds);
      let exported: Record<string, unknown>;
      try {
        exported = await exportMutation.mutateAsync({
          format: "idea_factory_v2",
          topic_ids: topicIds,
          run_id: selectedRunId ?? undefined,
          include_actions: true,
        });
      } catch {
        exported = await exportMutation.mutateAsync({
          format: "topic_factory_v1",
          topic_ids: topicIds,
          run_id: selectedRunId ?? undefined,
          include_actions: true,
        });
      }
      let imported: { created_links?: unknown[]; created_item_ids?: unknown[] } = {};
      try {
        imported = await importMutation.mutateAsync(exported);
      } catch {
        // Keep going with local queue fallback.
      }
      const links = (imported.created_links ?? []).map(String);
      const fallbackLinks =
        links.length > 0
          ? links
          : (imported.created_item_ids ?? []).map((id) => `/modules/appgen?research_item_id=${encodeURIComponent(String(id))}`);
      const queueTargets = topicIds
        .map((id) => allTopicsById.get(id))
        .filter((topic): topic is TrendsTopicResult => Boolean(topic));
      for (const topic of queueTargets) {
        await enqueueTopicFactory.mutateAsync({
          topic_text: topic.title,
          source: { module: "TrendsResearcher", run_id: selectedRunId, topic_id: topic.topic_id, sources: topic.sources ?? [] },
          params: { limit: 20, enable_youtube: Boolean(settings.sources.youtube.enabled) },
        });
      }
      setCreatedLinks(fallbackLinks);
      setToast(`Sent ${topicIds.length} topic(s) to IdeaFactory`);
    } catch (error) {
      setToast(`Export failed: ${String(error)}`);
    }
  };

  const onSendSingleToTopicFactory = async (topic: TrendsTopicResult) => {
    try {
      let exported: Record<string, unknown>;
      try {
        exported = await exportMutation.mutateAsync({
          format: "idea_factory_v2",
          topic_ids: [topic.topic_id],
          run_id: selectedRunId ?? undefined,
          include_actions: true,
        });
      } catch {
        exported = await exportMutation.mutateAsync({
          format: "topic_factory_v1",
          topic_ids: [topic.topic_id],
          run_id: selectedRunId ?? undefined,
          include_actions: true,
        });
      }
      let imported: { created_links?: unknown[]; created_item_ids?: unknown[] } = {};
      try {
        imported = await importMutation.mutateAsync(exported);
      } catch {
        // Keep going with local queue fallback.
      }
      await enqueueTopicFactory.mutateAsync({
        topic_text: topic.title,
        source: { module: "TrendsResearcher", run_id: selectedRunId, topic_id: topic.topic_id, sources: topic.sources ?? [] },
        params: { limit: 20, enable_youtube: Boolean(settings.sources.youtube.enabled) },
      });
      const links = (imported.created_links ?? []).map(String);
      const fallbackLinks =
        links.length > 0
          ? links
          : (imported.created_item_ids ?? []).map((id) => `/modules/appgen?research_item_id=${encodeURIComponent(String(id))}`);
      setCreatedLinks((prev) => [...fallbackLinks, ...prev].slice(0, 10));
      setToast("Sent to IdeaFactory queue");
    } catch (error) {
      setToast(`Send failed: ${String(error)}`);
    }
  };

  const onSaveToIdeaVault = async (topic: TrendsTopicResult) => {
    try {
      await createIdeaVault.mutateAsync({
        title: topic.title,
        summary: String(topic.summary ?? ""),
        type: "trend",
        status: "new",
        tags: Object.keys(topic.channels ?? {}),
        source: {
          module: "TrendsResearcher",
          run_id: selectedRunId,
          topic_id: topic.topic_id,
          sources: topic.sources ?? [],
          idea_type: "video",
          lineage: { origin_module: "TrendsResearcher", origin_run_id: selectedRunId, origin_topic_id: topic.topic_id },
          recommended_output_type: "dbvid",
        },
        payload: { ...(topic as Record<string, unknown>), idea_type: "video", recommended_output_type: "dbvid" },
        score: Number(topic.score ?? 0),
      });
      setToast("Saved to IdeaVault");
    } catch (error) {
      setToast(`IdeaVault save failed: ${String(error)}`);
    }
  };

  const onBranchTopicToOpportunityTypes = async (topic: TrendsTopicResult) => {
    try {
      const transformed = await transformSignal.mutateAsync({
        title: topic.title,
        summary: String(topic.summary ?? ""),
        topic_cluster: Object.keys(topic.channels ?? {}).slice(0, 2).join(", "),
        target_user: "short-form audience",
        signal: topic.title,
      });
      const forms = transformed.forms ?? [];
      for (const form of forms) {
        const ideaType = String(form.idea_type ?? "app").toLowerCase();
        await createIdeaVault.mutateAsync({
          title: String(form.title ?? topic.title),
          summary: String(form.summary ?? ""),
          type: "idea",
          status: "new",
          tags: ["strategy", "branched", ideaType],
          source: {
            module: "TrendsResearcher",
            run_id: selectedRunId,
            topic_id: topic.topic_id,
            idea_type: ideaType,
            lineage: { origin_module: "TrendsResearcher", origin_run_id: selectedRunId, origin_topic_id: topic.topic_id },
            recommended_output_type: String(form.recommended_output_type ?? ""),
          },
          payload: form,
          score: Number(form.score ?? 0),
        });
      }
      setToast(`Branched into ${forms.length} opportunity forms and saved to IdeaVault`);
    } catch (error) {
      setToast(`Branching failed: ${String(error)}`);
    }
  };

  const onSaveIdeaToIdeaVault = async (idea: Record<string, unknown>, ideaType: "video" | "app" | "saas") => {
    const ideaId = String(idea.idea_id ?? "");
    const score = scoreBreakdowns[ideaId] ?? {};
    const finalScore = Number(score.final_idea_score ?? idea.confidence ?? 0);
    try {
      await createIdeaVault.mutateAsync({
        title: String(idea.title ?? "Untitled idea"),
        summary: String(idea.one_liner ?? idea.problem_statement ?? ""),
        type: "idea",
        status: "new",
        tags: ["strategy", "idea", ideaType],
        source: { module: "TrendsResearcher", run_id: selectedRunId, idea_id: ideaId || undefined },
        payload: { ...idea, score_breakdown: score },
        score: Number.isFinite(finalScore) ? finalScore : 0,
      });
      setToast("Saved idea to IdeaVault");
    } catch (error) {
      setToast(`IdeaVault save failed: ${String(error)}`);
    }
  };

  const onSaveGroupToIdeaVault = async (group: Record<string, unknown>) => {
    const groupScore = Number(group.group_score ?? 0);
    try {
      await createIdeaVault.mutateAsync({
        title: String(group.theme_name ?? "Untitled group"),
        summary: String(group.thesis ?? group.why_now ?? ""),
        type: "idea",
        status: "new",
        tags: ["strategy", "group"],
        source: { module: "TrendsResearcher", run_id: selectedRunId, group_id: String(group.group_id ?? "") || undefined },
        payload: group,
        score: Number.isFinite(groupScore) ? groupScore : 0,
      });
      setToast("Saved group to IdeaVault");
    } catch (error) {
      setToast(`IdeaVault save failed: ${String(error)}`);
    }
  };

  const onSaveBigCallToIdeaVault = async (call: Record<string, unknown>) => {
    const conviction = Number(call.conviction_score ?? 0);
    try {
      await createIdeaVault.mutateAsync({
        title: String(call.headline ?? "Untitled call"),
        summary: String(call.thesis ?? call.expected_upside ?? ""),
        type: "idea",
        status: "new",
        tags: ["strategy", "big_call"],
        source: { module: "TrendsResearcher", run_id: selectedRunId, call_id: String(call.call_id ?? "") || undefined },
        payload: call,
        score: Number.isFinite(conviction) ? conviction : 0,
      });
      setToast("Saved big call to IdeaVault");
    } catch (error) {
      setToast(`IdeaVault save failed: ${String(error)}`);
    }
  };

  const onDeleteRun = async (runId: string) => {
    try {
      await deleteRun.mutateAsync(runId);
      if (selectedRunId === runId) {
        setSelectedRunId(null);
        setSelectedTopicId(null);
      }
      setToast("Run deleted");
    } catch (error) {
      setToast(`Delete failed: ${String(error)}`);
    }
  };

  const onCancelRun = async (runId: string) => {
    try {
      await cancelRunMutation.mutateAsync(runId);
      setToast("Run stopped");
      runsQuery.refetch();
    } catch (error) {
      setToast(`Stop failed: ${String(error)}`);
    }
  };

  const onNudgeRun = async (runId: string) => {
    try {
      await nudgeRunMutation.mutateAsync(runId);
      setToast("Run nudged");
      runsQuery.refetch();
    } catch (error) {
      setToast(`Nudge failed: ${String(error)}`);
    }
  };

  return (
    <div className="space-y-4">
      <PageHeader
        title="Trends Researcher"
        description="Latest trend harvesting results and export workflow into IdeaFactory."
        meta={`Last run: ${selectedRun?.started_at ? relativeTime(selectedRun.started_at) : "No runs yet"}`}
        actions={
          <>
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => {
                runsQuery.refetch();
                if (selectedRunId) resultsQuery.refetch();
              }}
            >
              <RefreshCw size={13} className={runsQuery.isFetching ? "animate-spin" : ""} />
              Refresh
            </Button>
            <Button type="button" size="sm" onClick={onStartRun} disabled={startRun.isPending || Boolean(settingsValidationError)}>
              {startRun.isPending ? <Loader2 size={13} className="animate-spin" /> : <Play size={13} />}
              Start Run
            </Button>
          </>
        }
      />
      {settingsValidationError ? (
        <div className="rounded-lg border border-warning/30 bg-warning/10 px-3 py-2 text-xs text-warning">{settingsValidationError}</div>
      ) : null}
      {!trendsOpenAiKeyStatus.data?.configured ? (
        <div className="rounded-lg border border-warning/30 bg-warning/10 px-3 py-2 text-xs text-warning flex items-center justify-between gap-2">
          <span>OpenAI strategy key is not configured. Runs in OpenAI strategy mode will fail.</span>
          <Button type="button" size="sm" variant="outline" onClick={() => setShowOpenAiKeyModal(true)}>
            Configure Key
          </Button>
        </div>
      ) : null}

      {runsQuery.error ? (
        <div className="rounded-lg border border-danger/20 bg-danger/10 px-3 py-2 text-sm text-danger">
          Disconnected from Trends backend. Check `DASHBURG_TRENDS_API_BASE_URL` and retry.
        </div>
      ) : null}

      <Card>
        <CardHeader className="pb-2">
          <button
            type="button"
            className="flex w-full items-center justify-between text-left"
            onClick={() => setSettingsOpen((prev) => !prev)}
          >
            <CardTitle className="text-[12px]">Run Settings</CardTitle>
            <span className="text-xs text-muted-foreground inline-flex items-center gap-1">
              Advanced options {settingsOpen ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
            </span>
          </button>
        </CardHeader>
        {settingsOpen ? (
          <CardContent className="space-y-4">
            <div className="grid gap-2 sm:grid-cols-2">
              <button
                type="button"
                onClick={() => setRunMode("top")}
                className={`rounded-lg border px-3 py-2 text-sm transition ${
                  runMode === "top" ? "border-primary bg-primary/15 text-primary" : "border-border bg-background/40 text-foreground"
                }`}
              >
                Top Trends
              </button>
              <button
                type="button"
                onClick={() => setRunMode("focused")}
                className={`rounded-lg border px-3 py-2 text-sm transition ${
                  runMode === "focused" ? "border-primary bg-primary/15 text-primary" : "border-border bg-background/40 text-foreground"
                }`}
              >
                Focused Trends
              </button>
            </div>

            <div className="grid gap-3 md:grid-cols-2">
              <label className="space-y-1 text-xs text-muted-foreground">
                Focus Query (optional)
                <Input
                  value={settings.query ?? ""}
                  placeholder="e.g. english premier league"
                  onChange={(e) => setSettings((prev) => ({ ...prev, query: e.target.value }))}
                />
              </label>
              <label className="space-y-1 text-xs text-muted-foreground">
                Objective
                <Input
                  value={settings.objective ?? DEFAULT_OBJECTIVE}
                  onChange={(e) => setSettings((prev) => ({ ...prev, objective: e.target.value || DEFAULT_OBJECTIVE }))}
                />
              </label>
            </div>

            <div className="grid gap-2 sm:grid-cols-3">
              {(["small", "medium", "large"] as RunSize[]).map((size) => (
                <button
                  key={size}
                  type="button"
                  onClick={() => setRunSize(size)}
                  className={`rounded-lg border px-3 py-2 text-sm capitalize transition ${
                    settings.limits.size === size ? "border-primary bg-primary/15 text-primary" : "border-border bg-background/40 text-foreground"
                  }`}
                >
                  {size}
                </button>
              ))}
            </div>

            <div className="grid gap-2 sm:grid-cols-3">
              {(["youtube", "trends", "reddit", "x_trends"] as SourceKey[]).map((source) => (
                <button
                  key={source}
                  type="button"
                  onClick={() => handleSourceToggle(source)}
                  className={`rounded-lg border px-3 py-2 text-sm capitalize transition ${
                    settings.sources[source]?.enabled ? "border-primary bg-primary/15 text-primary" : "border-border bg-background/40 text-foreground"
                  }`}
                >
                  {sourceLabel(source)}
                </button>
              ))}
            </div>
            <label className="inline-flex items-center gap-2 text-xs text-muted-foreground">
              <input
                type="checkbox"
                checked={Boolean(settings.sources.youtube.enabled)}
                onChange={() => handleSourceToggle("youtube")}
              />
              Enable YouTube
            </label>

            <div className="grid gap-3 md:grid-cols-3">
              <label className="space-y-1 text-xs text-muted-foreground">
                Region
                <Input value={settings.region} onChange={(e) => setSettings((prev) => ({ ...prev, region: e.target.value.toUpperCase() || "US" }))} />
              </label>
              <label className="space-y-1 text-xs text-muted-foreground">
                YouTube limit
                <Input
                  type="number"
                  value={settings.sources.youtube.limit ?? 40}
                  onChange={(e) => {
                    const value = Number(e.target.value) || 0;
                    setSettings((prev) => ({
                      ...prev,
                      sources: { ...prev.sources, youtube: { ...prev.sources.youtube, limit: value } },
                      limits: { ...prev.limits, youtube: value },
                    }));
                  }}
                />
              </label>
                <label className="space-y-1 text-xs text-muted-foreground">
                  Reddit limit
                <Input
                  type="number"
                  value={settings.sources.reddit.limit ?? 40}
                  onChange={(e) => {
                    const value = Number(e.target.value) || 0;
                    setSettings((prev) => ({
                      ...prev,
                      sources: { ...prev.sources, reddit: { ...prev.sources.reddit, limit: value } },
                      limits: { ...prev.limits, reddit: value },
                    }));
                  }}
                />
              </label>
              <label className="space-y-1 text-xs text-muted-foreground">
                X trends limit
                <Input
                  type="number"
                  min={0}
                  max={30}
                  value={settings.sources.x_trends?.limit ?? 20}
                  onChange={(e) => {
                    const value = Math.max(0, Math.min(30, Number(e.target.value) || 0));
                    setSettings((prev) => ({
                      ...prev,
                      sources: { ...prev.sources, x_trends: { ...(prev.sources.x_trends ?? { enabled: false }), limit: value } },
                      limits: { ...prev.limits, x_trends: value },
                      sources_config: {
                        ...(prev.sources_config ?? {}),
                        x_trends: {
                          ...(prev.sources_config?.x_trends ?? {}),
                          max_items: value,
                        },
                      },
                    }));
                  }}
                />
              </label>
            </div>

            <div className="space-y-2">
              <p className="text-xs font-medium uppercase tracking-[0.1em] text-muted-foreground">YouTube categories</p>
              <div className="flex flex-wrap gap-2">
                {CATEGORY_OPTIONS.map((cat) => (
                  <button
                    type="button"
                    key={cat}
                    onClick={() => toggleCategory(cat)}
                    className={`rounded-lg border px-2.5 py-1.5 text-xs transition ${
                      settings.categories.includes(cat) ? "border-primary bg-primary/15 text-primary" : "border-border bg-background/30 text-muted-foreground"
                    }`}
                  >
                    {cat}
                  </button>
                ))}
              </div>
            </div>

            <div className="space-y-2">
              <p className="text-xs font-medium uppercase tracking-[0.1em] text-muted-foreground">Subreddits</p>
              <div className="flex flex-wrap gap-2">
                {SUBREDDIT_OPTIONS.map((sub) => (
                  <button
                    type="button"
                    key={sub}
                    onClick={() => toggleSubreddit(sub)}
                    className={`rounded-lg border px-2.5 py-1.5 text-xs transition ${
                      settings.subreddits.includes(sub) ? "border-primary bg-primary/15 text-primary" : "border-border bg-background/30 text-muted-foreground"
                    }`}
                  >
                    r/{sub}
                  </button>
                ))}
              </div>
              <div className="mt-2 flex items-center gap-2">
                <Input
                  value={newSubreddit}
                  placeholder="Add subreddit (e.g. startups)"
                  onChange={(e) => setNewSubreddit(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") {
                      e.preventDefault();
                      addCustomSubreddit();
                    }
                  }}
                />
                <Button type="button" size="sm" variant="outline" onClick={addCustomSubreddit}>
                  Add
                </Button>
              </div>
            </div>

            <button
              type="button"
              className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
              onClick={() => setAdvancedOpen((prev) => !prev)}
            >
              Advanced limits {advancedOpen ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
            </button>

            {advancedOpen ? (
              <div className="grid gap-3 md:grid-cols-2">
                <label className="space-y-1 text-xs text-muted-foreground">
                  Google Trends limit
                  <Input
                    type="number"
                    value={settings.sources.trends.limit ?? 20}
                    onChange={(e) => {
                      const value = Number(e.target.value) || 0;
                      setSettings((prev) => ({
                        ...prev,
                        sources: { ...prev.sources, trends: { ...prev.sources.trends, limit: value } },
                        limits: { ...prev.limits, trends: value },
                    }));
                  }}
                />
                </label>
                <label className="inline-flex items-center gap-2 text-xs text-muted-foreground">
                  <input
                    type="checkbox"
                    checked={Boolean(settings.sources_config?.x_trends?.use_auth)}
                    onChange={(e) =>
                      setSettings((prev) => ({
                        ...prev,
                        sources_config: {
                          ...(prev.sources_config ?? {}),
                          x_trends: {
                            ...(prev.sources_config?.x_trends ?? {}),
                            use_auth: e.target.checked,
                          },
                        },
                      }))
                    }
                  />
                  X trends: use auth state
                </label>
                <label className="space-y-1 text-xs text-muted-foreground">
                  LLM rerank top N (0-100)
                  <Input
                    type="number"
                    min={0}
                    max={100}
                    value={settings.llm_rerank_top_n ?? DEFAULT_LLM_RERANK_TOP_N}
                    onChange={(e) => {
                      const value = clampInt(Number(e.target.value), 0, 100);
                      setSettings((prev) => ({ ...prev, llm_rerank_top_n: value }));
                    }}
                  />
                </label>
                <label className="space-y-1 text-xs text-muted-foreground">
                  Min focus relevance (0-1)
                  <Input
                    type="number"
                    min={0}
                    max={1}
                    step="0.05"
                    value={settings.min_focus_relevance ?? DEFAULT_MIN_FOCUS_RELEVANCE}
                    onChange={(e) => {
                      const value = clampFloat(Number(e.target.value), 0, 1);
                      setSettings((prev) => ({ ...prev, min_focus_relevance: value }));
                    }}
                  />
                </label>
                <div className="rounded-lg border border-border/60 bg-background/30 p-3 text-xs text-muted-foreground">
                  Use small/medium/large presets for balanced cost. Enable advanced limits only when you need higher sampling.
                </div>
              </div>
            ) : null}
          </CardContent>
        ) : null}
      </Card>

      <div className="grid gap-4 lg:grid-cols-[1fr_380px]">
        <div className="space-y-4">
          <Card>
            <CardHeader className="pb-2">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <CardTitle className="text-[12px]">Run Status</CardTitle>
                <div className="flex items-center gap-2">
                  <span className={`rounded-full border px-2 py-0.5 text-[10px] uppercase tracking-wide ${
                    statusTone(effectiveRunStatus) === "success"
                      ? "border-success/30 bg-success/10 text-success"
                      : statusTone(effectiveRunStatus) === "danger"
                      ? "border-danger/30 bg-danger/10 text-danger"
                      : statusTone(effectiveRunStatus) === "warning"
                      ? "border-warning/30 bg-warning/10 text-warning"
                      : "border-border bg-background/40 text-muted-foreground"
                  }`}>
                    {effectiveRunStatus}
                  </span>
                  {selectedRunId && isRunActive ? (
                    <Button type="button" size="sm" variant="danger" onClick={() => onCancelRun(selectedRunId)} disabled={cancelRunMutation.isPending}>
                      Stop Run
                    </Button>
                  ) : null}
                </div>
              </div>
            </CardHeader>
            <CardContent>
              <div className="grid gap-2 sm:grid-cols-4">
                {["Queued", "Running", "Succeeded", "Failed"].map((label, idx) => {
                  const active = stageIndex(effectiveRunStatus) >= idx;
                  const failed = String(effectiveRunStatus).toUpperCase() === "FAILED" && idx === 3;
                  return (
                    <div key={label} className={`rounded-lg border px-2 py-2 text-center text-xs ${
                      failed
                        ? "border-danger/40 bg-danger/10 text-danger"
                        : active
                        ? "border-primary/40 bg-primary/10 text-primary"
                        : "border-border/60 bg-background/30 text-muted-foreground"
                    }`}>
                      {label}
                    </div>
                  );
                })}
              </div>
                <div className="mt-3 space-y-2 rounded-lg border border-border/60 bg-background/25 p-3">
                  <div className="grid gap-2 sm:grid-cols-2 text-[11px] text-muted-foreground">
                    <span>
                      Mode: <span className="font-medium text-foreground">{runModeLabel}</span>
                    </span>
                    <span>
                      Focus query: <span className="font-medium text-foreground">{runQuery || "-"}</span>
                    </span>
                    <span>
                      Objective: <span className="font-medium text-foreground">{runObjective || "-"}</span>
                    </span>
                  </div>
                  <div className="flex flex-wrap items-center justify-between gap-2 text-xs">
                    <span className="text-muted-foreground">
                      Stage: <span className="font-medium text-foreground">{liveStage || "n/a"}</span>
                  </span>
                  <span className="text-muted-foreground">
                    Heartbeat: <span className="font-medium text-foreground">{heartbeatAt ? relativeTime(heartbeatAt) : "-"}</span>
                  </span>
                </div>
                <div className="h-2 w-full overflow-hidden rounded bg-background/60">
                  <div className="h-full rounded bg-primary transition-all duration-300" style={{ width: `${liveProgressPct}%` }} />
                </div>
                <div className="flex flex-wrap items-center justify-between gap-2 text-[11px] text-muted-foreground">
                  <span>
                    Progress: <span className="font-medium text-foreground">{progressLabel}</span>
                  </span>
                  <span>
                    Run ID: <span className="font-medium text-foreground">{selectedRunId ? `${selectedRunId.slice(0, 12)}…` : "-"}</span>
                  </span>
                </div>
                {heartbeatStale ? (
                  <div className="rounded-md border border-warning/30 bg-warning/10 px-2 py-1 text-[11px] text-warning">
                    Worker heartbeat is stale ({heartbeatAt ? relativeTime(heartbeatAt) : "unknown"}). Stop and restart if this persists.
                  </div>
                ) : null}
                {selectedRun?.error ? (
                  <div className="rounded-md border border-danger/30 bg-danger/10 px-2 py-1 text-[11px] text-danger">
                    {selectedRun.error}
                  </div>
                ) : null}
                <div className="grid gap-2 sm:grid-cols-3 text-[11px] text-muted-foreground">
                  <span>YouTube: {Number(sourceCounts.youtube ?? 0)}</span>
                  <span>Reddit: {Number(sourceCounts.reddit ?? 0)}</span>
                  <span>Trends: {Number(sourceCounts.trends ?? 0)}</span>
                  <span>X: {Number(sourceCounts.x ?? sourceCounts.x_trends ?? 0)}</span>
                </div>
                {(Number(keptSourceCounts.youtube ?? 0) > 0 || Number(keptSourceCounts.reddit ?? 0) > 0 || Number(keptSourceCounts.trends ?? 0) > 0 || Number(keptSourceCounts.x ?? keptSourceCounts.x_trends ?? 0) > 0) ? (
                  <div className="grid gap-2 sm:grid-cols-4 text-[11px] text-muted-foreground">
                    <span>YouTube kept/filter: {Number(keptSourceCounts.youtube ?? 0)} / {Number(filteredSourceCounts.youtube ?? 0)}</span>
                    <span>Reddit kept/filter: {Number(keptSourceCounts.reddit ?? 0)} / {Number(filteredSourceCounts.reddit ?? 0)}</span>
                    <span>Trends kept/filter: {Number(keptSourceCounts.trends ?? 0)} / {Number(filteredSourceCounts.trends ?? 0)}</span>
                    <span>X kept/filter: {Number(keptSourceCounts.x ?? keptSourceCounts.x_trends ?? 0)} / {Number(filteredSourceCounts.x ?? filteredSourceCounts.x_trends ?? 0)}</span>
                  </div>
                ) : null}
                {sourceWarnings.length > 0 ? (
                  <div className="rounded-md border border-warning/30 bg-warning/10 px-2 py-1 text-[11px] text-warning space-y-1">
                    {sourceWarnings.slice(-4).map((warning, idx) => {
                      if (typeof warning === "string") return <div key={`sw-${idx}`}>{warning}</div>;
                      const source = String(warning.source ?? "source");
                      const message = String(warning.message ?? warning.warning ?? "");
                      return <div key={`sw-${idx}`}>{source}: {message}</div>;
                    })}
                  </div>
                ) : null}
                {llmTotal > 0 ? (
                  <div className="text-[11px] text-muted-foreground">
                    LLM analysis: <span className="font-medium text-foreground">{llmDone}/{llmTotal}</span>
                  </div>
                ) : null}
                {(llmLogicalExpected > 0 || llmLogicalStarted > 0 || llmHttpAttemptStarted > 0) ? (
                  <div className="rounded-md border border-border/60 bg-background/35 px-2 py-2 text-[11px] text-muted-foreground space-y-1">
                    <div>
                      LLM logical calls: <span className="font-medium text-foreground">{llmLogicalCompleted}/{llmLogicalExpected || llmLogicalStarted}</span>
                    </div>
                    <div>
                      HTTP attempts: <span className="font-medium text-foreground">{llmHttpAttemptStarted}</span>
                      {llmMaxHttpAttempts > 0 ? (
                        <>
                          {" / "}
                          <span className="font-medium text-foreground">{llmMaxHttpAttempts}</span> max
                        </>
                      ) : null}
                      {" · "}
                      ok=<span className="font-medium text-foreground">{llmHttpAttemptSucceeded}</span>
                      {" · "}
                      fail=<span className="font-medium text-foreground">{llmHttpAttemptFailed}</span>
                    </div>
                    <div>
                      Endpoints: <span className="font-medium text-foreground">{llmEndpointCount || "-"}</span>
                      {" · "}
                      Retries used: <span className="font-medium text-foreground">{llmRetryCount}</span>
                    </div>
                    {(llmLastApiEvent || llmLastApiEndpoint || llmLastApiError) ? (
                      <div>
                        Last API: <span className="font-medium text-foreground">{llmLastApiEvent || "unknown"}</span>
                        {llmLastApiEndpoint ? <> @ <span className="font-medium text-foreground">{llmLastApiEndpoint}</span></> : null}
                        {llmLastApiError ? <> · <span className="text-danger">{llmLastApiError}</span></> : null}
                      </div>
                    ) : null}
                  </div>
                ) : null}
                {endpointHealthRows.length > 0 ? (
                  <details>
                    <summary className="cursor-pointer text-[11px] text-muted-foreground">LLM endpoint health</summary>
                    <div className="mt-1 max-h-28 overflow-auto rounded border border-border/60 bg-background/30 p-2 text-[11px] text-muted-foreground space-y-1">
                      {endpointHealthRows.map((row) => (
                        <div key={row.endpoint}>
                          <span className="font-medium text-foreground">{row.endpoint}</span>
                          {" · "}start={row.started}
                          {" · "}ok={row.succeeded}
                          {" · "}fail={row.failed}
                          {row.lastError ? <> · <span className="text-danger">{row.lastError}</span></> : null}
                        </div>
                      ))}
                    </div>
                  </details>
                ) : null}
                {liveEvents.length > 0 ? (
                  <details>
                    <summary className="cursor-pointer text-[11px] text-muted-foreground">Recent run events</summary>
                    <div className="mt-1 max-h-36 overflow-auto rounded border border-border/60 bg-background/30 p-2 text-[11px] text-muted-foreground space-y-1">
                      {liveEvents.map((event, idx) => (
                        <div key={`${idx}-${event.slice(0, 12)}`}>{event}</div>
                      ))}
                    </div>
                  </details>
                ) : null}
                <details>
                  <summary className="cursor-pointer text-[11px] text-muted-foreground">
                    Per-run logs {runLogsQuery.isFetching ? "(updating...)" : ""}
                  </summary>
                  <div className="mt-1 max-h-40 overflow-auto rounded border border-border/60 bg-background/30 p-2 text-[11px] text-muted-foreground space-y-1">
                    {runLogLines.length === 0 ? <div>No per-run logs yet.</div> : null}
                    {runLogLines.map((line, idx) => (
                      <div key={`${idx}-${line.slice(0, 16)}`}>{line}</div>
                    ))}
                  </div>
                </details>
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="pb-2">
              <div className="flex flex-wrap items-center gap-2">
                <button
                  type="button"
                  className={`rounded-lg px-2.5 py-1 text-xs ${activeSection === "bigcalls" ? "bg-primary/15 text-primary" : "text-muted-foreground"}`}
                  onClick={() => setActiveSection("bigcalls")}
                >
                  Big Calls
                </button>
                <button
                  type="button"
                  className={`rounded-lg px-2.5 py-1 text-xs ${activeSection === "ideas" ? "bg-primary/15 text-primary" : "text-muted-foreground"}`}
                  onClick={() => setActiveSection("ideas")}
                >
                  Ideas
                </button>
                <button
                  type="button"
                  className={`rounded-lg px-2.5 py-1 text-xs ${activeSection === "groups" ? "bg-primary/15 text-primary" : "text-muted-foreground"}`}
                  onClick={() => setActiveSection("groups")}
                >
                  Groups
                </button>
                <button
                  type="button"
                  className={`rounded-lg px-2.5 py-1 text-xs ${activeSection === "overall" ? "bg-primary/15 text-primary" : "text-muted-foreground"}`}
                  onClick={() => setActiveSection("overall")}
                >
                  Top 25 Overall
                </button>
                <button
                  type="button"
                  className={`rounded-lg px-2.5 py-1 text-xs ${activeSection === "sources" ? "bg-primary/15 text-primary" : "text-muted-foreground"}`}
                  onClick={() => setActiveSection("sources")}
                >
                  Top by Source
                </button>
                <button
                  type="button"
                  className={`rounded-lg px-2.5 py-1 text-xs ${activeSection === "channels" ? "bg-primary/15 text-primary" : "text-muted-foreground"}`}
                  onClick={() => setActiveSection("channels")}
                >
                  Top 2 Per Channel
                </button>
                <button
                  type="button"
                  className={`rounded-lg px-2.5 py-1 text-xs ${activeSection === "actions" ? "bg-primary/15 text-primary" : "text-muted-foreground"}`}
                  onClick={() => setActiveSection("actions")}
                >
                  Actions / History
                </button>
              </div>
            </CardHeader>
            <CardContent className="space-y-3">
              {activeSection !== "actions" ? (
                <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-border/60 bg-background/30 px-3 py-2">
                  <span className="text-xs text-muted-foreground">{selectedTopicIds.size} selected</span>
                  <div className="flex flex-wrap gap-2">
                    <Button type="button" size="sm" variant="outline" onClick={onBulkLike} disabled={selectedTopicIds.size === 0 || actionMutation.isPending}>
                      Bulk Like
                    </Button>
                    <Button type="button" size="sm" onClick={onSendToTopicFactory} disabled={selectedTopicIds.size === 0 || exportMutation.isPending || importMutation.isPending}>
                      {exportMutation.isPending || importMutation.isPending ? <Loader2 size={12} className="animate-spin" /> : <CheckCircle2 size={12} />}
                      Send to IdeaFactory
                    </Button>
                  </div>
                </div>
              ) : null}

              {resultsQuery.isLoading ? (
                <div className="rounded-lg border border-border/60 bg-background/20 p-4 text-sm text-muted-foreground inline-flex items-center gap-2">
                  <Loader2 size={14} className="animate-spin" /> Loading run results...
                </div>
              ) : null}

              {resultsQuery.error ? (
                <div className="rounded-lg border border-danger/30 bg-danger/10 p-3 text-sm text-danger">
                  {String(resultsQuery.error)}
                </div>
              ) : null}

              {selectedRunId ? (
                <div className={`rounded-lg border px-3 py-2 text-xs ${
                  strategyRunning
                    ? "border-warning/30 bg-warning/10 text-warning"
                    : strategyState === "succeeded"
                    ? "border-success/30 bg-success/10 text-success"
                    : strategyState === "failed"
                    ? "border-danger/30 bg-danger/10 text-danger"
                    : "border-border/60 bg-background/20 text-muted-foreground"
                }`}>
                  Strategy pass:{" "}
                  <span className="font-medium uppercase">
                    {strategyState || "idle"}
                  </span>
                  {strategyRunning ? " - showing quick results now, multi-phase LLM update in progress." : null}
                  {strategyRunning && strategyCurrentPhase ? ` · phase: ${strategyCurrentPhase}` : null}
                  {strategyRunning && strategyPhaseEntries.length > 0 ? ` · phases: ${strategyPhaseDone}/${strategyPhaseEntries.length}` : null}
                  {strategyRunning && strategyPhaseEntries.length === 0 ? " · awaiting strategy worker start" : null}
                  {strategyRunning && strategyQueuedAt ? ` · queued ${relativeTime(strategyQueuedAt)}` : null}
                  {strategyRunning && strategyRunTelemetry.length > 0 ? ` · ${strategyRunTelemetry.join(" · ")}` : null}
                  {strategyRunning && strategyLastTickAt ? ` · last update ${relativeTime(strategyLastTickAt)}` : null}
                  {strategyState === "succeeded" ? ` - using ${strategyMode}.` : null}
                  {strategyLastError ? ` · ${strategyLastError}` : null}
                  {strategyEvents.length > 0 ? ` · strategy events ${strategyEvents.length}` : null}
                </div>
              ) : null}
              {strategyEvents.length > 0 ? (
                <details>
                  <summary className="cursor-pointer text-[11px] text-muted-foreground">Strategy event timeline</summary>
                  <div className="mt-1 max-h-32 overflow-auto rounded border border-border/60 bg-background/30 p-2 text-[11px] text-muted-foreground space-y-1">
                    {strategyEvents.slice(-20).map((event, idx) => {
                      const ts = String(event.ts ?? "").trim();
                      const phase = String(event.phase ?? "").trim();
                      const eventName = String(event.event ?? "").trim();
                      const provider = String(event.provider ?? "").trim();
                      const status = String(event.status ?? "").trim();
                      return (
                        <div key={`${idx}-${ts}-${phase}`}>
                          {ts ? `${relativeTime(ts)} · ` : ""}
                          {phase || "phase?"}
                          {eventName ? ` · ${eventName}` : ""}
                          {provider ? ` (${provider})` : ""}
                          {status ? ` · ${status}` : ""}
                        </div>
                      );
                    })}
                  </div>
                </details>
              ) : null}

              {activeSection === "bigcalls" ? (
                <div className="space-y-3">
                  {bigCalls.length === 0 ? (
                    <div className="rounded-lg border border-dashed border-border p-3 text-sm text-muted-foreground">
                      No big calls generated yet for this run.
                    </div>
                  ) : (
                    bigCalls.map((call, idx) => (
                      <div key={String(call.call_id ?? call.headline ?? `call-${idx}`)} className="rounded-lg border border-border/60 bg-background/25 p-3">
                        <div className="flex flex-wrap items-center justify-between gap-2">
                          <p className="text-sm font-semibold text-foreground">{String(call.headline ?? "Untitled call")}</p>
                          <span className="rounded-full border border-primary/30 bg-primary/10 px-2 py-0.5 text-[11px] text-primary">
                            Conviction {(Number(call.conviction_score ?? 0) * 100).toFixed(0)}%
                          </span>
                        </div>
                        <p className="mt-1 text-xs text-muted-foreground">{String(call.thesis ?? "")}</p>
                        <p className="mt-2 text-xs text-foreground">{String(call.expected_upside ?? "")}</p>
                        <div className="mt-2">
                          <Button size="sm" variant="outline" onClick={() => onSaveBigCallToIdeaVault(call)}>
                            Send to IdeaVault
                          </Button>
                        </div>
                      </div>
                    ))
                  )}
                </div>
              ) : null}

              {activeSection === "ideas" ? (
                <div className="space-y-2">
                  {ideaCandidates.length === 0 ? (
                    <div className="rounded-lg border border-dashed border-border p-3 text-sm text-muted-foreground">
                      No idea candidates generated yet for this run.
                    </div>
                  ) : (
                    <>
                      {reviewNotes.length > 0 ? (
                        <div className="rounded-lg border border-border/60 bg-background/25 p-3">
                          <p className="text-xs uppercase tracking-wide text-muted-foreground">Final Review Notes</p>
                          <ul className="mt-2 space-y-1 text-xs text-foreground">
                            {reviewNotes.slice(0, 6).map((note, idx) => (
                              <li key={`review-note-${idx}`}>- {note}</li>
                            ))}
                          </ul>
                        </div>
                      ) : null}
                      {(["video", "app", "saas"] as const).map((ideaType) => (
                        <div key={`idea-type-${ideaType}`} className="space-y-2">
                          <p className="text-xs uppercase tracking-wide text-muted-foreground">{ideaType} ideas</p>
                          {(sortedIdeaCandidatesByType[ideaType] ?? []).slice(0, 20).map((idea, idx) => {
                            const ideaId = String(idea.idea_id ?? "");
                            const score = scoreBreakdowns[ideaId] ?? {};
                            return (
                              <div key={ideaId || `${ideaType}-idea-${idx}`} className="rounded-lg border border-border/60 bg-background/25 p-3">
                                <div className="flex flex-wrap items-center justify-between gap-2">
                                  <p className="text-sm font-medium text-foreground">{String(idea.title ?? "Untitled idea")}</p>
                                  <span className="rounded-full border border-border px-2 py-0.5 text-[11px] text-muted-foreground">
                                    {ideaType}
                                  </span>
                                </div>
                                <p className="mt-1 text-xs text-muted-foreground">{String(idea.one_liner ?? "")}</p>
                                <div className="mt-2 flex flex-wrap gap-2 text-[11px] text-muted-foreground">
                                  <span>Confidence {(Number(idea.confidence ?? 0) * 100).toFixed(0)}%</span>
                                  <span>Score {(Number(score.final_idea_score ?? 0) * 100).toFixed(0)}%</span>
                                  <span>TTV {Number(idea.time_to_value_days ?? 0)}d</span>
                                </div>
                                <p className="mt-2 text-xs text-foreground">Next step: {String(idea.next_step ?? "-")}</p>
                                <div className="mt-2">
                                  <Button size="sm" variant="outline" onClick={() => onSaveIdeaToIdeaVault(idea, ideaType)}>
                                    Send to IdeaVault
                                  </Button>
                                </div>
                              </div>
                            );
                          })}
                          {(sortedIdeaCandidatesByType[ideaType] ?? []).length === 0 ? (
                            <div className="rounded-lg border border-dashed border-border p-2 text-xs text-muted-foreground">
                              No {ideaType} ideas generated for this run.
                            </div>
                          ) : null}
                        </div>
                      ))}
                    </>
                  )}
                </div>
              ) : null}

              {activeSection === "groups" ? (
                <div className="space-y-2">
                  {ideaGroups.length === 0 ? (
                    <div className="rounded-lg border border-dashed border-border p-3 text-sm text-muted-foreground">
                      No idea groups generated yet for this run.
                    </div>
                  ) : (
                    ideaGroups.map((group, idx) => (
                      <div key={String(group.group_id ?? group.theme_name ?? `group-${idx}`)} className="rounded-lg border border-border/60 bg-background/25 p-3">
                        <div className="flex flex-wrap items-center justify-between gap-2">
                          <p className="text-sm font-semibold text-foreground">{String(group.theme_name ?? "Untitled group")}</p>
                          <span className="rounded-full border border-primary/30 bg-primary/10 px-2 py-0.5 text-[11px] text-primary">
                            {(Number(group.group_score ?? 0) * 100).toFixed(0)}%
                          </span>
                        </div>
                        <p className="mt-1 text-xs text-muted-foreground">{String(group.thesis ?? "")}</p>
                        <p className="mt-2 text-xs text-foreground">Why now: {String(group.why_now ?? "-")}</p>
                        <div className="mt-2">
                          <Button size="sm" variant="outline" onClick={() => onSaveGroupToIdeaVault(group)}>
                            Send to IdeaVault
                          </Button>
                        </div>
                      </div>
                    ))
                  )}
                </div>
              ) : null}

              {activeSection === "overall" ? (
                <div className="overflow-x-auto rounded-lg border border-border/60">
                  <table className="min-w-full text-left text-sm">
                    <thead className="bg-background/30 text-xs uppercase tracking-wide text-muted-foreground">
                      <tr>
                        <th className="px-3 py-2" />
                        <th className="px-3 py-2">Topic</th>
                        <th className="px-3 py-2">Score</th>
                        <th className="px-3 py-2">Channels</th>
                        <th className="px-3 py-2">Actions</th>
                      </tr>
                    </thead>
                    <tbody>
                      {sortedTopOverall.map((topic) => {
                        const action = actionState[topic.topic_id]?.action;
                        const topicChannels = normalizeTrendChannels(topic as Record<string, unknown>);
                        return (
                          <tr
                            key={topic.topic_id}
                            className={`border-t border-border/60 transition ${selectedTopicId === topic.topic_id ? "bg-primary/10" : "hover:bg-background/40"}`}
                          >
                            <td className="px-3 py-2 align-top">
                              <input
                                type="checkbox"
                                checked={selectedTopicIds.has(topic.topic_id)}
                                onChange={() => toggleSelection(topic.topic_id)}
                                className="mt-1"
                              />
                            </td>
                            <td className="px-3 py-2 align-top">
                              <button type="button" className="text-left" onClick={() => setSelectedTopicId(topic.topic_id)}>
                                <p className="font-medium text-foreground">{topic.title}</p>
                                <div className="mt-1 flex flex-wrap gap-1">
                                  <span className="rounded-md border border-primary/25 bg-primary/10 px-1.5 py-0.5 text-[10px] text-primary">
                                    {(topic.sources ?? []).join("+")}
                                  </span>
                                  {topic.sources?.map((source) => (
                                    <span key={`${topic.topic_id}-${source}`} className="inline-flex items-center gap-1 rounded-md border border-border/60 bg-background/40 px-1.5 py-0.5 text-[10px] text-muted-foreground">
                                      {sourceIcon(source)} {source}
                                    </span>
                                  ))}
                                  {topic.emerging_on_x ? (
                                    <span className="rounded-md border border-sky-400/30 bg-sky-500/10 px-1.5 py-0.5 text-[10px] text-sky-300">
                                      Emerging on X
                                    </span>
                                  ) : null}
                                  {topic.source_details?.x && typeof topic.source_details.x === "object" ? (
                                    <span className="rounded-md border border-border/60 bg-background/40 px-1.5 py-0.5 text-[10px] text-muted-foreground">
                                      X rank {String((topic.source_details.x as Record<string, unknown>).rank ?? "-")}
                                      {((topic.source_details.x as Record<string, unknown>).post_count_text)
                                        ? ` · ${String((topic.source_details.x as Record<string, unknown>).post_count_text)}`
                                        : ""}
                                    </span>
                                  ) : null}
                                  {action ? (
                                    <span className="rounded-md border border-primary/30 bg-primary/15 px-1.5 py-0.5 text-[10px] text-primary">
                                      {action}
                                    </span>
                                  ) : null}
                                </div>
                              </button>
                            </td>
                            <td className="px-3 py-2 align-top font-semibold text-primary">{Number(topic.score ?? 0).toFixed(1)}</td>
                            <td className="px-3 py-2 align-top">
                              {topicChannels.length > 0 ? (
                                <div className="flex max-w-[20rem] flex-wrap gap-1.5">
                                  {topicChannels.map((channel) => (
                                    <ChannelChip key={`${topic.topic_id}-${channel.channel_id}`} channel={channel} streamingMode={streamingMode} />
                                  ))}
                                </div>
                              ) : null}
                            </td>
                            <td className="px-3 py-2 align-top">
                              <div className="flex flex-wrap gap-1.5">
                                <Button size="sm" variant="outline" onClick={() => onSaveToIdeaVault(topic)}>Vault</Button>
                                <Button size="sm" onClick={() => onSendSingleToTopicFactory(topic)}>IdeaFactory</Button>
                                <Button size="sm" variant="outline" onClick={() => onBranchTopicToOpportunityTypes(topic)}>Branch</Button>
                              </div>
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              ) : null}

              {activeSection === "sources" ? (
                <div className="space-y-3">
                  <div className="grid gap-3 md:grid-cols-3">
                    {Object.entries(bySource).map(([source, topics]) => (
                      <div key={`source-${source}`} className="rounded-lg border border-border/60 bg-background/25 p-3">
                        <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                          Top {Math.min(10, topics.length)} {source}
                        </p>
                        <div className="space-y-2">
                          {topics.slice(0, 10).map((topic) => (
                            <div
                              key={`${source}-${topic.topic_id}`}
                              className="w-full rounded-md border border-border/60 bg-background/40 px-2 py-2 hover:border-primary/40"
                            >
                              <button
                                type="button"
                                className="w-full text-left"
                                onClick={() => setSelectedTopicId(topic.topic_id)}
                              >
                                <p className="text-sm font-medium text-foreground">{topic.title}</p>
                                <p className="mt-1 text-xs text-muted-foreground">Score {Number(topic.score ?? 0).toFixed(1)}</p>
                              </button>
                              <div className="mt-2">
                                <div className="flex flex-wrap gap-1">
                                  <Button size="sm" variant="outline" onClick={() => onSaveToIdeaVault(topic)}>
                                    Send to IdeaVault
                                  </Button>
                                  <Button size="sm" variant="outline" onClick={() => onBranchTopicToOpportunityTypes(topic)}>
                                    Branch x3
                                  </Button>
                                </div>
                              </div>
                            </div>
                          ))}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              ) : null}

              {activeSection === "channels" ? (
                <div className="space-y-3">
                  <div className="grid gap-3 md:grid-cols-2">
                    {Object.entries(byChannel).map(([channel, topics]) => (
                      <div key={channel} className="rounded-lg border border-border/60 bg-background/25 p-3">
                        <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">{displayChannelRef(channel)}</p>
                        <div className="space-y-2">
                          {topics.slice(0, 2).map((topic) => (
                            <div
                              key={`${channel}-${topic.topic_id}`}
                              className="w-full rounded-md border border-border/60 bg-background/40 px-2 py-2 hover:border-primary/40"
                            >
                              <button
                                type="button"
                                className="w-full text-left"
                                onClick={() => setSelectedTopicId(topic.topic_id)}
                              >
                                <p className="text-sm font-medium text-foreground">{topic.title}</p>
                                <p className="mt-1 text-xs text-muted-foreground">Score {Number(topic.score ?? 0).toFixed(1)}</p>
                              </button>
                              <div className="mt-2">
                                <div className="flex flex-wrap gap-1">
                                  <Button size="sm" variant="outline" onClick={() => onSaveToIdeaVault(topic)}>
                                    Send to IdeaVault
                                  </Button>
                                  <Link
                                    className="inline-flex items-center rounded-md border border-border px-2 py-1 text-xs"
                                    to={`/modules/viralcreator?title=${encodeURIComponent(topic.title)}&idea_text=${encodeURIComponent(String(topic.summary ?? ""))}&platform=youtube&output_type=dbvid`}
                                  >
                                    Create Experiment
                                  </Link>
                                </div>
                              </div>
                            </div>
                          ))}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              ) : null}

              {activeSection === "actions" ? (
                <div className="space-y-2">
                  {Object.entries(actionState).length === 0 ? (
                    <div className="rounded-lg border border-border/60 bg-background/20 p-3 text-sm text-muted-foreground">No actions yet for this session.</div>
                  ) : (
                    Object.entries(actionState).map(([topicId, info]) => (
                      <div key={topicId} className="rounded-lg border border-border/60 bg-background/30 px-3 py-2 text-xs">
                        <p className="font-medium text-foreground">{topOverall.find((item) => item.topic_id === topicId)?.title ?? topicId}</p>
                        <p className="mt-1 text-muted-foreground">Action: {info.action} {info.note ? `• ${info.note}` : ""}</p>
                      </div>
                    ))
                  )}
                </div>
              ) : null}
            </CardContent>
          </Card>
        </div>

        <div className="space-y-4">
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-[12px]">Run List</CardTitle>
            </CardHeader>
            <CardContent className="max-h-[340px] space-y-2 overflow-auto">
              {runs.length === 0 ? (
                <div className="rounded-lg border border-dashed border-border p-3 text-sm text-muted-foreground">No trend runs yet.</div>
              ) : (
                runs.map((run) => (
                  <div
                    key={run.id}
                    className={`w-full rounded-lg border px-3 py-2 text-left transition ${selectedRunId === run.id ? "border-primary bg-primary/10" : "border-border/60 bg-background/25 hover:border-primary/30"}`}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <button type="button" className="text-xs font-semibold text-foreground" onClick={() => setSelectedRunId(run.id)}>
                        {relativeTime(run.started_at)}
                      </button>
                      <span className={`rounded-full border px-2 py-0.5 text-[10px] uppercase ${
                        statusTone(run.status) === "success"
                          ? "border-success/30 bg-success/10 text-success"
                          : statusTone(run.status) === "danger"
                          ? "border-danger/30 bg-danger/10 text-danger"
                          : statusTone(run.status) === "warning"
                          ? "border-warning/30 bg-warning/10 text-warning"
                          : "border-border text-muted-foreground"
                      }`}>
                        {run.status}
                      </span>
                    </div>
                    <p className="mt-1 font-mono text-[10px] text-muted-foreground">{run.id.slice(0, 20)}</p>
                    <div className="mt-2 flex items-center gap-2">
                      {String(run.status).toUpperCase() === "RUNNING" ? (
                        <Button type="button" size="sm" variant="danger" onClick={() => onCancelRun(run.id)} disabled={cancelRunMutation.isPending}>
                          Stop
                        </Button>
                      ) : null}
                      {["QUEUED", "RUNNING"].includes(String(run.status).toUpperCase()) ? (
                        <Button type="button" size="sm" variant="outline" onClick={() => onNudgeRun(run.id)} disabled={nudgeRunMutation.isPending}>
                          Nudge
                        </Button>
                      ) : null}
                      <Button
                        type="button"
                        size="sm"
                        variant="outline"
                        onClick={() => {
                          setSelectedRunId(run.id);
                          setShowFullRunOutput(true);
                        }}
                      >
                        <ExternalLink size={12} />
                        Open
                      </Button>
                      {canDeleteRun(run.status) ? (
                        <Button type="button" size="sm" variant="danger" onClick={() => onDeleteRun(run.id)} disabled={deleteRun.isPending}>
                          <Trash2 size={12} />
                          Delete
                        </Button>
                      ) : null}
                    </div>
                  </div>
                ))
              )}
            </CardContent>
          </Card>

          <Card className="lg:sticky lg:top-20">
            <CardHeader className="pb-2">
              <CardTitle className="text-[12px]">Topic Detail</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              {!selectedTopicId ? (
                <div className="rounded-lg border border-dashed border-border p-3 text-sm text-muted-foreground">Click a topic to view details.</div>
              ) : (
                <>
                  <p className="text-sm font-semibold text-foreground">{selectedTopic?.title ?? topicDetailQuery.data?.title ?? selectedTopicId}</p>
                  <div className="rounded-lg border border-border/60 bg-background/30 p-3 text-xs text-muted-foreground">
                    {(topicDetailQuery.data?.llm_summary as string | undefined) || topicDetailQuery.data?.summary || selectedTopic?.summary || "No summary available."}
                  </div>
                  {selectedTopicChannels.length > 0 ? (
                    <div>
                      <div className="mb-1 flex items-center justify-between gap-2">
                        <p className="text-[11px] uppercase tracking-wide text-muted-foreground">Relevant channels</p>
                        <span className="text-[10px] text-muted-foreground">Top {selectedTopicChannels.length}</span>
                      </div>
                      <div className="flex flex-wrap gap-1.5">
                        {selectedTopicChannels.map((channel) => (
                          <ChannelChip key={`${selectedTopicId}-${channel.channel_id}`} channel={channel} streamingMode={streamingMode} />
                        ))}
                      </div>
                    </div>
                  ) : null}
                  <div>
                    <p className="mb-1 text-[11px] uppercase tracking-wide text-muted-foreground">Hooks</p>
                    <ul className="space-y-1 text-xs text-foreground">
                      {(topicDetailQuery.data?.hooks ?? selectedTopic?.hooks ?? []).slice(0, 5).map((hook, idx) => (
                        <li key={`${selectedTopicId}-hook-${idx}`} className="rounded-md border border-border/60 bg-background/30 px-2 py-1">
                          {String(hook)}
                        </li>
                      ))}
                    </ul>
                  </div>
                  <div>
                    <p className="mb-1 text-[11px] uppercase tracking-wide text-muted-foreground">Source breakdown</p>
                    <div className="space-y-2">
                      <ObjectReadout data={(topicDetailQuery.data?.sources as Record<string, unknown> | undefined) ?? (topicDetailQuery.data?.source_breakdown as Record<string, unknown> | undefined) ?? {}} />
                      <AdvancedRawJson data={topicDetailQuery.data?.sources ?? topicDetailQuery.data?.source_breakdown ?? {}} />
                    </div>
                  </div>
                  <div className="space-y-2">
                    <p className="text-[11px] uppercase tracking-wide text-muted-foreground">Action</p>
                    <div className="grid grid-cols-3 gap-2">
                      {ACTIONS.map((action) => (
                        <Button
                          key={`${selectedTopicId}-${action}`}
                          type="button"
                          size="sm"
                          variant={actionState[selectedTopicId]?.action === action ? "default" : "outline"}
                          onClick={() => onAction(selectedTopicId, action)}
                        >
                          {action}
                        </Button>
                      ))}
                    </div>
                    <Textarea
                      rows={3}
                      placeholder="Add note"
                      value={noteDraft[selectedTopicId] ?? ""}
                      onChange={(e) => setNoteDraft((prev) => ({ ...prev, [selectedTopicId]: e.target.value }))}
                    />
                  </div>
                </>
              )}
            </CardContent>
          </Card>

          {showFullRunOutput ? (
            <Card>
              <CardHeader className="pb-2">
                <div className="flex items-center justify-between">
                  <CardTitle className="text-[12px]">Full Run Output</CardTitle>
                  <Button type="button" size="sm" variant="outline" onClick={() => setShowFullRunOutput(false)}>
                    Close
                  </Button>
                </div>
              </CardHeader>
              <CardContent className="space-y-2">
                <ObjectReadout data={(runStatusQuery.data as Record<string, unknown> | undefined) ?? (selectedRun as unknown as Record<string, unknown> | undefined) ?? {}} />
                <ObjectReadout data={(resultsQuery.data as Record<string, unknown> | undefined) ?? {}} />
                <AdvancedRawJson title="Advanced Raw Run Output" data={{ run: runStatusQuery.data ?? selectedRun ?? {}, results: resultsQuery.data ?? {} }} />
              </CardContent>
            </Card>
          ) : null}

          {createdLinks.length > 0 ? (
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-[12px]">IdeaFactory Imports</CardTitle>
              </CardHeader>
              <CardContent className="space-y-2">
                {createdLinks.map((link, idx) => (
                  <a
                    key={`${link}-${idx}`}
                    href={link}
                    className="block rounded-md border border-border/60 bg-background/30 px-2 py-1 text-xs text-primary hover:underline"
                    target="_blank"
                    rel="noreferrer"
                  >
                    View in IdeaFactory {idx + 1}
                  </a>
                ))}
              </CardContent>
            </Card>
          ) : null}
        </div>
      </div>

      {toast ? (
        <div className="fixed bottom-4 right-4 z-50 rounded-lg border border-border bg-card px-3 py-2 text-xs text-foreground shadow-lg">
          {toast}
        </div>
      ) : null}
      {showOpenAiKeyModal ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/45 p-4" onClick={() => setShowOpenAiKeyModal(false)}>
          <div className="w-full max-w-lg rounded-xl border border-border bg-card p-4 shadow-2xl" onClick={(e) => e.stopPropagation()}>
            <div className="mb-3">
              <p className="font-display text-lg font-semibold text-foreground">Configure OpenAI API Key</p>
              <p className="text-xs text-muted-foreground mt-1">
                This run mode requires OpenAI strategy passes. Key status:{" "}
                {trendsOpenAiKeyStatus.data?.configured ? `configured (${trendsOpenAiKeyStatus.data?.masked ?? ""})` : "not configured"}.
              </p>
            </div>
            <div className="space-y-2">
              <Input
                placeholder="sk-..."
                value={openAiKeyInput}
                onChange={(e) => setOpenAiKeyInput(e.target.value)}
              />
              <div className="flex items-center justify-end gap-2">
                <Button
                  variant="ghost"
                  onClick={() => {
                    setShowOpenAiKeyModal(false);
                    setPendingStartPayload(null);
                  }}
                >
                  Cancel
                </Button>
                <Button onClick={onSaveOpenAiKeyAndContinue} disabled={setTrendsOpenAiKey.isPending || !openAiKeyInput.trim()}>
                  {setTrendsOpenAiKey.isPending ? <Loader2 size={13} className="animate-spin" /> : null}
                  Save & Continue
                </Button>
              </div>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}

function ChannelChip({ channel, streamingMode }: { channel: NormalizedTrendChannel; streamingMode: boolean }) {
  const displayName = withStreamingObfuscation(channel.channel_name, streamingMode, "channel");
  return (
    <span className="inline-flex max-w-full items-center gap-1.5 rounded-full border border-border/60 bg-background/35 px-2.5 py-1 text-[11px] text-foreground">
      <span className="truncate">{displayName}</span>
      <span className="rounded-full bg-primary/15 px-1.5 py-0.5 font-medium text-primary">
        {Math.round(channel.relevance_pct)}%
      </span>
      {channel.why ? (
        <span
          className="inline-flex shrink-0 items-center text-muted-foreground"
          title={channel.why}
          aria-label={`Why matched ${displayName}: ${channel.why}`}
        >
          <Info size={12} />
        </span>
      ) : null}
    </span>
  );
}
