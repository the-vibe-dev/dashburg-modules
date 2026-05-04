import { type ElementType, type ReactNode, useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { Archive, BarChart3, Bug, Network } from "lucide-react";

import {
  useCreateIdeaVaultItem,
  useTopicAppgenAnalyzeRun,
  useTopicRunDetail,
  useTopicRuns,
} from "../../shared/api/hooks";
import { Button } from "../../shared/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "../../shared/components/ui/card";
import { Input } from "../../shared/components/ui/input";

type InsightTab = "pain" | "workarounds" | "problems" | "trends";

function rows<T>(value: T[] | undefined): T[] {
  return Array.isArray(value) ? value : [];
}

function text(value: unknown, fallback = "-"): string {
  if (typeof value === "string" && value.trim()) return value;
  if (typeof value === "number") return String(value);
  return fallback;
}

function num(value: unknown, fallback = 0): number {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string") {
    const parsed = Number(value);
    if (Number.isFinite(parsed)) return parsed;
  }
  return fallback;
}

function insightText(row: Record<string, unknown>, ...keys: string[]): string {
  for (const key of keys) {
    if (key in row) {
      const value = text(row[key], "");
      if (value) return value;
    }
  }
  return "-";
}

function insightScore(row: Record<string, unknown>, ...keys: string[]): number {
  for (const key of keys) {
    if (key in row) {
      const value = num(row[key], Number.NaN);
      if (Number.isFinite(value)) return value;
    }
  }
  return 0;
}

function normalizeIdeaType(row: Record<string, unknown>): "video" | "app" | "saas" {
  const explicit = text(row.idea_type ?? row.category ?? row.type, "").toLowerCase();
  if (explicit === "video") return "video";
  if (explicit === "saas") return "saas";
  if (explicit === "app") return "app";
  const blob = `${text(row.title, "")} ${text(row.summary ?? row.one_liner, "")}`.toLowerCase();
  if (blob.includes("video") || blob.includes("youtube") || blob.includes("hook")) return "video";
  if (blob.includes("saas") || blob.includes("subscription") || blob.includes("b2b")) return "saas";
  return "app";
}

function analysisRunMatchesAppgen(run: Record<string, unknown>, appgenRunId: string): boolean {
  const inputSummary = run.input_summary && typeof run.input_summary === "object"
    ? (run.input_summary as Record<string, unknown>)
    : {};
  const sourceRun = text(inputSummary.appgen_run_id ?? run.appgen_run_id ?? run.source_run_id, "");
  if (sourceRun && sourceRun === appgenRunId) return true;
  const query = text(run.query, "").toLowerCase();
  return query.includes(appgenRunId.toLowerCase());
}

function buildViralCreatorHref(idea: Record<string, unknown>): string {
  const title = text(idea.title, "Untitled idea");
  const summary = text(idea.one_liner ?? idea.summary ?? idea.problem_summary ?? idea.problem, "");
  const outputType = normalizeIdeaType(idea) === "video" ? "dbvid" : "dbslide";
  return `/modules/viralcreator?title=${encodeURIComponent(title)}&idea_text=${encodeURIComponent(summary)}&platform=youtube&output_type=${encodeURIComponent(outputType)}`;
}

function toInsightsFromAppgenAnalysis(detail: Record<string, unknown>): Record<string, unknown> | null {
  const outputs = detail.outputs && typeof detail.outputs === "object"
    ? (detail.outputs as Record<string, unknown>)
    : null;
  if (!outputs) return null;

  const bestIdeas = Array.isArray(outputs.best_ideas)
    ? (outputs.best_ideas as Array<Record<string, unknown>>)
    : [];
  const themes = Array.isArray(outputs.themes)
    ? (outputs.themes as Array<Record<string, unknown>>)
    : [];
  const gaps = Array.isArray(outputs.gaps)
    ? (outputs.gaps as Array<Record<string, unknown>>)
    : [];
  const nextTests = Array.isArray(outputs.next_tests)
    ? (outputs.next_tests as Array<Record<string, unknown>>)
    : [];

  const hasAppgenShape = bestIdeas.length > 0 || themes.length > 0 || gaps.length > 0 || nextTests.length > 0 || typeof outputs.summary === "string";
  if (!hasAppgenShape) return null;

  const categoryBuckets: Record<string, { category: string; count: number; scoreTotal: number }> = {};
  for (const row of bestIdeas) {
    const category = text(row.category, "unknown");
    const score = num(row.score, 0);
    const existing = categoryBuckets[category] ?? { category, count: 0, scoreTotal: 0 };
    existing.count += 1;
    existing.scoreTotal += score;
    categoryBuckets[category] = existing;
  }
  const byCategory = Object.values(categoryBuckets).map((row) => ({
    category: row.category,
    count: row.count,
    avg_score: row.count > 0 ? row.scoreTotal / row.count : 0,
  }));

  const topClusters = themes.map((row, idx) => ({
    id: text(row.id, `theme-${idx + 1}`),
    cluster_id: text(row.id, `theme-${idx + 1}`),
    cluster_summary: text(row.theme ?? row.name ?? row.title, "theme"),
    problem_count: num(row.count, 1),
  }));

  const topMicroProblems = gaps.map((row, idx) => ({
    id: text(row.id, `gap-${idx + 1}`),
    text: text(row.title ?? row.gap ?? row.problem, "gap"),
    evidence_snippet: text(row.detail ?? row.summary ?? ""),
    frequency: num(row.count, 0),
  }));

  const countsRaw = detail.counts && typeof detail.counts === "object"
    ? (detail.counts as Record<string, unknown>)
    : {};

  return {
    counts: {
      signals: num(countsRaw.signals, 0),
      micro_problems: num(countsRaw.micro_problems, topMicroProblems.length),
      workarounds: num(countsRaw.workarounds, 0),
      ideas: num(countsRaw.ideas, bestIdeas.length),
    },
    top_clusters: topClusters,
    top_micro_problems: topMicroProblems,
    top_workarounds: [],
    pain_graph: { nodes: [], edges: [] },
    idea_trends: {
      by_category: byCategory,
      by_tag: [],
      top_ideas: bestIdeas,
    },
    summary: text(outputs.summary, ""),
    operator_review: text(outputs.operator_review, ""),
    next_tests: nextTests,
  };
}

function toInsightsFromTopicRun(detail: Record<string, unknown>): Record<string, unknown> | null {
  const outputs = detail.outputs && typeof detail.outputs === "object"
    ? (detail.outputs as Record<string, unknown>)
    : null;
  if (!outputs) return null;
  const topIdeas = Array.isArray(outputs.ideas) ? (outputs.ideas as Array<Record<string, unknown>>) : [];
  const clusters = Array.isArray(outputs.clusters) ? (outputs.clusters as Array<Record<string, unknown>>) : [];
  const pains = Array.isArray(outputs.top_pains) ? (outputs.top_pains as Array<Record<string, unknown>>) : [];
  if (topIdeas.length === 0 && clusters.length === 0 && pains.length === 0) return null;

  const byCategoryBucket: Record<string, { count: number; score: number }> = {};
  for (const idea of topIdeas) {
    const category = text(idea.category ?? idea.idea_type ?? "uncategorized", "uncategorized");
    const score = num(idea.opportunity_score ?? idea.score ?? idea.overall_score, 0);
    const bucket = byCategoryBucket[category] ?? { count: 0, score: 0 };
    bucket.count += 1;
    bucket.score += score;
    byCategoryBucket[category] = bucket;
  }
  const byCategory = Object.entries(byCategoryBucket).map(([category, row]) => ({
    category,
    count: row.count,
    avg_score: row.count ? row.score / row.count : 0,
  }));

  const topClusters = clusters.map((row, idx) => ({
    id: text(row.cluster_id, `cluster-${idx + 1}`),
    cluster_id: text(row.cluster_id, `cluster-${idx + 1}`),
    cluster_summary: text(row.cluster_label, "cluster"),
    problem_count: num(row.pain_count, 0),
  }));
  const topMicroProblems = pains.map((row, idx) => ({
    id: text(row.pain_id, `pain-${idx + 1}`),
    text: text(row.pain_summary, "pain"),
    evidence_snippet: text(row.pain_summary, ""),
    frequency: num(row.urgency_signal, 0),
  }));

  const countsRaw = detail.counts && typeof detail.counts === "object"
    ? (detail.counts as Record<string, unknown>)
    : {};
  return {
    counts: {
      signals: num(countsRaw.raw_posts, 0),
      micro_problems: num(countsRaw.pains, topMicroProblems.length),
      workarounds: 0,
      ideas: num(countsRaw.ideas, topIdeas.length),
    },
    top_clusters: topClusters,
    top_micro_problems: topMicroProblems,
    top_workarounds: [],
    pain_graph: { nodes: [], edges: [] },
    idea_trends: {
      by_category: byCategory,
      by_tag: [],
      top_ideas: topIdeas,
    },
    summary: text(detail.pipeline_run_id ?? detail.run_id, ""),
  };
}

export function TopicInsightsPage({ initialTab = "pain" }: { initialTab?: InsightTab }) {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const [tab, setTab] = useState<InsightTab>(initialTab);
  const [runId, setRunId] = useState<string | null>(searchParams.get("run_id"));
  const [appgenRunId, setAppgenRunId] = useState<string | null>(searchParams.get("appgen_run_id"));
  const [problemSearch, setProblemSearch] = useState("");
  const [communityFilter, setCommunityFilter] = useState("");
  const [saveState, setSaveState] = useState<string | null>(null);
  const [selectedIdea, setSelectedIdea] = useState<Record<string, unknown> | null>(null);

  const runsQuery = useTopicRuns(100);
  const analyzeAppgenRun = useTopicAppgenAnalyzeRun();
  const saveToVault = useCreateIdeaVaultItem();

  const allRuns = rows(runsQuery.data);
  const sourceRuns = useMemo(() => allRuns.filter((run) => {
    const id = text((run as Record<string, unknown>).run_id ?? (run as Record<string, unknown>).id, "");
    const status = text((run as Record<string, unknown>).status, "").toLowerCase();
    const counts = (((run as Record<string, unknown>).counts as Record<string, unknown> | undefined) ?? {}) as Record<string, unknown>;
    const ideaCount = num(counts.ideas, 0);
    return id.startsWith("run:") && ["completed", "succeeded", "success", "done"].includes(status) && ideaCount > 0;
  }).sort((a, b) => {
    const at = new Date(String((a as Record<string, unknown>).created_at ?? (a as Record<string, unknown>).started_at ?? "")).getTime() || 0;
    const bt = new Date(String((b as Record<string, unknown>).created_at ?? (b as Record<string, unknown>).started_at ?? "")).getTime() || 0;
    return bt - at;
  }), [allRuns]);
  const analysisRuns = useMemo(() => allRuns.filter((run) => {
    const id = text((run as Record<string, unknown>).run_id ?? (run as Record<string, unknown>).id, "");
    const pipeline = text((run as Record<string, unknown>).pipeline, "").toLowerCase();
    const query = text((run as Record<string, unknown>).query, "").toLowerCase();
    const status = text((run as Record<string, unknown>).status, "").toLowerCase();
    if (!["completed", "succeeded", "success", "done"].includes(status)) return false;
    if (id.startsWith("run:")) return true;
    if (id.startsWith("appgen-analysis:")) return true;
    return pipeline === "appgen_yc_analysis" || query.startsWith("appgen:");
  }).sort((a, b) => {
    const at = new Date(String((a as Record<string, unknown>).created_at ?? (a as Record<string, unknown>).started_at ?? "")).getTime() || 0;
    const bt = new Date(String((b as Record<string, unknown>).created_at ?? (b as Record<string, unknown>).started_at ?? "")).getTime() || 0;
    return bt - at;
  }), [allRuns]);
  const appgenRuns = useMemo(() => sourceRuns.filter((run) => {
    const row = run as Record<string, unknown>;
    const id = text(row.id ?? row.run_id, "");
    return Boolean(id);
  }), [sourceRuns]);
  const defaultRunId = useMemo(() => {
    if (runId) return runId;
    if (analysisRuns.length > 0) return text((analysisRuns[0] as Record<string, unknown>).run_id ?? (analysisRuns[0] as Record<string, unknown>).id, "");
    return "";
  }, [runId, analysisRuns]);
  const defaultAppgenRunId = useMemo(() => {
    if (appgenRunId) return appgenRunId;
    if (appgenRuns.length > 0) return text((appgenRuns[0] as Record<string, unknown>).id ?? (appgenRuns[0] as Record<string, unknown>).run_id, "");
    return "";
  }, [appgenRunId, appgenRuns]);
  const effectiveRunId = runId || defaultRunId || null;
  const effectiveRunKind = (effectiveRunId || "").startsWith("run:") ? "run" : "analysis";
  const runDetailQuery = useTopicRunDetail(effectiveRunId);
  const selectedRunMeta = useMemo(
    () => analysisRuns.find((run) => text((run as Record<string, unknown>).run_id ?? (run as Record<string, unknown>).id, "") === effectiveRunId) ?? null,
    [analysisRuns, effectiveRunId],
  );
  const selectedRunStatus = text(
    (runDetailQuery.data as Record<string, unknown> | undefined)?.status ??
      (selectedRunMeta as Record<string, unknown> | null)?.status ??
      "unknown",
  );
  const insights = useMemo(() => {
    const detail = runDetailQuery.data as Record<string, unknown> | undefined;
    if (effectiveRunKind === "run") {
      return detail ? toInsightsFromTopicRun(detail) : null;
    }
    const nested = detail?.outputs && typeof detail.outputs === "object"
      ? (detail.outputs as Record<string, unknown>).yc_insights
      : null;
    const raw = detail?.yc_insights ?? nested;
    if (raw && typeof raw === "object") return raw as Record<string, unknown>;
    if (!detail) return null;
    return toInsightsFromTopicRun(detail) ?? toInsightsFromAppgenAnalysis(detail);
  }, [effectiveRunKind, runDetailQuery.data]);
  const runCounts = (((runDetailQuery.data as Record<string, unknown> | undefined)?.counts as Record<string, unknown> | undefined) ?? {}) as Record<string, unknown>;
  const counts = ((insights?.counts as Record<string, unknown> | undefined) ?? {}) as Record<string, unknown>;
  const topClusters = rows((insights?.top_clusters as Array<Record<string, unknown>> | undefined) ?? []);
  const topMicroProblems = rows((insights?.top_micro_problems as Array<Record<string, unknown>> | undefined) ?? []);
  const topWorkarounds = rows((insights?.top_workarounds as Array<Record<string, unknown>> | undefined) ?? []);
  const painGraph = ((insights?.pain_graph as Record<string, unknown> | undefined) ?? {}) as Record<string, unknown>;
  const painNodes = rows((painGraph.nodes as Array<Record<string, unknown>> | undefined) ?? []);
  const painEdges = rows((painGraph.edges as Array<Record<string, unknown>> | undefined) ?? []);
  const ideaTrends = ((insights?.idea_trends as Record<string, unknown> | undefined) ?? {}) as Record<string, unknown>;
  const byCategory = rows((ideaTrends.by_category as Array<Record<string, unknown>> | undefined) ?? []);
  const byTag = rows((ideaTrends.by_tag as Array<Record<string, unknown>> | undefined) ?? []);
  const topIdeas = rows((ideaTrends.top_ideas as Array<Record<string, unknown>> | undefined) ?? []);
  const displaySignals = num(counts.signals, num(runCounts.signals, num(runCounts.raw_posts, 0)));
  const displayMicroProblems = num(counts.micro_problems, num(runCounts.micro_problems, num(runCounts.pains, 0)));
  const displayWorkarounds = num(counts.workarounds, num(runCounts.workarounds, 0));
  const displayIdeas = num(counts.ideas, num(runCounts.ideas, topIdeas.length));

  useEffect(() => {
    if (!runId && defaultRunId) setRunId(defaultRunId);
  }, [runId, defaultRunId]);

  useEffect(() => {
    if (!appgenRunId && defaultAppgenRunId) setAppgenRunId(defaultAppgenRunId);
  }, [appgenRunId, defaultAppgenRunId]);

  useEffect(() => {
    setSelectedIdea(null);
  }, [effectiveRunId]);

  const communities = useMemo(() => {
    const set = new Set<string>();
    painEdges.forEach((edge) => {
      const row = edge as Record<string, unknown>;
      const id = text(row.community ?? row.community_id, "");
      if (id) set.add(id);
    });
    return Array.from(set).sort((a, b) => a.localeCompare(b));
  }, [painEdges]);

  const filteredEdges = useMemo(() => {
    if (!communityFilter) return painEdges;
    return painEdges.filter((edge) => {
      const row = edge as Record<string, unknown>;
      return text(row.community ?? row.community_id, "") === communityFilter;
    });
  }, [painEdges, communityFilter]);

  const problemIndex = useMemo(() => {
    const map = new Map<string, Record<string, unknown>>();
    painNodes.forEach((p) => {
      const row = p as Record<string, unknown>;
      const id = text(row.id ?? row.problem_id, "");
      if (id) map.set(id, row);
    });
    return map;
  }, [painNodes]);

  const clusterIndex = useMemo(() => {
    const map = new Map<string, string>();
    topClusters.forEach((cluster) => {
      const row = cluster as Record<string, unknown>;
      const id = text(row.id ?? row.cluster_id, "");
      if (!id) return;
      map.set(id, text(row.cluster_summary ?? row.name ?? row.label, id));
    });
    return map;
  }, [topClusters]);

  const filteredMicroProblems = useMemo(() => {
    const q = problemSearch.trim().toLowerCase();
    const filtered = !q
      ? topMicroProblems
      : topMicroProblems.filter((item) => {
          const row = item as Record<string, unknown>;
          return insightText(row, "text", "statement", "label").toLowerCase().includes(q);
        });
    return [...filtered].sort(
      (a, b) =>
        insightScore(b as Record<string, unknown>, "frequency", "frequency_proxy", "count", "repeatability_score") -
        insightScore(a as Record<string, unknown>, "frequency", "frequency_proxy", "count", "repeatability_score"),
    );
  }, [topMicroProblems, problemSearch]);

  const hasInsights = Boolean(insights);
  const isRunning = selectedRunStatus.toLowerCase() === "running";
  const isCompleted = ["completed", "succeeded", "success", "done"].includes(selectedRunStatus.toLowerCase());
  const hasAnyInsightContent = (
    displaySignals > 0 ||
    displayMicroProblems > 0 ||
    displayWorkarounds > 0 ||
    displayIdeas > 0 ||
    topClusters.length > 0 ||
    topMicroProblems.length > 0 ||
    topWorkarounds.length > 0 ||
    painNodes.length > 0 ||
    painEdges.length > 0 ||
    topIdeas.length > 0
  );
  const completedButEmpty = Boolean(effectiveRunId) && !runDetailQuery.isLoading && isCompleted && !hasAnyInsightContent;
  const emptyReason = appgenRuns.length === 0
    ? "Generate a completed IdeaFactory run with idea results first, then run advanced analysis here."
    : analyzeAppgenRun.isPending
    ? "Advanced analysis is running now."
    : isRunning
    ? "Insights will appear when the analysis run finishes."
    : completedButEmpty
    ? "This analysis run completed but produced no extracted signals, problems, or ideas."
    : "Select a completed IdeaFactory run and run advanced analysis.";

  const runAdvancedAnalysis = () => {
    const selected = text(appgenRunId, "");
    if (!selected) return;
    analyzeAppgenRun.mutate(
      { appgen_run_id: selected },
      {
        onSuccess: async (result) => {
          const row = result as Record<string, unknown>;
          let analysisRunId = text(
            row.id ?? row.run_id ??
            (row.data as Record<string, unknown> | undefined)?.id ??
            (row.data as Record<string, unknown> | undefined)?.run_id,
            "",
          );
          if (!analysisRunId) {
            const refreshed = await runsQuery.refetch();
            const latest = rows(refreshed.data).find((run) => {
              const row = run as Record<string, unknown>;
              const rid = text(row.run_id ?? row.id, "");
              const pipeline = text(row.pipeline, "").toLowerCase();
              const query = text(row.query, "").toLowerCase();
              const isAnalysis = rid.startsWith("appgen-analysis:") || pipeline === "appgen_yc_analysis" || query.startsWith("appgen:");
              return isAnalysis && analysisRunMatchesAppgen(row, selected);
            });
            analysisRunId = text((latest as Record<string, unknown> | undefined)?.run_id ?? (latest as Record<string, unknown> | undefined)?.id, "");
          }
          if (analysisRunId) setRunId(analysisRunId);
          setSearchParams((prev) => {
            const next = new URLSearchParams(prev);
            next.set("appgen_run_id", selected);
            if (analysisRunId) next.set("run_id", analysisRunId);
            return next;
          });
          setSaveState(analysisRunId ? `Advanced analysis ready: ${analysisRunId}` : `Advanced analysis completed for ${selected}`);
          window.setTimeout(() => setSaveState(null), 3000);
        },
        onError: (error) => {
          setSaveState(`Advanced analysis failed: ${String(error)}`);
          window.setTimeout(() => setSaveState(null), 3000);
        },
      },
    );
  };

  const saveIdea = async (idea: Record<string, unknown>) => {
    try {
      const ideaType = normalizeIdeaType(idea);
      await saveToVault.mutateAsync({
        title: text(idea.title, "Untitled Idea"),
        summary: text(idea.one_liner ?? idea.summary, ""),
        type: "idea",
        tags: ["topic-insights", "ideas-top", ideaType],
        source: {
          module: "TopicInsights",
          run_id: runId,
          endpoint: "/ideas/top",
          related_runs: runId ? [runId] : [],
        },
        payload: {
          ...idea,
          idea_type: ideaType,
          problem_summary: text(idea.problem_summary ?? idea.problem ?? idea.core_problem, ""),
          target_user: text(idea.target_user ?? idea.target ?? idea.audience, ""),
          why_now: text(idea.why_now ?? idea.trend_alignment ?? "Signal frequency and repeated patterns."),
          first_build_step: text(idea.first_build_step ?? idea.mvp_step ?? "Create a narrow test and validate demand."),
        },
        score: insightScore(idea, "score", "overall_score"),
      });
      setSaveState("Saved to IdeaVault");
      window.setTimeout(() => setSaveState(null), 2000);
    } catch (error) {
      setSaveState(`Save failed: ${String(error)}`);
      window.setTimeout(() => setSaveState(null), 3000);
    }
  };

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader className="pb-3">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <CardTitle>TopicInsights</CardTitle>
              <p className="text-xs text-muted-foreground">Advanced analysis layer for completed IdeaFactory runs. This path analyzes AppGen output directly instead of starting a new discovery run.</p>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <Link to="/modules/appgen">
                <Button size="sm" variant="outline">Open IdeaFactory</Button>
              </Link>
              <select
                className="rounded-md border border-border bg-background px-2 py-1 text-xs"
                value={appgenRunId ?? ""}
                onChange={(e) => {
                  const next = e.target.value || null;
                  setAppgenRunId(next);
                  if (next?.startsWith("run:")) {
                    setRunId(next);
                  }
                  setSearchParams((prev) => {
                    const params = new URLSearchParams(prev);
                    if (next) params.set("appgen_run_id", next);
                    else params.delete("appgen_run_id");
                    if (next?.startsWith("run:")) params.set("run_id", next);
                    return params;
                  });
                }}
              >
                <option value="">Select IdeaFactory run</option>
                {appgenRuns.map((run) => {
                  const row = run as Record<string, unknown>;
                  const id = text(row.id ?? row.run_id, "");
                  const status = text(row.status, "");
                  const ts = text(row.created_at ?? row.started_at ?? "", "");
                  const dateLabel = ts ? new Date(/[Z+]/.test(ts) ? ts : `${ts}Z`).toLocaleDateString() : "";
                  const idShort = id.length > 26 ? `${id.slice(0, 26)}…` : id;
                  return (
                    <option key={id} value={id}>{idShort}{dateLabel ? ` (${dateLabel})` : ""}{status ? ` · ${status}` : ""}</option>
                  );
                })}
              </select>
              <Button size="sm" onClick={runAdvancedAnalysis} disabled={!appgenRunId || analyzeAppgenRun.isPending}>
                {analyzeAppgenRun.isPending ? "Analyzing..." : "Run Advanced Analysis"}
              </Button>
              <select
                className="rounded-md border border-border bg-background px-2 py-1 text-xs"
                value={runId ?? ""}
                onChange={(e) => {
                  const next = e.target.value || null;
                  setRunId(next);
                  setSearchParams((prev) => {
                    const params = new URLSearchParams(prev);
                    if (next) params.set("run_id", next);
                    else params.delete("run_id");
                    return params;
                  });
                }}
              >
                <option value="">Select analysis run</option>
                {analysisRuns.map((run) => {
                  const row = run as Record<string, unknown>;
                  const id = text(row.run_id ?? row.id, "");
                  const ts = text(row.created_at ?? row.started_at ?? "", "");
                  const dateLabel = ts ? new Date(/[Z+]/.test(ts) ? ts : `${ts}Z`).toLocaleDateString() : "";
                  const idShort = id.length > 26 ? `${id.slice(0, 26)}…` : id;
                  return (
                    <option key={id} value={id}>{idShort}{dateLabel ? ` (${dateLabel})` : ""}</option>
                  );
                })}
              </select>
            </div>
          </div>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <StatCard icon={Network} label="Signals" value={displaySignals} />
            <StatCard icon={Bug} label="Micro Problems" value={displayMicroProblems} />
            <StatCard icon={Archive} label="Workarounds" value={displayWorkarounds} />
            <StatCard icon={BarChart3} label="Top Ideas" value={displayIdeas} />
          </div>
          <div className="text-xs text-muted-foreground">
            Source IdeaFactory run: {text(appgenRunId, "-")} · Analysis run: {text(effectiveRunId, "-")} (status: {selectedRunStatus})
          </div>
          {completedButEmpty ? (
            <div className="rounded-md border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-xs text-amber-200">
              Analysis run completed with empty output. No signals/problems/ideas were extracted for this run.
            </div>
          ) : null}
          {saveState ? <div className="text-xs text-primary">{saveState}</div> : null}
        </CardContent>
      </Card>

      {effectiveRunId && runDetailQuery.isLoading ? (
        <Card>
          <CardContent className="py-8 text-center text-sm text-muted-foreground">Loading run insights…</CardContent>
        </Card>
      ) : null}

      {!hasInsights ? (
        <Card>
          <CardContent className="py-12">
            <div className="mx-auto max-w-xl text-center space-y-3">
              <p className="text-lg font-semibold text-foreground">No insights yet</p>
              <p className="text-sm text-muted-foreground">{emptyReason}</p>
              <div className="flex items-center justify-center gap-2">
                <Button size="sm" onClick={() => navigate("/modules/appgen")}>Go to IdeaFactory</Button>
                <Button size="sm" variant="outline" onClick={runAdvancedAnalysis} disabled={!appgenRunId || analyzeAppgenRun.isPending}>
                  {analyzeAppgenRun.isPending ? "Analyzing..." : "Run Advanced Analysis"}
                </Button>
              </div>
            </div>
          </CardContent>
        </Card>
      ) : null}

      {hasInsights ? (
      <div className="flex flex-wrap gap-2">
        <TabButton active={tab === "pain"} onClick={() => setTab("pain")}>Pain Graph Explorer</TabButton>
        <TabButton active={tab === "workarounds"} onClick={() => setTab("workarounds")}>Workaround Insights</TabButton>
        <TabButton active={tab === "problems"} onClick={() => setTab("problems")}>Problem Explorer</TabButton>
        <TabButton active={tab === "trends"} onClick={() => setTab("trends")}>Idea Trend Dashboard</TabButton>
      </div>
      ) : null}

      {hasInsights && tab === "pain" ? (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle>Pain Graph Explorer</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3 text-sm">
            <div className="flex items-center gap-2">
              <select
                className="rounded-md border border-border bg-background px-2 py-1 text-xs"
                value={communityFilter}
                onChange={(e) => setCommunityFilter(e.target.value)}
              >
                <option value="">All communities</option>
                {communities.map((id) => (
                  <option key={id} value={id}>{id}</option>
                ))}
              </select>
              <span className="text-xs text-muted-foreground">{filteredEdges.length} edges</span>
            </div>
            {filteredEdges.length > 0 ? (
              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="text-left text-muted-foreground">
                      <th className="py-1">Source problem</th>
                      <th className="py-1">Target problem</th>
                      <th className="py-1">Similarity</th>
                      <th className="py-1">Community</th>
                    </tr>
                  </thead>
                  <tbody>
                    {filteredEdges.slice(0, 200).map((edge) => {
                      const row = edge as Record<string, unknown>;
                      const sourceId = text(row.source_problem_id ?? row.source, "");
                      const targetId = text(row.target_problem_id ?? row.target, "");
                      return (
                        <tr key={`${sourceId}:${targetId}`} className="border-t border-border/60">
                          <td className="py-1">{text(problemIndex.get(sourceId)?.label ?? problemIndex.get(sourceId)?.text ?? sourceId)}</td>
                          <td className="py-1">{text(problemIndex.get(targetId)?.label ?? problemIndex.get(targetId)?.text ?? targetId)}</td>
                          <td className="py-1">{num(row.similarity).toFixed(2)}</td>
                          <td className="py-1">{text(row.community ?? row.community_id)}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="text-left text-muted-foreground">
                      <th className="py-1">Type</th>
                      <th className="py-1">Label</th>
                      <th className="py-1">Weight</th>
                      <th className="py-1">Community</th>
                    </tr>
                  </thead>
                  <tbody>
                    {painNodes.slice(0, 200).map((node) => {
                      const row = node as Record<string, unknown>;
                      return (
                        <tr key={text(row.id ?? row.problem_id)} className="border-t border-border/60">
                          <td className="py-1">{text(row.type, "problem")}</td>
                          <td className="py-1">{text(row.label ?? row.text)}</td>
                          <td className="py-1">{num(row.weight, 0)}</td>
                          <td className="py-1">{text(row.community ?? row.community_id)}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </CardContent>
        </Card>
      ) : null}

      {hasInsights && tab === "workarounds" ? (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle>Workaround Insights</CardTitle>
          </CardHeader>
          <CardContent className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="text-left text-muted-foreground">
                  <th className="py-1">Workaround</th>
                  <th className="py-1">Cluster</th>
                  <th className="py-1">Why used</th>
                  <th className="py-1">Evidence</th>
                </tr>
              </thead>
              <tbody>
                {topWorkarounds.map((row) => {
                  const item = row as Record<string, unknown>;
                  const clusterId = text(item.cluster_id ?? item.cluster, "");
                  const evidenceItems = Array.isArray(item.evidence_snippets)
                    ? (item.evidence_snippets as unknown[]).map((v) => text(v, "")).filter(Boolean)
                    : text(item.evidence_snippet, "") ? [text(item.evidence_snippet, "")] : [];
                  return (
                    <tr key={text(item.id ?? item.text)} className="border-t border-border/60">
                      <td className="py-1">{text(item.text ?? item.workaround, "-")}</td>
                      <td className="py-1">{text(clusterIndex.get(clusterId) ?? clusterId, "-")}</td>
                      <td className="py-1">{text(item.why_used ?? item.reason ?? item.workaround_type, "-")}</td>
                      <td className="py-1">
                        {evidenceItems.length <= 2 ? (
                          <div className="space-y-1">{evidenceItems.map((ev, idx) => <div key={idx}>{ev}</div>)}</div>
                        ) : (
                          <details>
                            <summary className="cursor-pointer">View evidence ({evidenceItems.length})</summary>
                            <div className="mt-1 space-y-1">{evidenceItems.map((ev, idx) => <div key={idx}>{ev}</div>)}</div>
                          </details>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </CardContent>
        </Card>
      ) : null}

      {hasInsights && tab === "problems" ? (
        <Card>
          <CardHeader className="pb-2"><CardTitle>Problem Explorer</CardTitle></CardHeader>
          <CardContent className="space-y-3 text-xs">
            <Input placeholder="Search micro problems" value={problemSearch} onChange={(e) => setProblemSearch(e.target.value)} />
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="text-left text-muted-foreground">
                    <th className="py-1">Micro problem</th>
                    <th className="py-1">Frequency</th>
                    <th className="py-1">Cluster</th>
                    <th className="py-1">Evidence</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredMicroProblems.map((problem) => {
                    const row = problem as Record<string, unknown>;
                    const clusterId = text(row.cluster_id ?? row.cluster, "");
                    const evidenceItems = Array.isArray(row.evidence_snippets)
                      ? (row.evidence_snippets as unknown[]).map((v) => text(v, "")).filter(Boolean)
                      : text(row.evidence_snippet, "") ? [text(row.evidence_snippet, "")] : [];
                    return (
                      <tr key={text(row.id ?? row.text ?? row.statement)} className="border-t border-border/60">
                        <td className="py-1">{insightText(row, "text", "statement", "label")}</td>
                        <td className="py-1">{insightScore(row, "frequency", "frequency_proxy", "count", "repeatability_score").toFixed(2)}</td>
                        <td className="py-1">{text(clusterIndex.get(clusterId) ?? clusterId, "-")}</td>
                        <td className="py-1">
                          {evidenceItems.length <= 2 ? (
                            <div className="space-y-1">{evidenceItems.map((ev, idx) => <div key={idx}>{ev}</div>)}</div>
                          ) : (
                            <details>
                              <summary className="cursor-pointer">View evidence ({evidenceItems.length})</summary>
                              <div className="mt-1 space-y-1">{evidenceItems.map((ev, idx) => <div key={idx}>{ev}</div>)}</div>
                            </details>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </CardContent>
        </Card>
      ) : null}

      {hasInsights && tab === "trends" ? (
        <Card>
          <CardHeader className="pb-2"><CardTitle>Idea Trend Dashboard</CardTitle></CardHeader>
          <CardContent className="space-y-3">
            <div className="grid gap-3 md:grid-cols-2">
              <div className="rounded-md border border-border/70 bg-background/60 p-3">
                <p className="text-xs text-muted-foreground">By Category</p>
                <table className="mt-2 w-full text-xs">
                  <thead><tr className="text-left text-muted-foreground"><th>Category</th><th>Count</th><th>Avg Score</th></tr></thead>
                  <tbody>
                    {[...byCategory].sort((a, b) => num((b as Record<string, unknown>).count, 0) - num((a as Record<string, unknown>).count, 0)).map((row, idx) => {
                      const item = row as Record<string, unknown>;
                      return <tr key={`${idx}-${text(item.category ?? item.name)}`} className="border-t border-border/60"><td className="py-1">{text(item.category ?? item.name)}</td><td className="py-1">{num(item.count, 0)}</td><td className="py-1">{num(item.avg_score, 0).toFixed(2)}</td></tr>;
                    })}
                  </tbody>
                </table>
              </div>
              <div className="rounded-md border border-border/70 bg-background/60 p-3">
                <p className="text-xs text-muted-foreground">By Tag</p>
                <table className="mt-2 w-full text-xs">
                  <thead><tr className="text-left text-muted-foreground"><th>Tag</th><th>Count</th><th>Avg Score</th></tr></thead>
                  <tbody>
                    {[...byTag].sort((a, b) => num((b as Record<string, unknown>).count, 0) - num((a as Record<string, unknown>).count, 0)).map((row, idx) => {
                      const item = row as Record<string, unknown>;
                      return <tr key={`${idx}-${text(item.tag ?? item.name)}`} className="border-t border-border/60"><td className="py-1">{text(item.tag ?? item.name)}</td><td className="py-1">{num(item.count, 0)}</td><td className="py-1">{num(item.avg_score, 0).toFixed(2)}</td></tr>;
                    })}
                  </tbody>
                </table>
              </div>
            </div>
            <div className="rounded-md border border-border/70 bg-background/60 p-3">
                <p className="text-xs text-muted-foreground">Top Ideas</p>
                <div className="overflow-x-auto">
                <table className="mt-2 w-full text-xs">
                  <thead><tr className="text-left text-muted-foreground"><th className="pr-3 py-1">Title</th><th className="pr-3 py-1">Score</th><th className="pr-3 py-1">Category</th><th className="pr-3 py-1">Target</th><th className="pr-3 py-1">Why shortlisted</th><th className="pr-3 py-1">Evidence</th><th className="py-1">Action</th></tr></thead>
                  <tbody>
                    {[...topIdeas].sort((a, b) => insightScore(b as Record<string, unknown>, "score", "overall_score") - insightScore(a as Record<string, unknown>, "score", "overall_score")).map((idea) => {
                      const row = idea as Record<string, unknown>;
                      const shortlist = row.shortlist_rationale && typeof row.shortlist_rationale === "object"
                        ? (row.shortlist_rationale as Record<string, unknown>)
                        : {};
                      const evidence = Array.isArray(row.evidence)
                        ? (row.evidence as unknown[]).map((item) => text(item, "")).filter(Boolean).slice(0, 3)
                        : [];
                      return (
                        <tr
                          key={text(row.id ?? row.idea_id ?? row.title)}
                          className="cursor-pointer border-t border-border/60 hover:bg-background/40"
                          onClick={() => setSelectedIdea(row)}
                        >
                          <td className="py-1">
                            <div className="flex items-center gap-1.5">
                              <span>{text(row.title)}</span>
                              <span className="rounded border border-primary/30 bg-primary/10 px-1 py-0.5 text-[10px] text-primary">
                                {normalizeIdeaType(row).toUpperCase()}
                              </span>
                            </div>
                          </td>
                          <td className="py-1">{insightScore(row, "score", "overall_score").toFixed(2)}</td>
                          <td className="py-1">{text(row.category)}</td>
                          <td className="py-1">{text(row.target_user ?? row.target)}</td>
                          <td className="py-1">
                            <div>{text(shortlist.winner_because ?? row.why_now ?? row.trend_alignment ?? row.summary, "-")}</div>
                            <div className="text-[10px] text-muted-foreground">Risk: {text(shortlist.why_not_higher ?? row.risk, "-")}</div>
                          </td>
                          <td className="py-1">
                            {evidence.length > 0 ? (
                              <div className="space-y-1">
                                {evidence.map((item, idx) => <div key={idx}>{item}</div>)}
                              </div>
                            ) : text(row.evidence_snippet ?? "-", "-")}
                          </td>
                          <td className="py-1">
                            <div className="flex gap-1">
                              <Button size="sm" variant="outline" onClick={(event) => { event.stopPropagation(); setSelectedIdea(row); }}>Inspect</Button>
                              <Button size="sm" variant="outline" onClick={(event) => { event.stopPropagation(); saveIdea(row); }}>Save to Vault</Button>
                              <Link className="inline-flex items-center rounded-md border border-border px-2 py-1 text-xs" to={buildViralCreatorHref(row)}>
                                Use in ViralCreator
                              </Link>
                            </div>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          </CardContent>
        </Card>
      ) : null}

      {selectedIdea ? (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle>Idea Dossier</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2 text-xs">
            <div><span className="text-muted-foreground">Title:</span> {text(selectedIdea.title ?? selectedIdea.idea_name)}</div>
            <div><span className="text-muted-foreground">Wedge:</span> {text(selectedIdea.one_liner ?? selectedIdea.summary, "-")}</div>
            <div><span className="text-muted-foreground">ICP:</span> {text(selectedIdea.target_user ?? selectedIdea.target, "-")}</div>
            <div><span className="text-muted-foreground">Category:</span> {text(selectedIdea.category ?? selectedIdea.idea_type, "-")}</div>
            <div><span className="text-muted-foreground">Problem:</span> {text(selectedIdea.problem_summary ?? selectedIdea.problem ?? selectedIdea.core_problem, "-")}</div>
            <div><span className="text-muted-foreground">Why shortlisted:</span> {text(((selectedIdea.shortlist_rationale as Record<string, unknown> | undefined) ?? {}).winner_because ?? selectedIdea.why_now, "-")}</div>
            <div><span className="text-muted-foreground">Risk:</span> {text(((selectedIdea.shortlist_rationale as Record<string, unknown> | undefined) ?? {}).why_not_higher ?? selectedIdea.risk, "-")}</div>
            <div><span className="text-muted-foreground">Score:</span> {insightScore(selectedIdea, "score", "overall_score").toFixed(2)}</div>
            <div className="flex gap-2 pt-1">
              <Button size="sm" variant="outline" onClick={() => saveIdea(selectedIdea)}>Save to Vault</Button>
              <Link className="inline-flex items-center rounded-md border border-border px-2 py-1 text-xs" to={buildViralCreatorHref(selectedIdea)}>Use in ViralCreator</Link>
            </div>
          </CardContent>
        </Card>
      ) : null}
    </div>
  );
}

function StatCard({ icon: Icon, label, value }: { icon: ElementType; label: string; value: number }) {
  return (
    <div className="rounded-md border border-border/70 bg-background/60 p-3">
      <div className="flex items-center gap-2 text-muted-foreground">
        <Icon size={14} />
        <span className="text-xs">{label}</span>
      </div>
      <div className="mt-2 text-lg font-semibold">{value}</div>
    </div>
  );
}

function TabButton({ active, onClick, children }: { active: boolean; onClick: () => void; children: ReactNode }) {
  return (
    <Button variant={active ? "default" : "outline"} size="sm" onClick={onClick}>
      {children}
    </Button>
  );
}
