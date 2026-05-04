import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Activity, Bot, Clock3, Loader2, Play, RefreshCw, Search, Sparkles } from "lucide-react";

import {
  useCancelTopicRun,
  useDeleteTopicRun,
  useStartAutoRun,
  useStartTopicRun,
  useTopicHealth,
  useTopicIdeasTop,
  useTopicProviderStats,
  useTopicRunDetail,
  useTopicRunLogs,
  useTopicRuns,
  useTopicTrending,
} from "../../shared/api/hooks";
import type { TopicRun, TopicRunAutoRequest, TopicRunStartRequest, TopicTrendingItem } from "../../shared/api/types";
import { Button } from "../../shared/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "../../shared/components/ui/card";
import { Input } from "../../shared/components/ui/input";
import { PageHeader } from "../../shared/components/ui/page-header";

type SourcePack =
  | "broad_default"
  | "business_ops"
  | "marketing"
  | "sales"
  | "field_service"
  | "ecommerce"
  | "creator"
  | "dev_tools"
  | "game_dev";

type OperatorSettings = {
  ideas_per_run: number;
  target_topics: number;
  limit_per_topic: number;
  max_comment_posts: number;
  max_comments_per_thread: number;
  llm_budget: number;
  enable_web_search: boolean;
  low_fanout_mode: boolean;
  enable_youtube: boolean;
  category_mode: "broad" | "focused" | "strict";
  category_filters: string[];
  source_pack: SourcePack;
};

type TargetedForm = {
  query: string;
  topic: string;
};

const STORAGE_KEY = "dashburg.ideafactory.operator-settings.v6";
const STAGES = ["queued", "harvest", "extract_micro", "cluster", "synthesize", "idea_generate", "rank", "finalize"];

const DEFAULT_SETTINGS: OperatorSettings = {
  ideas_per_run: 5,
  target_topics: 8,
  limit_per_topic: 20,
  max_comment_posts: 10,
  max_comments_per_thread: 40,
  llm_budget: 120,
  enable_web_search: true,
  low_fanout_mode: false,
  enable_youtube: false,
  category_mode: "broad",
  category_filters: [],
  source_pack: "broad_default",
};

const CATEGORY_OPTIONS = [
  { key: "business_ops", label: "Business Ops" },
  { key: "marketing", label: "Marketing" },
  { key: "sales", label: "Sales" },
  { key: "field_service", label: "Field Service" },
  { key: "ecommerce", label: "Ecommerce" },
  { key: "creator", label: "Creator" },
  { key: "dev_tools", label: "Dev Tools" },
  { key: "game_dev", label: "Game Dev" },
] as const;

const SOURCE_PACKS: Record<SourcePack, { label: string; topic: string; categoryDefaults: string[]; subreddits?: string[]; search_terms?: string[] }> = {
  broad_default: {
    label: "Broad Discovery",
    topic: "broad_discovery",
    categoryDefaults: CATEGORY_OPTIONS.map((row) => row.key),
  },
  business_ops: {
    label: "Business / Ops",
    topic: "business_ops",
    categoryDefaults: ["business_ops"],
  },
  marketing: {
    label: "Marketing",
    topic: "marketing",
    categoryDefaults: ["marketing"],
  },
  sales: {
    label: "Sales",
    topic: "sales",
    categoryDefaults: ["sales"],
  },
  field_service: {
    label: "Field Service",
    topic: "field_service",
    categoryDefaults: ["field_service"],
  },
  ecommerce: {
    label: "Ecommerce",
    topic: "ecommerce",
    categoryDefaults: ["ecommerce"],
  },
  creator: {
    label: "Creator",
    topic: "creator",
    categoryDefaults: ["creator"],
  },
  dev_tools: {
    label: "Dev Tools",
    topic: "dev_tools",
    categoryDefaults: ["dev_tools"],
  },
  game_dev: {
    label: "Game Dev",
    topic: "game_dev",
    categoryDefaults: ["game_dev", "dev_tools"],
    subreddits: ["gamedev", "gamedesign", "INAT", "gamedevclassifieds", "indiegames"],
    search_terms: [
      "indie game dev workflow pain",
      "unity build pipeline pain",
      "unreal blueprint debugging pain",
      "steam page launch checklist pain",
      "game QA bug triage pain",
      "player feedback tracking pain",
      "game art pipeline bottleneck",
      "multiplayer backend workflow pain",
    ],
  },
};

function clampSettings(input: Partial<OperatorSettings>): OperatorSettings {
  const sourcePack: SourcePack = ((): SourcePack => {
    const raw = String(input.source_pack ?? DEFAULT_SETTINGS.source_pack);
    if (raw in SOURCE_PACKS) return raw as SourcePack;
    return "broad_default";
  })();
  const categoryModeRaw = String(input.category_mode ?? DEFAULT_SETTINGS.category_mode).toLowerCase();
  const category_mode: "broad" | "focused" | "strict" =
    categoryModeRaw === "strict" ? "strict" : categoryModeRaw === "focused" ? "focused" : "broad";
  const category_filters = Array.isArray(input.category_filters)
    ? input.category_filters
      .map((v) => String(v).trim().toLowerCase())
      .filter((v, idx, arr) => v && arr.indexOf(v) === idx)
      .slice(0, 6)
    : DEFAULT_SETTINGS.category_filters;
  return {
    ideas_per_run: Math.max(1, Math.min(20, Number(input.ideas_per_run ?? DEFAULT_SETTINGS.ideas_per_run) || DEFAULT_SETTINGS.ideas_per_run)),
    target_topics: Math.max(1, Math.min(25, Number(input.target_topics ?? DEFAULT_SETTINGS.target_topics) || DEFAULT_SETTINGS.target_topics)),
    limit_per_topic: Math.max(1, Math.min(100, Number(input.limit_per_topic ?? DEFAULT_SETTINGS.limit_per_topic) || DEFAULT_SETTINGS.limit_per_topic)),
    max_comment_posts: Math.max(1, Math.min(50, Number(input.max_comment_posts ?? DEFAULT_SETTINGS.max_comment_posts) || DEFAULT_SETTINGS.max_comment_posts)),
    max_comments_per_thread: Math.max(1, Math.min(200, Number(input.max_comments_per_thread ?? DEFAULT_SETTINGS.max_comments_per_thread) || DEFAULT_SETTINGS.max_comments_per_thread)),
    llm_budget: Math.max(20, Math.min(500, Number(input.llm_budget ?? DEFAULT_SETTINGS.llm_budget) || DEFAULT_SETTINGS.llm_budget)),
    enable_web_search: Boolean(input.enable_web_search ?? DEFAULT_SETTINGS.enable_web_search),
    low_fanout_mode: Boolean(input.low_fanout_mode ?? DEFAULT_SETTINGS.low_fanout_mode),
    enable_youtube: Boolean(input.enable_youtube ?? DEFAULT_SETTINGS.enable_youtube),
    category_mode,
    category_filters,
    source_pack: sourcePack,
  };
}

function loadSettings(): OperatorSettings {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return DEFAULT_SETTINGS;
    return clampSettings(JSON.parse(raw) as Partial<OperatorSettings>);
  } catch {
    return DEFAULT_SETTINGS;
  }
}

function defaultsForPack(pack: SourcePack): Pick<OperatorSettings, "category_mode" | "category_filters"> {
  if (pack === "broad_default") {
    return { category_mode: "broad", category_filters: [] };
  }
  const defaults = SOURCE_PACKS[pack]?.categoryDefaults ?? [];
  return {
    category_mode: defaults.length > 1 ? "focused" : "strict",
    category_filters: defaults.slice(0, 4),
  };
}

function getString(value: unknown, fallback = "-"): string {
  if (typeof value === "string" && value.trim()) return value;
  if (typeof value === "number") return String(value);
  return fallback;
}

function getNumber(value: unknown, fallback = 0): number {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string") {
    const parsed = Number(value);
    if (Number.isFinite(parsed)) return parsed;
  }
  return fallback;
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" ? (value as Record<string, unknown>) : {};
}

function asRows(value: unknown): Array<Record<string, unknown>> {
  if (Array.isArray(value)) return value as Array<Record<string, unknown>>;
  const obj = asRecord(value);
  for (const key of ["items", "rows", "ideas", "data", "results"]) {
    if (Array.isArray(obj[key])) return obj[key] as Array<Record<string, unknown>>;
  }
  return [];
}

function formatDate(value: unknown): string {
  if (typeof value !== "string" || !value.trim()) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString();
}

function relativeTime(value: unknown): string {
  if (typeof value !== "string" || !value.trim()) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  const diffSeconds = Math.max(0, Math.floor((Date.now() - date.getTime()) / 1000));
  if (diffSeconds < 60) return `${diffSeconds}s ago`;
  if (diffSeconds < 3600) return `${Math.floor(diffSeconds / 60)}m ago`;
  if (diffSeconds < 86400) return `${Math.floor(diffSeconds / 3600)}h ago`;
  return `${Math.floor(diffSeconds / 86400)}d ago`;
}

function sortRuns(rows: TopicRun[]): TopicRun[] {
  return [...rows].sort((a, b) => {
    const aUpdated = new Date(String(a.updated_at ?? a.started_at ?? a.created_at ?? "")).getTime() || 0;
    const bUpdated = new Date(String(b.updated_at ?? b.started_at ?? b.created_at ?? "")).getTime() || 0;
    if (bUpdated !== aUpdated) return bUpdated - aUpdated;
    const aStarted = new Date(String(a.started_at ?? a.created_at ?? "")).getTime() || 0;
    const bStarted = new Date(String(b.started_at ?? b.created_at ?? "")).getTime() || 0;
    if (bStarted !== aStarted) return bStarted - aStarted;
    return String(b.id ?? b.run_id ?? "").localeCompare(String(a.id ?? a.run_id ?? ""));
  });
}

function statusTone(status: string): string {
  const value = status.toLowerCase();
  if (["running", "queued", "cancel_requested"].includes(value)) return "border-primary/30 bg-primary/10 text-primary";
  if (["succeeded", "completed", "success", "done"].includes(value)) return "border-success/30 bg-success/10 text-success";
  if (["failed", "error"].includes(value)) return "border-danger/30 bg-danger/10 text-danger";
  return "border-border bg-background/40 text-muted-foreground";
}

function healthTone(ok: boolean, label: string): string {
  if (!ok) return "border-danger/30 bg-danger/10 text-danger";
  if (label.toLowerCase().includes("not_found")) return "border-warning/30 bg-warning/10 text-warning";
  return "border-success/30 bg-success/10 text-success";
}

function MetricTile({ label, value, hint }: { label: string; value: string | number; hint?: string }) {
  return (
    <div className="rounded-xl border border-border bg-background/30 p-3">
      <p className="text-[10px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">{label}</p>
      <p className="mt-1 text-xl font-semibold text-foreground">{value}</p>
      {hint ? <p className="mt-1 text-[11px] text-muted-foreground">{hint}</p> : null}
    </div>
  );
}

function StageChip({ label, active, failed }: { label: string; active: boolean; failed?: boolean }) {
  const classes = failed
    ? "border-danger/40 bg-danger/10 text-danger"
    : active
      ? "border-primary/40 bg-primary/10 text-primary"
      : "border-border/60 bg-background/30 text-muted-foreground";
  return <div className={`rounded-lg border px-2 py-2 text-center text-[11px] ${classes}`}>{label}</div>;
}

export function AppGenPage() {
  const nav = useNavigate();

  const [settings, setSettings] = useState<OperatorSettings>(() => loadSettings());
  const [targetedForm, setTargetedForm] = useState<TargetedForm>({ query: "", topic: "general" });
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [selectedIdea, setSelectedIdea] = useState<Record<string, unknown> | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const [logOffset, setLogOffset] = useState(0);
  const [logLines, setLogLines] = useState<string[]>([]);

  const topicHealthQuery = useTopicHealth(true);
  const providerStatsQuery = useTopicProviderStats(80, true);
  const trendingQuery = useTopicTrending(6, true);
  const runsQuery = useTopicRuns(80, true);
  const runRows = useMemo(() => sortRuns(runsQuery.data ?? []), [runsQuery.data]);

  useEffect(() => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(settings));
  }, [settings]);

  useEffect(() => {
    if (!selectedRunId && runRows.length > 0) {
      const first = getString(runRows[0].id ?? runRows[0].run_id, "");
      if (first) setSelectedRunId(first);
    }
  }, [runRows, selectedRunId]);

  useEffect(() => {
    setLogOffset(0);
    setLogLines([]);
    setSelectedIdea(null);
  }, [selectedRunId]);

  const selectedRun = useMemo(
    () => runRows.find((row) => getString(row.id ?? row.run_id, "") === selectedRunId) ?? null,
    [runRows, selectedRunId],
  );

  const runDetailQuery = useTopicRunDetail(selectedRunId, Boolean(selectedRunId));
  const ideasTopQuery = useTopicIdeasTop(selectedRunId, 12);
  const logsQuery = useTopicRunLogs(selectedRunId, logOffset, 200, Boolean(selectedRunId));

  useEffect(() => {
    const data = logsQuery.data;
    if (!data) return;
    const nextOffset = getNumber(data.next_offset, logOffset);
    const lines = Array.isArray(data.lines) ? data.lines.map(String) : [];
    if (nextOffset > logOffset) {
      setLogLines((prev) => [...prev, ...lines].slice(-1500));
      setLogOffset(nextOffset);
      return;
    }
    if (logOffset === 0 && lines.length > 0) {
      setLogLines(lines.slice(-1500));
    }
  }, [logsQuery.data, logOffset]);

  const startAuto = useStartAutoRun();
  const startTargeted = useStartTopicRun();
  const cancelRun = useCancelTopicRun();
  const deleteRun = useDeleteTopicRun();

  const preset = SOURCE_PACKS[settings.source_pack];
  const estimatedComments = settings.max_comment_posts * settings.max_comments_per_thread;
  const estimatedSignals = settings.target_topics * settings.limit_per_topic;
  const estimatedOpenAiCalls = Math.max(6, Math.min(24, Math.max(1, Math.floor(settings.ideas_per_run / 3)))) + Math.max(1, Math.ceil(Math.max(1, settings.ideas_per_run) / 12));
  const estimatedWebQueries = settings.enable_web_search ? (settings.low_fanout_mode ? 1 : 3) : 0;
  const estimatedWebResults = settings.enable_web_search ? estimatedWebQueries * (settings.low_fanout_mode ? 3 : 5) : 0;

  const health = asRecord(topicHealthQuery.data);
  const providerItems = asRows(providerStatsQuery.data).slice(0, 12);
  const runDetail = asRecord(runDetailQuery.data);
  const counts = asRecord(runDetail.counts);
  const outputs = asRecord(runDetail.outputs);
  const totalsJson = asRecord(runDetail.totals_json);
  const telemetry = asRecord(runDetail.telemetry);
  const llmCalls = asRecord(telemetry.llm_calls);
  const llmExpected = asRecord(llmCalls.expected);
  const llmActual = asRecord(llmCalls.actual);
  const llmApiHealth = asRecord(llmCalls.api_health);
  const endpointStats = asRecord(llmCalls.endpoint_stats);
  const stageStatuses = asRecord(telemetry.stage_statuses);
  const sourceCounts = asRecord(telemetry.source_counts);
  const categoryCounts = asRecord(totalsJson.category_candidate_counts);
  const candidateThreadCounts = asRecord(telemetry.candidate_thread_counts);
  const shortlistedThreadCounts = asRecord(telemetry.shortlisted_thread_counts);
  const commentFilterCounts = asRecord(telemetry.comment_filter_counts);
  const droppedCommentCounts = asRecord(telemetry.dropped_comment_counts);
  const selectionReasons = asRecord(telemetry.selection_reasons);
  const threadSelectionReasons = asRows(selectionReasons.threads);
  const commentSelectionReasons = asRows(selectionReasons.comments);
  const statusReport = asRecord(asRecord(runDetail._dashburg).status_report);
  const outputIdeas = asRows(outputs.ideas);
  const effectiveIdeas = outputIdeas.length > 0 ? outputIdeas : (selectedRunId ? [] : (ideasTopQuery.data ?? []));
  const outputSignals = asRows(outputs.signals).slice(0, 5);
  const outputProblems = asRows(outputs.micro_problems).slice(0, 5);
  const sizingRows = asRows(telemetry.sizing);
  const endpointRows = Object.entries(endpointStats).map(([endpoint, value]) => ({ endpoint, row: asRecord(value) }));
  const currentStatus = getString(runDetail.status ?? selectedRun?.status, "unknown");
  const heartbeatAt = getString(runDetail.heartbeat_at ?? selectedRun?.heartbeat_at ?? selectedRun?.updated_at ?? "", "");
  const heartbeatAgeSeconds = getNumber(statusReport.heartbeat_age_seconds, heartbeatAt ? Math.max(0, Math.floor((Date.now() - new Date(heartbeatAt).getTime()) / 1000)) : 0);
  const heartbeatStale = heartbeatAgeSeconds > 45;
  const topicInsightsReady = ["succeeded", "completed", "success", "done"].includes(currentStatus.toLowerCase());

  const autoPayload: TopicRunAutoRequest = {
    ideas_per_run: settings.ideas_per_run,
    target_topics: settings.target_topics,
    limit_per_topic: settings.limit_per_topic,
    target_final_ideas: settings.ideas_per_run,
    enable_youtube: settings.enable_youtube,
    max_posts_per_source: settings.target_topics,
    max_comment_posts: settings.max_comment_posts,
    max_comments_per_thread: settings.max_comments_per_thread,
    ingest_overrides: {
      reddit_max_posts: settings.target_topics,
      reddit_max_comment_posts: settings.max_comment_posts,
      reddit_max_comments_per_post: settings.max_comments_per_thread,
      llm_max_calls_per_run: settings.llm_budget,
    },
    subreddits: preset.subreddits,
    search_terms: preset.search_terms,
    use_default_subreddits: settings.source_pack === "broad_default",
    use_default_search_terms: settings.source_pack === "broad_default",
    enable_reddit: true,
    enable_web_search: settings.enable_web_search,
    low_fanout_mode: settings.low_fanout_mode,
    category_mode: settings.category_mode,
    category_filters: settings.category_filters,
  };

  const startAutoRun = async () => {
    setToast("Starting research pipeline...");
    try {
      const result = await startAuto.mutateAsync(autoPayload);
      const runId = getString(asRecord(result).run_id ?? asRecord(result).id, "");
      if (runId) setSelectedRunId(runId);
      setToast(runId ? `Run queued: ${runId}` : "Run queued");
      runsQuery.refetch();
    } catch (error) {
      setToast(`Start failed: ${String(error)}`);
    }
  };

  const startTargetedRun = async () => {
    const query = targetedForm.query.trim();
    if (!query) {
      setToast("Enter a problem or market to research.");
      return;
    }
    const payload: TopicRunStartRequest = {
      query,
      topic: targetedForm.topic.trim() || preset.topic,
      limit: Math.max(20, settings.limit_per_topic * Math.max(1, Math.min(4, settings.target_topics))),
      enable_youtube: settings.enable_youtube,
      target_final_ideas: settings.ideas_per_run,
      enable_pain_graph: true,
      ingest_overrides: {
        reddit_max_posts: settings.target_topics,
        reddit_max_comment_posts: settings.max_comment_posts,
        reddit_max_comments_per_post: settings.max_comments_per_thread,
        llm_max_calls_per_run: settings.llm_budget,
      },
      subreddits: preset.subreddits,
      search_terms: preset.search_terms,
      use_default_subreddits: settings.source_pack === "broad_default",
      use_default_search_terms: settings.source_pack === "broad_default",
      enable_reddit: true,
      enable_web_search: settings.enable_web_search,
      low_fanout_mode: settings.low_fanout_mode,
      category_mode: settings.category_mode,
      category_filters: settings.category_filters,
    };
    setToast("Starting targeted research...");
    try {
      const result = await startTargeted.mutateAsync(payload);
      const runId = getString(asRecord(result).run_id ?? asRecord(result).id, "");
      if (runId) setSelectedRunId(runId);
      setToast(runId ? `Targeted run queued: ${runId}` : "Targeted run queued");
      runsQuery.refetch();
    } catch (error) {
      setToast(`Targeted run failed: ${String(error)}`);
    }
  };

  return (
    <div className="space-y-4">
      <PageHeader
        compact
        title="IdeaFactory"
        description="Live YC cockpit for bounded intake, provider health, LLM activity, and ranked idea output."
        meta={toast ?? `Local route: Redis Ollama · Quick fallback: gpt-4o-mini · Large synthesis: gpt-4o`}
        actions={
          <Button
            variant="outline"
            onClick={() => {
              topicHealthQuery.refetch();
              providerStatsQuery.refetch();
              trendingQuery.refetch();
              runsQuery.refetch();
              runDetailQuery.refetch();
              ideasTopQuery.refetch();
            }}
            disabled={runsQuery.isFetching || runDetailQuery.isFetching}
          >
            <RefreshCw size={13} className={runsQuery.isFetching || runDetailQuery.isFetching ? "animate-spin" : ""} />
            Refresh
          </Button>
        }
      >
        <div className="grid gap-2 md:grid-cols-4">
          <MetricTile label="Idea Target" value={settings.ideas_per_run} hint="final ranked ideas" />
          <MetricTile label="Signal Budget" value={estimatedSignals} hint={`${settings.target_topics} topics x ${settings.limit_per_topic}`} />
          <MetricTile label="Comment Budget" value={estimatedComments} hint={`${settings.max_comment_posts} posts x ${settings.max_comments_per_thread}`} />
          <MetricTile label="OpenAI Budget" value={settings.llm_budget} hint={`est. ${estimatedOpenAiCalls} cloud calls`} />
          <MetricTile label="Selected Pack" value={preset.label} hint="source preset and prompt framing" />
        </div>
      </PageHeader>

      <div className="grid gap-4 xl:grid-cols-[330px_minmax(0,1fr)_320px]">
        <div className="space-y-4">
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="flex items-center gap-1.5">
                <Search size={14} />
                Compose Run
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="rounded-xl border border-border bg-background/30 p-3">
                <p className="text-[10px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">Preset Pack</p>
                <select
                  className="mt-2 w-full rounded-lg border border-border bg-input px-3 py-2 text-sm text-foreground"
                  value={settings.source_pack}
                  onChange={(e) => {
                    const nextPack = e.target.value as SourcePack;
                    const defaults = defaultsForPack(nextPack);
                    setSettings((prev) => clampSettings({ ...prev, source_pack: nextPack, ...defaults }));
                  }}
                >
                  <option value="broad_default">Broad Discovery</option>
                  <option value="business_ops">Business / Ops</option>
                  <option value="marketing">Marketing</option>
                  <option value="sales">Sales</option>
                  <option value="field_service">Field Service</option>
                  <option value="ecommerce">Ecommerce</option>
                  <option value="creator">Creator</option>
                  <option value="dev_tools">Dev Tools</option>
                  <option value="game_dev">Game Dev</option>
                </select>
                <p className="mt-2 text-xs text-muted-foreground">
                  {settings.source_pack === "broad_default"
                    ? "Breadth-first sampling across categories. Best default for discovery."
                    : settings.source_pack === "game_dev"
                      ? "Focused game-dev intake sources and pain queries."
                      : "Focused category run with soft balancing enabled."}
                </p>
              </div>

              <div className="rounded-xl border border-border bg-background/30 p-3">
                <p className="text-[10px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">Category Mode</p>
                <div className="mt-2 grid gap-2 sm:grid-cols-3">
                  {(["broad", "focused", "strict"] as const).map((mode) => (
                    <button
                      key={mode}
                      type="button"
                      className={`rounded-lg border px-2 py-1.5 text-xs ${settings.category_mode === mode ? "border-primary/40 bg-primary/10 text-primary" : "border-border bg-background/30 text-muted-foreground"}`}
                      onClick={() => setSettings((prev) => clampSettings({ ...prev, category_mode: mode }))}
                    >
                      {mode}
                    </button>
                  ))}
                </div>
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {CATEGORY_OPTIONS.map((row) => {
                    const active = settings.category_filters.includes(row.key);
                    return (
                      <button
                        key={row.key}
                        type="button"
                        className={`rounded border px-2 py-1 text-[11px] ${active ? "border-primary/40 bg-primary/10 text-primary" : "border-border bg-background/30 text-muted-foreground"}`}
                        onClick={() =>
                          setSettings((prev) => {
                            const next = active
                              ? prev.category_filters.filter((item) => item !== row.key)
                              : [...prev.category_filters, row.key].slice(0, 4);
                            return clampSettings({ ...prev, category_filters: next });
                          })
                        }
                      >
                        {row.label}
                      </button>
                    );
                  })}
                </div>
              </div>

              <div className="grid gap-2 sm:grid-cols-2">
                <label className="text-xs text-muted-foreground">
                  Ideas
                  <Input type="number" value={settings.ideas_per_run} onChange={(e) => setSettings((prev) => clampSettings({ ...prev, ideas_per_run: Number(e.target.value) }))} />
                </label>
                <label className="text-xs text-muted-foreground">
                  Topics
                  <Input type="number" value={settings.target_topics} onChange={(e) => setSettings((prev) => clampSettings({ ...prev, target_topics: Number(e.target.value) }))} />
                </label>
                <label className="text-xs text-muted-foreground">
                  Items / Topic
                  <Input type="number" value={settings.limit_per_topic} onChange={(e) => setSettings((prev) => clampSettings({ ...prev, limit_per_topic: Number(e.target.value) }))} />
                </label>
                <label className="text-xs text-muted-foreground">
                  Comment Posts
                  <Input type="number" value={settings.max_comment_posts} onChange={(e) => setSettings((prev) => clampSettings({ ...prev, max_comment_posts: Number(e.target.value) }))} />
                </label>
                <label className="text-xs text-muted-foreground sm:col-span-2">
                  Comments / Post
                  <Input type="number" value={settings.max_comments_per_thread} onChange={(e) => setSettings((prev) => clampSettings({ ...prev, max_comments_per_thread: Number(e.target.value) }))} />
                </label>
                <label className="text-xs text-muted-foreground sm:col-span-2">
                  OpenAI Budget
                  <Input type="number" value={settings.llm_budget} onChange={(e) => setSettings((prev) => clampSettings({ ...prev, llm_budget: Number(e.target.value) }))} />
                </label>
              </div>

              <div className="flex flex-wrap gap-2 text-xs">
                <label className="inline-flex items-center gap-2 rounded border border-border px-2 py-1.5">
                  <input type="checkbox" checked={settings.enable_web_search} onChange={(e) => setSettings((prev) => clampSettings({ ...prev, enable_web_search: e.target.checked }))} />
                  Web search
                </label>
                <label className="inline-flex items-center gap-2 rounded border border-border px-2 py-1.5">
                  <input
                    type="checkbox"
                    checked={settings.low_fanout_mode}
                    disabled={!settings.enable_web_search}
                    onChange={(e) => setSettings((prev) => clampSettings({ ...prev, low_fanout_mode: e.target.checked }))}
                  />
                  Low-fanout web
                </label>
                <label className="inline-flex items-center gap-2 rounded border border-border px-2 py-1.5">
                  <input type="checkbox" checked={settings.enable_youtube} onChange={(e) => setSettings((prev) => clampSettings({ ...prev, enable_youtube: e.target.checked }))} />
                  YouTube
                </label>
              </div>

              <div className="rounded-xl border border-border bg-background/30 p-3 text-xs text-muted-foreground">
                Effective bound: up to <span className="font-medium text-foreground">{estimatedSignals}</span> source rows and <span className="font-medium text-foreground">{estimatedComments}</span> Reddit comments before filtering.
                <br />
                Web search fanout: <span className="font-medium text-foreground">{estimatedWebQueries}</span> queries / <span className="font-medium text-foreground">{estimatedWebResults}</span> results max.
                <br />
                OpenAI budget: <span className="font-medium text-foreground">{settings.llm_budget}</span> max, with an estimated <span className="font-medium text-foreground">{estimatedOpenAiCalls}</span> cloud calls for this run shape. Local Ollama calls are not capped by this setting.
              </div>

              <div className="flex gap-2">
                <Button onClick={startAutoRun} disabled={startAuto.isPending}>
                  {startAuto.isPending ? <Loader2 size={13} className="animate-spin" /> : <Play size={13} />}
                  Run Auto
                </Button>
              </div>

              <div className="rounded-xl border border-border bg-background/30 p-3">
                <p className="text-[10px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">Targeted Research</p>
                <div className="mt-2 space-y-2">
                  <Input placeholder="AI scheduling for HVAC techs" value={targetedForm.query} onChange={(e) => setTargetedForm((prev) => ({ ...prev, query: e.target.value }))} />
                  <Input placeholder="topic label" value={targetedForm.topic} onChange={(e) => setTargetedForm((prev) => ({ ...prev, topic: e.target.value }))} />
                  <Button variant="outline" onClick={startTargetedRun} disabled={startTargeted.isPending}>
                    {startTargeted.isPending ? <Loader2 size={13} className="animate-spin" /> : <Sparkles size={13} />}
                    Run Targeted
                  </Button>
                </div>
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="flex items-center gap-1.5">
                <Activity size={14} />
                System Health
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              <div className={`rounded-xl border px-3 py-2 text-xs ${healthTone(Boolean(health.ok ?? true), getString(health.reason ?? health.status, "ok"))}`}>
                Topicsite health: {getString(health.status ?? health.reason, Boolean(health.ok ?? true) ? "ok" : "degraded")}
              </div>
              <div className="rounded-xl border border-border bg-background/30 p-3 text-xs text-muted-foreground">
                Ollama route: <span className="font-medium text-foreground">Redis broker</span>
                <br />
                OpenAI quick fallback: <span className="font-medium text-foreground">gpt-4o-mini</span>
                <br />
                Large synthesis: <span className="font-medium text-foreground">gpt-4o</span>
              </div>
              <div className="space-y-2">
                {providerItems.length === 0 ? <p className="text-xs text-muted-foreground">No provider telemetry yet.</p> : null}
                {providerItems.slice(0, 6).map((row, index) => {
                  const provider = getString(row.provider, `provider-${index}`);
                  const success = getNumber(row.succeeded ?? row.calls, 0);
                  const failed = getNumber(row.failed ?? row.errors, 0);
                  return (
                    <div key={provider} className="rounded-lg border border-border/70 bg-background/25 px-3 py-2 text-xs">
                      <div className="flex items-center justify-between gap-2">
                        <span className="font-medium text-foreground">{provider}</span>
                        <span className="text-muted-foreground">ok {success} · fail {failed}</span>
                      </div>
                    </div>
                  );
                })}
              </div>
            </CardContent>
          </Card>
        </div>

        <div className="space-y-4">
          <Card>
            <CardHeader className="pb-2">
              <div className="flex items-center justify-between gap-2">
                <CardTitle>Live Cockpit</CardTitle>
                {selectedRunId ? <span className="text-xs text-muted-foreground">{selectedRunId}</span> : null}
              </div>
            </CardHeader>
            <CardContent className="space-y-4">
              {!selectedRunId ? (
                <div className="rounded-xl border border-dashed border-border p-4 text-sm text-muted-foreground">Select a run to inspect intake, LLM activity, and output.</div>
              ) : runDetailQuery.isLoading ? (
                <div className="flex items-center gap-2 text-sm text-muted-foreground">
                  <Loader2 size={14} className="animate-spin" /> Loading run detail...
                </div>
              ) : (
                <>
                  <div className="flex flex-wrap items-center gap-2">
                    <span className={`rounded border px-2 py-1 text-xs ${statusTone(currentStatus)}`}>{currentStatus}</span>
                    <span className="rounded border border-border px-2 py-1 text-xs text-muted-foreground">stage {getString(runDetail.stage ?? asRecord(runDetail.progress).stage, "n/a")}</span>
                    <span className="rounded border border-border px-2 py-1 text-xs text-muted-foreground">
                      heartbeat {heartbeatAt ? relativeTime(heartbeatAt) : "-"}
                    </span>
                    {heartbeatStale ? <span className="rounded border border-warning/30 bg-warning/10 px-2 py-1 text-xs text-warning">stale heartbeat</span> : null}
                    <Button size="sm" variant="outline" onClick={() => selectedRunId && cancelRun.mutate(selectedRunId)} disabled={cancelRun.isPending}>
                      Cancel
                    </Button>
                    <Button size="sm" variant="danger" onClick={() => selectedRunId && deleteRun.mutate(selectedRunId)} disabled={deleteRun.isPending}>
                      Delete
                    </Button>
                    <Button size="sm" variant="outline" onClick={() => nav(`/modules/topic-insights?run_id=${encodeURIComponent(selectedRunId)}`)} disabled={!topicInsightsReady}>
                      <Bot size={12} />
                      TopicInsights
                    </Button>
                  </div>

                  <div className="grid gap-2 sm:grid-cols-4">
                    {STAGES.map((stage) => {
                      const stageStatus = getString(asRecord(stageStatuses[stage]).status, "");
                      const active = Boolean(stageStatus) || getString(runDetail.stage ?? asRecord(runDetail.progress).stage, "").toLowerCase() === stage;
                      return <StageChip key={stage} label={stage} active={active} failed={stageStatus === "failed" || stageStatus === "error"} />;
                    })}
                  </div>

                  <div className="rounded-xl border border-border bg-background/30 p-3">
                    <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-muted-foreground">
                      <span>
                        Progress <span className="font-medium text-foreground">{Math.round(getNumber(runDetail.progress_pct ?? asRecord(runDetail.progress).percent, 0))}%</span>
                      </span>
                      <span>
                        Blocked <span className="font-medium text-foreground">{getString(statusReport.blocked_reason, "no")}</span>
                      </span>
                    </div>
                    <div className="mt-2 h-2 w-full overflow-hidden rounded bg-background/70">
                      <div className="h-full rounded bg-primary transition-all" style={{ width: `${Math.max(0, Math.min(100, getNumber(runDetail.progress_pct ?? asRecord(runDetail.progress).percent, 0)))}%` }} />
                    </div>
                  </div>

                  <div className="grid gap-3 xl:grid-cols-2">
                    <div className="rounded-xl border border-border bg-background/30 p-3">
                      <p className="text-[10px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">Research Intake</p>
                      <div className="mt-3 grid gap-2 sm:grid-cols-2">
                        <MetricTile label="Signals" value={getNumber(counts.signals, 0)} />
                        <MetricTile label="Micro" value={getNumber(counts.micro_problems, 0)} />
                          <MetricTile label="Clusters" value={getNumber(counts.clusters, 0)} />
                          <MetricTile label="Ideas" value={getNumber(counts.ideas, 0)} />
                      </div>
                      <div className="mt-3 grid gap-2 sm:grid-cols-2">
                        <MetricTile label="Candidates" value={getNumber(candidateThreadCounts.reddit_fetched, 0)} hint="threads fetched before shortlist" />
                        <MetricTile label="Shortlisted" value={getNumber(candidateThreadCounts.selected ?? shortlistedThreadCounts.reddit, 0)} hint={Boolean(telemetry.backfill_used) ? "backfill used" : "no backfill"} />
                        <MetricTile label="Comments Fetched" value={getNumber(commentFilterCounts.fetched, 0)} />
                        <MetricTile label="Comments Kept" value={getNumber(commentFilterCounts.final_kept ?? commentFilterCounts.llm_kept ?? commentFilterCounts.heuristic_kept, 0)} hint="after filtering / triage" />
                      </div>
                      <div className="mt-3 grid gap-2 sm:grid-cols-2 text-xs text-muted-foreground">
                        {Object.entries(sourceCounts).map(([source, count]) => (
                          <div key={source} className="rounded-lg border border-border/70 bg-background/20 px-3 py-2">
                            {source}: <span className="font-medium text-foreground">{getNumber(count, 0)}</span>
                          </div>
                        ))}
                        {Object.keys(sourceCounts).length === 0 ? <div>No intake telemetry yet.</div> : null}
                      </div>
                      {Object.keys(categoryCounts).length > 0 ? (
                        <div className="mt-3 rounded-lg border border-border/70 bg-background/20 px-3 py-2 text-xs text-muted-foreground">
                          Category coverage:
                          {" "}
                          {Object.entries(categoryCounts)
                            .map(([category, count]) => `${category} ${getNumber(count, 0)}`)
                            .join(" · ")}
                        </div>
                      ) : null}
                      {(Object.keys(droppedCommentCounts).length > 0 || threadSelectionReasons.length > 0 || commentSelectionReasons.length > 0) ? (
                        <div className="mt-3 space-y-2 text-xs text-muted-foreground">
                          {Object.keys(droppedCommentCounts).length > 0 ? (
                            <div className="rounded-lg border border-border/70 bg-background/20 px-3 py-2">
                              Dropped comments:
                              {" "}
                              {Object.entries(droppedCommentCounts)
                                .map(([reason, count]) => `${reason} ${getNumber(count, 0)}`)
                                .join(" · ")}
                            </div>
                          ) : null}
                          {threadSelectionReasons.length > 0 ? (
                            <div className="rounded-lg border border-border/70 bg-background/20 px-3 py-2">
                              Top thread picks:
                              {" "}
                              {threadSelectionReasons
                                .slice(0, 3)
                                .map((row) => `${getString(row.source_id, "thread")} (${getString(row.llm_reason ?? row.heuristic_reason, "selected")})`)
                                .join(" · ")}
                            </div>
                          ) : null}
                          {commentSelectionReasons.length > 0 ? (
                            <div className="rounded-lg border border-border/70 bg-background/20 px-3 py-2">
                              Kept comments:
                              {" "}
                              {commentSelectionReasons
                                .slice(0, 3)
                                .map((row) => `${getString(row.source_id, "comment")} ${getNumber(row.score, 0).toFixed(1)}`)
                                .join(" · ")}
                            </div>
                          ) : null}
                        </div>
                      ) : null}
                    </div>

                    <div className="rounded-xl border border-border bg-background/30 p-3">
                      <p className="text-[10px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">LLM Activity</p>
                      <div className="mt-3 space-y-2 text-xs text-muted-foreground">
                        <div>Logical calls: <span className="font-medium text-foreground">{getNumber(llmActual.logical_completed, 0)}/{Math.max(getNumber(llmExpected.total_logical_calls, 0), getNumber(llmActual.logical_started, 0))}</span></div>
                        <div>HTTP attempts: <span className="font-medium text-foreground">{getNumber(llmActual.http_attempt_started, 0)}</span> · ok <span className="font-medium text-foreground">{getNumber(llmActual.http_attempt_succeeded, 0)}</span> · fail <span className="font-medium text-foreground">{getNumber(llmActual.http_attempt_failed, 0)}</span></div>
                        <div>Retries used: <span className="font-medium text-foreground">{getNumber(llmActual.retries, 0)}</span></div>
                        <div>Current provider: <span className="font-medium text-foreground">{getString(telemetry.current_provider ?? llmApiHealth.last_provider, "-")}</span></div>
                        <div>Current model: <span className="font-medium text-foreground">{getString(telemetry.current_model, "-")}</span></div>
                        <div>Current operation: <span className="font-medium text-foreground">{getString(telemetry.current_operation ?? llmApiHealth.last_operation, "-")}</span></div>
                        <div>Last API: <span className="font-medium text-foreground">{getString(llmApiHealth.last_http_event, "-")}</span> @ <span className="font-medium text-foreground">{getString(llmApiHealth.last_http_endpoint, "-")}</span></div>
                        {getString(llmApiHealth.last_http_error, "") ? <div className="text-danger">{getString(llmApiHealth.last_http_error, "")}</div> : null}
                      </div>
                      {endpointRows.length > 0 ? (
                        <div className="mt-3 space-y-2">
                          {endpointRows.map(({ endpoint, row }) => (
                            <div key={endpoint} className="rounded-lg border border-border/70 bg-background/20 px-3 py-2 text-xs text-muted-foreground">
                              <span className="font-medium text-foreground">{endpoint}</span> · start {getNumber(row.started, 0)} · ok {getNumber(row.succeeded, 0)} · fail {getNumber(row.failed, 0)}
                              {getString(row.lastError, "") ? <> · <span className="text-danger">{getString(row.lastError, "")}</span></> : null}
                            </div>
                          ))}
                        </div>
                      ) : null}
                    </div>
                  </div>

                  <div className="grid gap-3 xl:grid-cols-[1.15fr_0.85fr]">
                    <div className="rounded-xl border border-border bg-background/30 p-3">
                      <div className="mb-2 flex items-center justify-between text-xs text-muted-foreground">
                        <span>Logs and events</span>
                        {logsQuery.isFetching ? <Loader2 size={12} className="animate-spin" /> : null}
                      </div>
                      <pre className="max-h-[300px] overflow-auto rounded-lg bg-background/70 p-3 text-xs leading-relaxed text-foreground/90">
                        {logLines.length > 0 ? logLines.join("\n") : "Waiting for logs..."}
                      </pre>
                    </div>

                    <div className="space-y-3">
                      <div className="rounded-xl border border-border bg-background/30 p-3">
                        <p className="text-[10px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">Sizing</p>
                        <div className="mt-2 space-y-2 text-xs text-muted-foreground">
                          {sizingRows.length === 0 ? <p>No sizing telemetry yet.</p> : null}
                          {sizingRows.slice(-5).map((row, index) => (
                            <div key={`${getString(row.stage, `size-${index}`)}-${index}`} className="rounded-lg border border-border/70 bg-background/20 px-3 py-2">
                              {getString(row.stage, "stage")} · batches {getNumber(row.batches, 0)} · prompt chars est {getNumber(row.prompt_chars_est, 0)}
                            </div>
                          ))}
                        </div>
                      </div>

                      <div className="rounded-xl border border-border bg-background/30 p-3">
                        <p className="text-[10px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">Live Output Snapshot</p>
                        <p className="mt-1 text-[11px] text-muted-foreground">
                          {effectiveIdeas.length} idea{effectiveIdeas.length === 1 ? "" : "s"} in this run snapshot
                        </p>
                        <div className="mt-2 space-y-2">
                          {[...effectiveIdeas].sort((a, b) => getNumber(b.score, 0) - getNumber(a.score, 0)).slice(0, 12).map((row, index) => (
                            <button
                              type="button"
                              onClick={() => setSelectedIdea(row)}
                              key={`${getString(row.id ?? row.idea_id, `idea-${index}`)}`}
                              className="w-full rounded-lg border border-border/70 bg-background/20 p-3 text-left hover:border-primary/40"
                            >
                              <div className="flex items-start justify-between gap-2">
                                <p className="text-sm font-semibold text-foreground">{getString(row.title ?? row.idea_name, "Untitled idea")}</p>
                                <span className="rounded border border-primary/30 bg-primary/10 px-1.5 py-0.5 text-[10px] text-primary">{getNumber(row.score, 0).toFixed(1)}</span>
                              </div>
                              <p className="mt-1 text-xs text-muted-foreground">{getString(row.one_liner ?? row.summary, "No summary yet.")}</p>
                            </button>
                          ))}
                          {effectiveIdeas.length === 0 ? <p className="text-sm text-muted-foreground">No ideas surfaced yet.</p> : null}
                        </div>
                      </div>
                      {selectedIdea ? (
                        <div className="rounded-xl border border-border bg-background/30 p-3">
                          <p className="text-[10px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">Idea Dossier</p>
                          <div className="mt-2 space-y-1 text-xs">
                            <div><span className="text-muted-foreground">Title:</span> {getString(selectedIdea.title ?? selectedIdea.idea_name, "-")}</div>
                            <div><span className="text-muted-foreground">Summary:</span> {getString(selectedIdea.one_liner ?? selectedIdea.summary, "-")}</div>
                            <div><span className="text-muted-foreground">Problem:</span> {getString(selectedIdea.problem_summary ?? selectedIdea.core_problem, "-")}</div>
                            <div><span className="text-muted-foreground">Target User:</span> {getString(selectedIdea.target_user ?? selectedIdea.target, "-")}</div>
                            <div><span className="text-muted-foreground">Category:</span> {getString(selectedIdea.category ?? selectedIdea.idea_type, "-")}</div>
                            <div><span className="text-muted-foreground">Score:</span> {getNumber(selectedIdea.score ?? selectedIdea.overall_score, 0).toFixed(2)}</div>
                          </div>
                        </div>
                      ) : null}
                    </div>
                  </div>
                </>
              )}
            </CardContent>
          </Card>
        </div>

        <div className="space-y-4">
          <Card>
            <CardHeader className="pb-2">
              <div className="flex items-center justify-between gap-2">
                <CardTitle>Recent Runs</CardTitle>
                <span className="text-xs text-muted-foreground">{runRows.length} loaded</span>
              </div>
            </CardHeader>
            <CardContent className="space-y-2">
              {runsQuery.isLoading ? (
                <div className="flex items-center gap-2 text-sm text-muted-foreground">
                  <Loader2 size={14} className="animate-spin" /> Loading runs...
                </div>
              ) : null}
              {runsQuery.error ? (
                <div className="rounded-xl border border-danger/30 bg-danger/10 px-3 py-2 text-sm text-danger">
                  Failed to load runs: {String(runsQuery.error)}
                </div>
              ) : null}
              <div className="max-h-[420px] space-y-2 overflow-auto pr-1">
                {runRows.map((row) => {
                  const runId = getString(row.id ?? row.run_id, "");
                  const selected = runId === selectedRunId;
                  return (
                    <button
                      key={runId}
                      className={`w-full rounded-xl border p-3 text-left ${selected ? "border-primary/40 bg-primary/10" : "border-border bg-background/20 hover:bg-background/35"}`}
                      onClick={() => setSelectedRunId(runId)}
                    >
                      <div className="flex items-center justify-between gap-2">
                        <p className="text-sm font-semibold text-foreground">{relativeTime(row.updated_at ?? row.started_at ?? row.created_at ?? "")}</p>
                        <span className={`rounded border px-1.5 py-0.5 text-[10px] ${statusTone(getString(row.status, "unknown"))}`}>{getString(row.status, "unknown")}</span>
                      </div>
                      <div className="mt-1 flex items-center gap-1 font-mono text-[10px] text-muted-foreground">
                        <Clock3 size={10} />
                        {runId.length > 22 ? `${runId.slice(0, 22)}…` : runId}
                      </div>
                      <p className="mt-1 text-[11px] text-muted-foreground">
                        stage {getString((row as Record<string, unknown>).stage, "n/a")} · progress {Math.round(getNumber((row as Record<string, unknown>).progress_pct, 0))}%
                      </p>
                    </button>
                  );
                })}
                {!runsQuery.isLoading && !runsQuery.error && runRows.length === 0 ? (
                  <div className="rounded-xl border border-dashed border-border p-4 text-sm text-muted-foreground">
                    No runs loaded yet. Start a run or refresh the page.
                  </div>
                ) : null}
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="pb-2">
              <CardTitle>Trending Seeds</CardTitle>
            </CardHeader>
            <CardContent className="space-y-2">
              {(trendingQuery.data ?? []).map((item: TopicTrendingItem, index) => (
                <button
                  key={`${getString(item.id ?? item.topic, `trend-${index}`)}`}
                  className="block w-full rounded-xl border border-border/70 bg-background/25 px-3 py-2 text-left"
                  onClick={() => setTargetedForm({ query: getString(item.topic, ""), topic: getString(item.topic, "general") })}
                >
                  <p className="truncate text-sm text-foreground">{getString(item.topic ?? item.name ?? item.label, "untitled topic")}</p>
                  <p className="mt-1 text-[11px] text-muted-foreground">
                    pains {getNumber((item as Record<string, unknown>).pain_count, 0)} · last seen {formatDate((item as Record<string, unknown>).last_seen ?? "")}
                  </p>
                </button>
              ))}
              {(trendingQuery.data ?? []).length === 0 ? <p className="text-sm text-muted-foreground">No trending seeds loaded.</p> : null}
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="pb-2">
              <CardTitle>Signal Snapshot</CardTitle>
            </CardHeader>
            <CardContent className="space-y-2">
              {outputSignals.map((row, index) => (
                <div key={`${getString(row.id, `signal-${index}`)}`} className="rounded-lg border border-border/70 bg-background/20 px-3 py-2">
                  <p className="text-xs text-foreground">{getString(row.title ?? row.body, "signal")}</p>
                </div>
              ))}
              {outputProblems.map((row, index) => (
                <div key={`${getString(row.id, `problem-${index}`)}`} className="rounded-lg border border-border/70 bg-background/20 px-3 py-2">
                  <p className="text-xs text-muted-foreground">{getString(row.text ?? row.statement, "problem")}</p>
                </div>
              ))}
              {outputSignals.length === 0 && outputProblems.length === 0 ? <p className="text-sm text-muted-foreground">No intake snapshot yet.</p> : null}
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}
