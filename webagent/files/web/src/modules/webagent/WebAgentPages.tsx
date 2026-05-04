import { type ReactNode, useEffect, useMemo, useState } from "react";
import { Link, useLocation, useNavigate, useParams } from "react-router-dom";
import { Activity, FileText, Globe, Play, Plus, Save, Search, Server, Shield, Video, Camera, ListTree, Monitor, MousePointerClick, Type, Upload, Keyboard } from "lucide-react";

import {
  useCreateWebAgentRun,
  useMarkWebAgentRunUseful,
  useRetryWebAgentRun,
  useSaveWebAgentReport,
  useWebAgentOverview,
  useWebAgentReports,
  useWebAgentRun,
  useWebAgentRuns,
  useWebAgentStatus,
  useWebAgentRunArtifacts,
  useWebAgentRunDiscovery,
  useWebAgentRunGeneratedTests,
  useWebAgentRunLive,
  useWebAgentRunLogs,
  useWebAgentRunReplay,
  useWebAgentRunScreenshots,
  useCreateWebAgentSession,
  useWebAgentSessionStatus,
  useCloseWebAgentSession,
  useWebAgentSessionAction,
  useWebAgentTool,
} from "../../shared/api/hooks";
import type { WebAgentArtifact } from "../../shared/api/types";
import { Button } from "../../shared/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "../../shared/components/ui/card";
import { Input, Textarea } from "../../shared/components/ui/input";
import { PageHeader } from "../../shared/components/ui/page-header";

const RUN_TYPE_OPTIONS = [
  {
    value: "discovery-scan",
    label: "Discovery Scan",
    description: "Crawl and map routes/forms/actions with minimal mutation.",
    profile: "discovery",
    runMode: "discovery-scan",
    actionBundle: ["goto", "scan_page", "discover_navigation", "inventory_forms", "inventory_actions", "screenshot"],
  },
  {
    value: "content-extract",
    label: "Content Extract",
    description: "Single-page extraction of content, metadata, forms, and API hints.",
    profile: "extract",
    runMode: "content-extract",
    actionBundle: ["goto", "capture_html", "capture_text", "inventory_forms", "network_log", "console_log"],
  },
  {
    value: "qa-audit",
    label: "QA Audit",
    description: "Non-destructive QA baseline: console/js checks + assertions/reporting.",
    profile: "qa-audit",
    runMode: "qa-audit",
    actionBundle: ["goto", "scan_page", "assert_console_clean", "assert_no_js_errors", "summarize_run"],
  },
  {
    value: "form-intel",
    label: "Form Intelligence",
    description: "Deep form recognition/inventory without submitting or mutating.",
    profile: "form-intel",
    runMode: "form-intel",
    actionBundle: ["goto", "inventory_forms", "analyze_form", "scan_page", "screenshot"],
  },
  {
    value: "form-fill",
    label: "Form Fill",
    description: "Auto-fill detected forms/selects/checks using test personas.",
    profile: "form-fill",
    runMode: "form-fill",
    actionBundle: ["goto", "fill_all_forms", "select_option", "check", "press", "screenshot"],
  },
  {
    value: "upload-validation",
    label: "Upload Validation",
    description: "Locate upload controls, attach fixtures, and validate preview/selection.",
    profile: "upload-test",
    runMode: "upload-validation",
    actionBundle: ["goto", "inventory_uploads", "generate_test_asset", "set_input_files", "assert_file_preview_visible", "screenshot"],
  },
  {
    value: "workflow-e2e",
    label: "Workflow E2E",
    description: "Form + upload + CTA workflow traversal with replay artifacts.",
    profile: "workflow-e2e",
    runMode: "workflow-e2e",
    actionBundle: ["goto", "click", "fill", "set_input_files", "select_option", "check", "press", "screenshot"],
  },
  {
    value: "deep-explore",
    label: "Deep Explore",
    description: "High-depth exploratory interaction with guarded automation.",
    profile: "deep-explore",
    runMode: "deep-explore",
    actionBundle: ["scan_page", "inventory_actions", "deep_explore_page", "click", "fill", "screenshot"],
  },
];

function apiBase(): string {
  const explicit = String(import.meta.env.VITE_API_URL ?? "").trim();
  if (explicit) return explicit.replace(/\/+$/, "");
  return `${window.location.protocol}//${window.location.hostname}:8321`;
}

function artifactUrl(runId: string, path: string): string {
  return `${apiBase()}/api/webagent/runs/${runId}/artifacts/content?path=${encodeURIComponent(path)}`;
}

function relTime(iso: string | null | undefined): string {
  if (!iso) return "-";
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return iso;
  const sec = Math.max(0, Math.floor((Date.now() - t) / 1000));
  if (sec < 60) return `${sec}s ago`;
  const min = Math.floor(sec / 60);
  if (min < 60) return `${min}m ago`;
  const hr = Math.floor(min / 60);
  if (hr < 24) return `${hr}h ago`;
  return `${Math.floor(hr / 24)}d ago`;
}

function StatusChip({ status }: { status: string }) {
  const value = String(status || "unknown").toLowerCase();
  const cls =
    value === "completed"
      ? "bg-success/15 text-success"
      : value === "running" || value === "queued"
        ? "bg-warning/15 text-warning"
        : value === "failed" || value === "cancelled"
          ? "bg-danger/15 text-danger"
          : "bg-muted text-muted-foreground";
  return <span className={`inline-flex rounded-full px-2 py-1 text-xs font-semibold ${cls}`}>{value}</span>;
}

function WebAgentTabs() {
  const location = useLocation();
  const tabs = [
    { href: "/modules/webagent", label: "Overview", icon: <Globe size={12} /> },
    { href: "/modules/webagent/new", label: "New Run", icon: <Plus size={12} /> },
    { href: "/modules/webagent/interactive", label: "Interactive", icon: <MousePointerClick size={12} /> },
    { href: "/modules/webagent/runs", label: "Runs", icon: <Play size={12} /> },
    { href: "/modules/webagent/reports", label: "Saved Reports", icon: <Save size={12} /> },
    { href: "/modules/webagent/status", label: "Node Status", icon: <Server size={12} /> },
  ];
  return (
    <div className="flex flex-wrap gap-2">
      {tabs.map((tab) => (
        <Link key={tab.href} to={tab.href}>
          <Button variant={tab.href === "/modules/webagent" ? (location.pathname === tab.href ? "default" : "outline") : location.pathname.startsWith(tab.href) ? "default" : "outline"} size="sm">
            {tab.icon}
            {tab.label}
          </Button>
        </Link>
      ))}
    </div>
  );
}

function OverviewSection() {
  const overview = useWebAgentOverview();
  const status = useWebAgentStatus();
  const summary = overview.data?.summary;
  return (
    <div className="space-y-4">
      <div className="grid gap-3 md:grid-cols-4">
        <MetricCard title="Total Runs" value={String(summary?.total_runs ?? 0)} />
        <MetricCard title="Saved Reports" value={String(summary?.saved_reports ?? 0)} />
        <MetricCard title="Useful Runs" value={String(summary?.useful_runs ?? 0)} />
        <MetricCard title="Node Health" value={String((status.data?.health as { status?: string } | undefined)?.status ?? "unknown")} />
      </div>
      <Card>
        <CardHeader className="pb-2"><CardTitle>Recent WebAgent Runs</CardTitle></CardHeader>
        <CardContent className="space-y-2">
          {(overview.data?.recent_runs ?? []).slice(0, 8).map((run) => (
            <div key={run.id} className="flex flex-wrap items-center justify-between gap-2 rounded border border-border p-2">
              <div className="min-w-0">
                <p className="truncate text-sm font-medium">{run.target_url}</p>
                <p className="text-xs text-muted-foreground">{run.run_type} · node {run.node_id}</p>
              </div>
              <div className="flex items-center gap-2">
                <StatusChip status={run.status} />
                <Link to={`/modules/webagent/runs/${run.id}`}><Button size="sm" variant="outline">Open</Button></Link>
              </div>
            </div>
          ))}
          {(overview.data?.recent_runs?.length ?? 0) === 0 ? <p className="text-sm text-muted-foreground">No runs yet.</p> : null}
        </CardContent>
      </Card>
    </div>
  );
}

function NewRunSection() {
  const navigate = useNavigate();
  const createRun = useCreateWebAgentRun();
  const [targetUrl, setTargetUrl] = useState("");
  const [runType, setRunType] = useState("workflow-e2e");
  const [nodeId, setNodeId] = useState("");
  const [crawlDepth, setCrawlDepth] = useState(2);
  const [maxPages, setMaxPages] = useState(40);
  const [domainPolicy, setDomainPolicy] = useState<"same-domain" | "allow-subdomains" | "allow-external">("same-domain");
  const [includeLighthouse, setIncludeLighthouse] = useState(false);
  const [passiveOnlySecurity, setPassiveOnlySecurity] = useState(true);
  const [enableLiveView, setEnableLiveView] = useState(false);
  const [headedMode, setHeadedMode] = useState(false);
  const [saveTrace, setSaveTrace] = useState(true);
  const [saveVideo, setSaveVideo] = useState(true);
  const [saveScreenshots, setSaveScreenshots] = useState(true);
  const [saveConsoleLogs, setSaveConsoleLogs] = useState(true);
  const [saveNetworkSummary, setSaveNetworkSummary] = useState(true);
  const [saveDomArtifacts, setSaveDomArtifacts] = useState(true);
  const [saveGeneratedTests, setSaveGeneratedTests] = useState(true);
  const [viewportPreset, setViewportPreset] = useState("desktop");
  const [traceMode, setTraceMode] = useState("on");
  const [videoMode, setVideoMode] = useState("on");
  const [timeoutSeconds, setTimeoutSeconds] = useState(900);
  const [objective, setObjective] = useState("");
  const [mode, setMode] = useState("workflow-e2e");
  const [aggression, setAggression] = useState<"safe" | "normal" | "aggressive" | "destructive-test">("normal");
  const [allowDestructive, setAllowDestructive] = useState(false);
  const [fillProfile, setFillProfile] = useState<"minimal" | "realistic" | "edge-case" | "max-length" | "invalid">("realistic");
  const [personaSeed, setPersonaSeed] = useState(7);
  const [notes, setNotes] = useState("");

  const selectedRunType = RUN_TYPE_OPTIONS.find((row) => row.value === runType) ?? RUN_TYPE_OPTIONS[0];
  const automationHeavy = ["form-fill", "upload-test", "workflow-e2e", "deep-explore"].includes(selectedRunType.profile);
  const liveSupported = true;

  useEffect(() => {
    setMode(selectedRunType.runMode);
  }, [selectedRunType.runMode]);

  return (
    <Card>
      <CardHeader className="pb-2"><CardTitle>Create WebAgent Run</CardTitle></CardHeader>
      <CardContent className="space-y-3">
        <label className="text-xs text-muted-foreground">
          Target URL
          <Input value={targetUrl} onChange={(e) => setTargetUrl(e.target.value)} placeholder="https://example.com" />
        </label>

        <div className="grid gap-3 md:grid-cols-3">
          <label className="text-xs text-muted-foreground">
            Run Type
            <select className="mt-1 w-full rounded border border-border bg-input px-2 py-2 text-sm text-foreground" value={runType} onChange={(e) => setRunType(e.target.value)}>
              {RUN_TYPE_OPTIONS.map((rt) => <option key={rt.value} value={rt.value}>{rt.label}</option>)}
            </select>
            <span className="mt-1 block text-[11px] text-muted-foreground">{selectedRunType.description}</span>
          </label>
          <label className="text-xs text-muted-foreground">
            Node ID
            <Input value={nodeId} onChange={(e) => setNodeId(e.target.value)} placeholder="optional (auto-resolve if blank)" />
          </label>
          <label className="text-xs text-muted-foreground">
            Allowed Domain Behavior
            <select className="mt-1 w-full rounded border border-border bg-input px-2 py-2 text-sm text-foreground" value={domainPolicy} onChange={(e) => setDomainPolicy(e.target.value as "same-domain" | "allow-subdomains" | "allow-external")}>
              <option value="same-domain">same-domain</option>
              <option value="allow-subdomains">allow-subdomains</option>
              <option value="allow-external">allow-external</option>
            </select>
          </label>
        </div>

        <div className="grid gap-3 rounded border border-border p-3 md:grid-cols-2">
          <label className="inline-flex items-center gap-2 text-xs text-muted-foreground"><input type="checkbox" disabled={!liveSupported} checked={enableLiveView && liveSupported} onChange={(e) => { const on = e.target.checked && liveSupported; setEnableLiveView(on); if (on) setHeadedMode(true); }} />Enable Live View</label>
          <label className="inline-flex items-center gap-2 text-xs text-muted-foreground"><input type="checkbox" checked={headedMode || enableLiveView} disabled={enableLiveView} onChange={(e) => setHeadedMode(e.target.checked)} />Headed Mode</label>
          <label className="inline-flex items-center gap-2 text-xs text-muted-foreground"><input type="checkbox" checked={saveTrace} onChange={(e) => setSaveTrace(e.target.checked)} />Save Trace</label>
          <label className="inline-flex items-center gap-2 text-xs text-muted-foreground"><input type="checkbox" checked={saveVideo} onChange={(e) => setSaveVideo(e.target.checked)} />Save Video</label>
          <label className="inline-flex items-center gap-2 text-xs text-muted-foreground"><input type="checkbox" checked={saveScreenshots} onChange={(e) => setSaveScreenshots(e.target.checked)} />Save Screenshots</label>
          <label className="inline-flex items-center gap-2 text-xs text-muted-foreground"><input type="checkbox" checked={saveConsoleLogs} onChange={(e) => setSaveConsoleLogs(e.target.checked)} />Save Console Logs</label>
          <label className="inline-flex items-center gap-2 text-xs text-muted-foreground"><input type="checkbox" checked={saveNetworkSummary} onChange={(e) => setSaveNetworkSummary(e.target.checked)} />Save Network Summary</label>
          <label className="inline-flex items-center gap-2 text-xs text-muted-foreground"><input type="checkbox" checked={saveDomArtifacts} onChange={(e) => setSaveDomArtifacts(e.target.checked)} />Save DOM/Discovery Artifacts</label>
          <label className="inline-flex items-center gap-2 text-xs text-muted-foreground"><input type="checkbox" checked={saveGeneratedTests} onChange={(e) => setSaveGeneratedTests(e.target.checked)} />Save Generated Tests</label>
          <label className="inline-flex items-center gap-2 text-xs text-muted-foreground"><input type="checkbox" checked={includeLighthouse} onChange={(e) => setIncludeLighthouse(e.target.checked)} />Include Lighthouse</label>
          <label className="inline-flex items-center gap-2 text-xs text-muted-foreground"><input type="checkbox" checked={passiveOnlySecurity} onChange={(e) => setPassiveOnlySecurity(e.target.checked)} />Passive-only security</label>
        </div>
        {!liveSupported ? <p className="text-xs text-muted-foreground">Live session is unavailable for security-scan runs.</p> : null}

        <details className="rounded border border-border p-3">
          <summary className="cursor-pointer text-sm font-semibold">Advanced options</summary>
          <div className="mt-3 grid gap-3 md:grid-cols-3">
            <label className="text-xs text-muted-foreground">Crawl Depth<Input type="number" value={crawlDepth} onChange={(e) => setCrawlDepth(Number(e.target.value || 2))} /></label>
            <label className="text-xs text-muted-foreground">Max Pages<Input type="number" value={maxPages} onChange={(e) => setMaxPages(Number(e.target.value || 40))} /></label>
            <label className="text-xs text-muted-foreground">Timeout (seconds)<Input type="number" value={timeoutSeconds} onChange={(e) => setTimeoutSeconds(Number(e.target.value || 900))} /></label>
            <label className="text-xs text-muted-foreground">Viewport/device preset
              <select className="mt-1 w-full rounded border border-border bg-input px-2 py-2 text-sm text-foreground" value={viewportPreset} onChange={(e) => setViewportPreset(e.target.value)}>
                <option value="desktop">desktop</option>
                <option value="mobile">mobile</option>
                <option value="tablet">tablet</option>
              </select>
            </label>
            <label className="text-xs text-muted-foreground">Trace mode
              <select className="mt-1 w-full rounded border border-border bg-input px-2 py-2 text-sm text-foreground" value={traceMode} onChange={(e) => setTraceMode(e.target.value)}>
                <option value="on">on</option>
                <option value="retain-on-failure">retain-on-failure</option>
                <option value="off">off</option>
              </select>
            </label>
            <label className="text-xs text-muted-foreground">Video mode
              <select className="mt-1 w-full rounded border border-border bg-input px-2 py-2 text-sm text-foreground" value={videoMode} onChange={(e) => setVideoMode(e.target.value)}>
                <option value="on">on</option>
                <option value="retain-on-failure">retain-on-failure</option>
                <option value="off">off</option>
              </select>
            </label>
            <label className="text-xs text-muted-foreground">Run mode (from run type)
              <Input value={mode} readOnly />
            </label>
            <label className="text-xs text-muted-foreground">Deep aggression
              <select className="mt-1 w-full rounded border border-border bg-input px-2 py-2 text-sm text-foreground" value={aggression} onChange={(e) => setAggression(e.target.value as "safe" | "normal" | "aggressive" | "destructive-test")}>
                <option value="safe">safe</option>
                <option value="normal">normal</option>
                <option value="aggressive">aggressive</option>
                <option value="destructive-test">destructive-test</option>
              </select>
            </label>
            <label className="text-xs text-muted-foreground">Form fill profile
              <select className="mt-1 w-full rounded border border-border bg-input px-2 py-2 text-sm text-foreground" value={fillProfile} onChange={(e) => setFillProfile(e.target.value as "minimal" | "realistic" | "edge-case" | "max-length" | "invalid")}>
                <option value="minimal">minimal</option>
                <option value="realistic">realistic</option>
                <option value="edge-case">edge-case</option>
                <option value="max-length">max-length</option>
                <option value="invalid">invalid</option>
              </select>
            </label>
            <label className="text-xs text-muted-foreground">Persona seed
              <Input type="number" value={personaSeed} onChange={(e) => setPersonaSeed(Number(e.target.value || 7))} />
            </label>
            <label className="inline-flex items-center gap-2 text-xs text-muted-foreground md:col-span-3"><input type="checkbox" checked={allowDestructive} onChange={(e) => setAllowDestructive(e.target.checked)} />Allow destructive actions (guarded)</label>
            <label className="text-xs text-muted-foreground md:col-span-3">
              Objective
              <Textarea rows={3} value={objective} onChange={(e) => setObjective(e.target.value)} placeholder="What should this run discover?" />
            </label>
          </div>
        </details>

        <label className="text-xs text-muted-foreground">
          Notes
          <Textarea rows={3} value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="Context or expected outputs..." />
        </label>

        <div className="flex gap-2">
          <Button
            onClick={() =>
              createRun.mutate(
                {
                  target_url: targetUrl.trim(),
                  run_type: runType,
                  node_id: nodeId.trim() || undefined,
                  notes,
                  settings: {
                    crawl_depth: crawlDepth,
                    max_pages: maxPages,
                    domain_policy: domainPolicy,
                    include_screenshots: saveScreenshots,
                    include_generated_tests: saveGeneratedTests,
                    include_lighthouse: includeLighthouse,
                    passive_only_security: passiveOnlySecurity,
                    enable_live_view: (enableLiveView && liveSupported) || (automationHeavy && liveSupported),
                    headed_mode: enableLiveView ? true : automationHeavy ? true : headedMode,
                    save_trace: saveTrace,
                    save_video: saveVideo,
                    save_screenshots: saveScreenshots,
                    save_console_logs: saveConsoleLogs,
                    save_network_summary: saveNetworkSummary,
                    save_dom_artifacts: saveDomArtifacts,
                    save_generated_tests: saveGeneratedTests,
                    viewport_preset: viewportPreset,
                    step_screenshot_frequency: "key-actions",
                    trace_mode: traceMode,
                    video_mode: videoMode,
                    timeout_seconds: timeoutSeconds,
                    objective,
                    mode,
                    aggression,
                    allow_destructive: allowDestructive,
                    fill_profile: fillProfile,
                    persona_seed: personaSeed,
                    requested_run_type: runType,
                    automation_profile: selectedRunType.profile,
                    playwright_action_bundle: selectedRunType.actionBundle,
                  },
                },
                {
                  onSuccess: (run) => navigate(`/modules/webagent/runs/${run.id}`),
                },
              )
            }
            disabled={!targetUrl.trim() || createRun.isPending}
          >
            <Play size={14} />
            Run WebAgent
          </Button>
          <Link to="/modules/webagent/runs"><Button variant="outline">View Runs</Button></Link>
        </div>
        {createRun.error ? <p className="text-sm text-danger">{String(createRun.error)}</p> : null}
      </CardContent>
    </Card>
  );
}

function RunsSection() {
  const [statusFilter, setStatusFilter] = useState("");
  const [search, setSearch] = useState("");
  const runsQuery = useWebAgentRuns({ status: statusFilter || undefined, limit: 200 });
  const rows = useMemo(() => {
    const list = runsQuery.data ?? [];
    const q = search.trim().toLowerCase();
    if (!q) return list;
    return list.filter((r) => r.target_url.toLowerCase().includes(q) || r.run_type.toLowerCase().includes(q) || r.node_id.toLowerCase().includes(q));
  }, [runsQuery.data, search]);

  return (
    <Card>
      <CardHeader className="pb-2"><CardTitle>WebAgent Runs</CardTitle></CardHeader>
      <CardContent className="space-y-3">
        <div className="grid gap-2 md:grid-cols-3">
          <label className="text-xs text-muted-foreground">
            Status filter
            <select className="mt-1 w-full rounded border border-border bg-input px-2 py-2 text-sm text-foreground" value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
              <option value="">all</option>
              <option value="queued">queued</option>
              <option value="running">running</option>
              <option value="completed">completed</option>
              <option value="failed">failed</option>
              <option value="cancelled">cancelled</option>
            </select>
          </label>
          <label className="text-xs text-muted-foreground md:col-span-2">
            Search
            <Input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Filter by URL, node, run type..." />
          </label>
        </div>
        <div className="space-y-2">
          {rows.map((run) => (
            <div key={run.id} className="flex flex-wrap items-center justify-between gap-2 rounded border border-border p-2">
              <div className="min-w-0">
                <p className="truncate text-sm font-medium">{run.target_url}</p>
                <p className="text-xs text-muted-foreground">{run.run_type} · node {run.node_id} · created {relTime(run.created_at)}</p>
              </div>
              <div className="flex items-center gap-2">
                <StatusChip status={run.status} />
                {run.live_session?.enabled ? <span className="rounded bg-primary/15 px-2 py-1 text-xs text-primary">live</span> : null}
                <Link to={`/modules/webagent/runs/${run.id}`}><Button size="sm" variant="outline">Open</Button></Link>
              </div>
            </div>
          ))}
          {(rows.length === 0 && !runsQuery.isLoading) ? <p className="text-sm text-muted-foreground">No runs match the current filters.</p> : null}
        </div>
      </CardContent>
    </Card>
  );
}

function RunDetailSection() {
  const { id = "" } = useParams();
  const [tab, setTab] = useState<"overview" | "live" | "replay" | "screenshots" | "artifacts" | "logs" | "tests" | "discovery">("overview");
  const [liveZoom, setLiveZoom] = useState(1.35);
  const [followActions, setFollowActions] = useState(true);
  const [liveFrameIndex, setLiveFrameIndex] = useState(0);
  const runQuery = useWebAgentRun(id || null);
  const artifactsQ = useWebAgentRunArtifacts(id || null);
  const logsQ = useWebAgentRunLogs(id || null, 1200);
  const replayQ = useWebAgentRunReplay(id || null);
  const screenshotsQ = useWebAgentRunScreenshots(id || null);
  const liveQ = useWebAgentRunLive(id || null);
  const testsQ = useWebAgentRunGeneratedTests(id || null);
  const discoveryQ = useWebAgentRunDiscovery(id || null);
  const retryRun = useRetryWebAgentRun();
  const saveReport = useSaveWebAgentReport();
  const markUseful = useMarkWebAgentRunUseful();

  const run = runQuery.data;
  if (!id) return <p className="text-sm text-muted-foreground">Run id missing.</p>;
  if (runQuery.isLoading) return <p className="text-sm text-muted-foreground">Loading run...</p>;
  if (runQuery.error || !run) return <p className="text-sm text-danger">Failed to load run: {String(runQuery.error ?? "missing")}</p>;

  const summary = (run.summary ?? {}) as Record<string, unknown>;
  const counts = (summary.counts ?? {}) as Record<string, unknown>;
  const artifacts = artifactsQ.data?.items ?? [];
  const groups = artifactsQ.data?.groups ?? {};
  const screenshots = (screenshotsQ.data?.items as WebAgentArtifact[] | undefined) ?? [];
  const logs = logsQ.data?.lines ?? [];
  const latestShot = screenshots.length ? screenshots[screenshots.length - 1] : null;
  const liveFrame = screenshots.length ? screenshots[Math.max(0, Math.min(liveFrameIndex, screenshots.length - 1))] : latestShot;

  useEffect(() => {
    if (!screenshots.length) {
      setLiveFrameIndex(0);
      return;
    }
    if (followActions) {
      setLiveFrameIndex(screenshots.length - 1);
    } else {
      setLiveFrameIndex((idx) => Math.max(0, Math.min(idx, screenshots.length - 1)));
    }
  }, [followActions, screenshots.length]);

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader className="pb-2"><CardTitle>Run Overview</CardTitle></CardHeader>
        <CardContent className="grid gap-2 md:grid-cols-5">
          <MetricCard title="Status" value={run.status} />
          <MetricCard title="Run Type" value={run.run_type} />
          <MetricCard title="Node" value={run.node_id} />
          <MetricCard title="Created" value={relTime(run.created_at)} />
          <MetricCard title="Artifacts" value={String(artifacts.length)} />
          <div className="md:col-span-5">
            <p className="text-sm font-semibold">{run.target_url}</p>
            <p className="mt-1 text-xs text-muted-foreground">{String(summary.summary_text ?? "")}</p>
            {run.error_message ? <p className="mt-1 text-xs text-danger">{run.error_message}</p> : null}
          </div>
        </CardContent>
      </Card>

      <div className="flex flex-wrap gap-2">
        <Button variant={tab === "overview" ? "default" : "outline"} size="sm" onClick={() => setTab("overview")}>Overview</Button>
        <Button variant={tab === "live" ? "default" : "outline"} size="sm" onClick={() => setTab("live")}><Monitor size={12} />Live Session</Button>
        <Button variant={tab === "replay" ? "default" : "outline"} size="sm" onClick={() => setTab("replay")}><Video size={12} />Replay</Button>
        <Button variant={tab === "screenshots" ? "default" : "outline"} size="sm" onClick={() => setTab("screenshots")}><Camera size={12} />Screenshots</Button>
        <Button variant={tab === "artifacts" ? "default" : "outline"} size="sm" onClick={() => setTab("artifacts")}><FileText size={12} />Artifacts</Button>
        <Button variant={tab === "logs" ? "default" : "outline"} size="sm" onClick={() => setTab("logs")}><Activity size={12} />Logs</Button>
        <Button variant={tab === "tests" ? "default" : "outline"} size="sm" onClick={() => setTab("tests")}>Generated Tests</Button>
        <Button variant={tab === "discovery" ? "default" : "outline"} size="sm" onClick={() => setTab("discovery")}><ListTree size={12} />Discovery Data</Button>
      </div>

      {tab === "overview" ? (
        <Card>
          <CardHeader className="pb-2"><CardTitle>Summary and Counts</CardTitle></CardHeader>
          <CardContent className="grid gap-2 md:grid-cols-4">
            <MetricCard title="Routes" value={String(counts.routes ?? 0)} />
            <MetricCard title="Forms" value={String(counts.forms ?? 0)} />
            <MetricCard title="API Endpoints" value={String(counts.api_endpoints ?? 0)} />
            <MetricCard title="Screenshots" value={String(counts.screenshots ?? 0)} />
          </CardContent>
        </Card>
      ) : null}

      {tab === "live" ? (
        <Card>
          <CardHeader className="pb-2"><CardTitle>Live Session</CardTitle></CardHeader>
          <CardContent className="space-y-3">
            <div className="flex items-center gap-2 text-xs text-muted-foreground">
              <span>Live status:</span>
              <StatusChip status={liveQ.data?.status ?? run.live_session?.status ?? "unknown"} />
            </div>
            {(followActions && screenshots.length > 0) || liveFrame ? (
              <div className="space-y-2">
                <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                  <span>Zoom</span>
                  <Button size="sm" variant="outline" onClick={() => setLiveZoom((z) => Math.max(1, Number((z - 0.1).toFixed(2))))}>-</Button>
                  <span className="min-w-14 text-center">{Math.round(liveZoom * 100)}%</span>
                  <Button size="sm" variant="outline" onClick={() => setLiveZoom((z) => Math.min(2.5, Number((z + 0.1).toFixed(2))))}>+</Button>
                  <Button size="sm" variant="outline" onClick={() => setLiveZoom(1.35)}>Reset</Button>
                  <label className="ml-2 inline-flex items-center gap-2">
                    <input type="checkbox" checked={followActions} onChange={(e) => setFollowActions(e.target.checked)} />
                    Follow actions
                  </label>
                  {screenshots.length > 1 ? (
                    <span className="ml-2">
                      Frame {Math.min(liveFrameIndex + 1, screenshots.length)} / {screenshots.length}
                    </span>
                  ) : null}
                </div>
                <div className="relative h-[760px] w-full overflow-hidden rounded border border-border bg-black">
                  <img
                    className="h-full w-full object-cover object-top"
                    style={{ transform: `scale(${liveZoom})`, transformOrigin: "top center" }}
                    src={artifactUrl(run.id, String(liveFrame?.local_rel_path ?? liveFrame?.path ?? ""))}
                    alt="live progression preview"
                  />
                </div>
                {screenshots.length > 1 ? (
                  <input
                    type="range"
                    min={0}
                    max={Math.max(0, screenshots.length - 1)}
                    value={Math.max(0, Math.min(liveFrameIndex, screenshots.length - 1))}
                    onChange={(e) => {
                      setFollowActions(false);
                      setLiveFrameIndex(Number(e.target.value || 0));
                    }}
                  />
                ) : null}
                {liveQ.data?.url ? (
                  <details className="rounded border border-border p-2">
                    <summary className="cursor-pointer text-xs text-muted-foreground">Open raw live stream (secondary view)</summary>
                    <div className="mt-2 relative h-[520px] w-full overflow-hidden rounded border border-border bg-background">
                      <iframe src={liveQ.data.url} title="WebAgent Live Session" className="h-full w-full border-0" />
                    </div>
                  </details>
                ) : null}
              </div>
            ) : latestShot ? (
              <div className="space-y-2">
                <p className="text-xs text-muted-foreground">No live stream URL provided by node. Showing latest screenshot with auto-refresh while run is active.</p>
                <img className="max-h-[520px] w-full rounded border border-border object-contain" src={artifactUrl(run.id, String(latestShot.local_rel_path ?? latestShot.path ?? ""))} alt="latest screenshot" />
              </div>
            ) : (
              <p className="text-sm text-muted-foreground">Live view unavailable for this run.</p>
            )}
          </CardContent>
        </Card>
      ) : null}

      {tab === "replay" ? (
        <Card>
          <CardHeader className="pb-2"><CardTitle>Replay</CardTitle></CardHeader>
          <CardContent className="space-y-4">
            {(replayQ.data?.video_available ?? false) && (replayQ.data?.videos?.length ?? 0) > 0 ? (
              <video controls className="w-full rounded border border-border bg-black" src={artifactUrl(run.id, String(replayQ.data?.primary_video?.local_rel_path ?? replayQ.data?.primary_video?.path ?? replayQ.data?.videos?.[0]?.local_rel_path ?? replayQ.data?.videos?.[0]?.path ?? ""))} />
            ) : <p className="text-sm text-muted-foreground">No video recorded for this run.</p>}
            {(replayQ.data?.trace_available ?? false) && (replayQ.data?.traces?.length ?? 0) > 0 ? (
              <a className="text-sm text-primary underline" target="_blank" rel="noreferrer" href={artifactUrl(run.id, String(replayQ.data?.traces?.[0]?.local_rel_path ?? replayQ.data?.traces?.[0]?.path ?? ""))}>Download trace.zip</a>
            ) : <p className="text-sm text-muted-foreground">No trace recorded for this run.</p>}
          </CardContent>
        </Card>
      ) : null}

      {tab === "screenshots" ? (
        <Card>
          <CardHeader className="pb-2"><CardTitle>Screenshots ({screenshots.length})</CardTitle></CardHeader>
          <CardContent>
            {screenshots.length === 0 ? <p className="text-sm text-muted-foreground">No screenshots found.</p> : (
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                {screenshots.map((row, idx) => {
                  const p = String(row.local_rel_path ?? row.path ?? "");
                  return (
                    <a key={`${p}-${idx}`} href={artifactUrl(run.id, p)} target="_blank" rel="noreferrer" className="overflow-hidden rounded border border-border bg-background/40 p-2">
                      <img src={artifactUrl(run.id, p)} alt={p} className="h-40 w-full object-cover" />
                      <p className="mt-2 truncate text-xs text-muted-foreground">{p}</p>
                    </a>
                  );
                })}
              </div>
            )}
          </CardContent>
        </Card>
      ) : null}

      {tab === "artifacts" ? (
        <Card>
          <CardHeader className="pb-2"><CardTitle>Artifact Manifest</CardTitle></CardHeader>
          <CardContent className="space-y-3">
            <div className="flex flex-wrap gap-2">
              {Object.entries(groups).map(([key, val]) => (
                <span key={key} className="rounded bg-primary/15 px-2 py-1 text-xs text-primary">{key}: {Array.isArray(val) ? val.length : 0}</span>
              ))}
            </div>
            <div className="max-h-[460px] overflow-auto rounded border border-border">
              <table className="w-full text-sm">
                <thead className="bg-background/50 text-xs text-muted-foreground"><tr><th className="p-2 text-left">Path</th><th className="p-2 text-right">Size</th><th className="p-2 text-right">Open</th></tr></thead>
                <tbody>
                  {artifacts.map((row, idx) => {
                    const p = String(row.local_rel_path ?? row.path ?? "");
                    return (
                      <tr key={`${p}-${idx}`} className="border-t border-border">
                        <td className="p-2 font-mono text-xs">{p}</td>
                        <td className="p-2 text-right text-xs text-muted-foreground">{String(row.size_bytes ?? "-")}</td>
                        <td className="p-2 text-right"><a className="text-xs text-primary underline" href={artifactUrl(run.id, p)} target="_blank" rel="noreferrer">open</a></td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </CardContent>
        </Card>
      ) : null}

      {tab === "logs" ? (
        <Card>
          <CardHeader className="pb-2"><CardTitle>Run Logs / Events</CardTitle></CardHeader>
          <CardContent>
            <div className="max-h-[500px] overflow-auto rounded border border-border bg-background/40 p-2 font-mono text-xs">
              {logs.length ? logs.map((line, idx) => <p key={idx}>{line}</p>) : <p className="text-muted-foreground">No log lines yet.</p>}
            </div>
          </CardContent>
        </Card>
      ) : null}

      {tab === "tests" ? (
        <Card>
          <CardHeader className="pb-2"><CardTitle>Generated Tests</CardTitle></CardHeader>
          <CardContent className="space-y-2">
            {(testsQ.data?.items ?? []).length === 0 ? <p className="text-sm text-muted-foreground">No generated tests available.</p> : (testsQ.data?.items ?? []).map((row, idx) => {
              const p = String(row.local_rel_path ?? row.path ?? "");
              return <a key={`${p}-${idx}`} className="block text-sm text-primary underline" href={artifactUrl(run.id, p)} target="_blank" rel="noreferrer">{p}</a>;
            })}
          </CardContent>
        </Card>
      ) : null}

      {tab === "discovery" ? (
        <div className="grid gap-4 md:grid-cols-2">
          <Panel title="Sitemap" icon={<Search size={14} />} rows={toRows(discoveryQ.data?.sitemap)} />
          <Panel title="Forms / Login Surfaces / Buttons" icon={<Shield size={14} />} rows={[...toRows(discoveryQ.data?.forms), ...toRows(discoveryQ.data?.login_surfaces), ...toRows(discoveryQ.data?.buttons)]} />
          <Panel title="API / JS Endpoints" icon={<Activity size={14} />} rows={[...toRows(discoveryQ.data?.api_endpoints), ...toRows(discoveryQ.data?.js_endpoints)]} />
          <Card>
            <CardHeader className="pb-2"><CardTitle>Lighthouse / UX</CardTitle></CardHeader>
            <CardContent>
              <pre className="max-h-56 overflow-auto rounded border border-border bg-background/40 p-2 text-xs text-muted-foreground">{JSON.stringify({ ux_score: discoveryQ.data?.ux_score, lighthouse: discoveryQ.data?.lighthouse ?? {} }, null, 2)}</pre>
            </CardContent>
          </Card>
        </div>
      ) : null}

      <div className="flex flex-wrap gap-2">
        <Button onClick={() => retryRun.mutate(run.id)} variant="outline">Retry Run</Button>
        <Button onClick={() => saveReport.mutate({ runId: run.id })} variant="outline">Save Report</Button>
        <Button onClick={() => markUseful.mutate({ runId: run.id, is_useful: !run.is_useful })} variant="outline">{run.is_useful ? "Unmark Useful" : "Mark Useful"}</Button>
      </div>
    </div>
  );
}

function InteractiveSection() {
  const createSession = useCreateWebAgentSession();
  const getSessionStatus = useWebAgentSessionStatus();
  const closeSession = useCloseWebAgentSession();
  const runAction = useWebAgentSessionAction();
  const runTool = useWebAgentTool();

  const [nodeId, setNodeId] = useState("");
  const nodeStatus = useWebAgentStatus(nodeId.trim() || undefined);
  const [targetUrl, setTargetUrl] = useState("https://testautomationpractice.blogspot.com/");
  const [sessionId, setSessionId] = useState("");
  const [timeoutSeconds, setTimeoutSeconds] = useState(120);
  const [selector, setSelector] = useState("");
  const [value, setValue] = useState("");
  const [filesCsv, setFilesCsv] = useState("");
  const [pressKey, setPressKey] = useState("Enter");
  const [script, setScript] = useState("document.title");
  const [customAction, setCustomAction] = useState("scan_page");
  const [customPayload, setCustomPayload] = useState("{\"wait_for\":\"networkidle\"}");
  const [assetKind, setAssetKind] = useState("image");
  const [assetName, setAssetName] = useState("upload-fixture");
  const [aggressionMode, setAggressionMode] = useState("normal");
  const [actionResult, setActionResult] = useState<Record<string, unknown> | null>(null);
  const interactiveBlocked = nodeStatus.data?.interactive_supported === false;
  const allowedJobTypes = Array.isArray(nodeStatus.data?.runner_allowed_job_types) ? nodeStatus.data?.runner_allowed_job_types : [];

  function setResult(row: unknown) {
    if (row && typeof row === "object") setActionResult(row as Record<string, unknown>);
    else setActionResult({ result: row });
  }

  function filesArray(): string[] {
    return filesCsv
      .split(",")
      .map((v) => v.trim())
      .filter((v) => v.length > 0);
  }

  function mutateAction(action: string, payload: Record<string, unknown>) {
    if (interactiveBlocked) {
      setResult({
        ok: false,
        error: "Interactive WebAgent actions are not enabled on this node runner.",
        runner_allowed_job_types: allowedJobTypes,
      });
      return;
    }
    if (!sessionId.trim()) return;
    runAction.mutate(
      {
        sessionId: sessionId.trim(),
        payload: {
          action,
          node_id: nodeId.trim() || undefined,
          timeout_seconds: timeoutSeconds,
          ...payload,
        },
      },
      {
        onSuccess: (row) => {
          const sid = String(row.session_id ?? "").trim();
          if (sid) setSessionId(sid);
          setResult(row);
        },
      },
    );
  }

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader className="pb-2"><CardTitle>Interactive Playwright Controls</CardTitle></CardHeader>
        <CardContent className="space-y-3">
          {interactiveBlocked ? (
            <div className="rounded border border-danger/40 bg-danger/10 p-2 text-xs text-danger">
              Interactive actions are unavailable on this node runner (`webagent.action` unsupported). Allowed job types: {allowedJobTypes?.join(", ") || "none reported"}.
            </div>
          ) : null}
          <div className="grid gap-3 md:grid-cols-4">
            <label className="text-xs text-muted-foreground">
              Node ID
              <Input value={nodeId} onChange={(e) => setNodeId(e.target.value)} placeholder="optional (auto-resolve if blank)" />
            </label>
            <label className="text-xs text-muted-foreground md:col-span-2">
              Target URL
              <Input value={targetUrl} onChange={(e) => setTargetUrl(e.target.value)} placeholder="https://testautomationpractice.blogspot.com/" />
            </label>
            <label className="text-xs text-muted-foreground">
              Timeout (seconds)
              <Input type="number" value={timeoutSeconds} onChange={(e) => setTimeoutSeconds(Number(e.target.value || 120))} />
            </label>
          </div>

          <div className="flex flex-wrap gap-2">
            <Button
              onClick={() =>
                createSession.mutate(
                  {
                    target_url: targetUrl.trim(),
                    node_id: nodeId.trim() || undefined,
                    settings: { headed_mode: true, enable_live_view: true },
                    timeout_seconds: timeoutSeconds,
                  },
                  {
                    onSuccess: (row) => {
                      const sid = String(row.session_id ?? "").trim();
                      if (sid) setSessionId(sid);
                      setResult(row);
                    },
                  },
                )
              }
              disabled={interactiveBlocked || !targetUrl.trim() || createSession.isPending}
            >
              <Play size={14} />
              Start Session
            </Button>
            <Button
              variant="outline"
              onClick={() =>
                getSessionStatus.mutate(
                  { sessionId: sessionId.trim(), nodeId: nodeId.trim() || undefined, timeoutSeconds },
                  { onSuccess: (row) => setResult(row) },
                )
              }
              disabled={interactiveBlocked || !sessionId.trim() || getSessionStatus.isPending}
            >
              Session Status
            </Button>
            <Button
              variant="outline"
              onClick={() =>
                mutateAction("goto", {
                  url: targetUrl.trim(),
                })
              }
              disabled={interactiveBlocked || !sessionId.trim() || !targetUrl.trim() || runAction.isPending}
            >
              Navigate
            </Button>
            <Button
              variant="outline"
              onClick={() =>
                closeSession.mutate(
                  { sessionId: sessionId.trim(), nodeId: nodeId.trim() || undefined, timeoutSeconds },
                  {
                    onSuccess: (row) => {
                      setResult(row);
                      setSessionId("");
                    },
                  },
                )
              }
              disabled={interactiveBlocked || !sessionId.trim() || closeSession.isPending}
            >
              Stop Session
            </Button>
          </div>

          <label className="text-xs text-muted-foreground">
            Active Session ID
            <Input value={sessionId} onChange={(e) => setSessionId(e.target.value)} placeholder="session id from start_session" />
          </label>
        </CardContent>
      </Card>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader className="pb-2"><CardTitle className="flex items-center gap-2 text-sm"><MousePointerClick size={14} />Click / Check / Hover</CardTitle></CardHeader>
          <CardContent className="space-y-3">
            <label className="text-xs text-muted-foreground">
              Selector
              <Input value={selector} onChange={(e) => setSelector(e.target.value)} placeholder="#id, .class, text=Label, xpath=..." />
            </label>
            <div className="flex flex-wrap gap-2">
              <Button size="sm" onClick={() => mutateAction("click", { selector })} disabled={!sessionId.trim() || !selector.trim()}>Click</Button>
              <Button size="sm" variant="outline" onClick={() => mutateAction("dblclick", { selector })} disabled={!sessionId.trim() || !selector.trim()}>Double Click</Button>
              <Button size="sm" variant="outline" onClick={() => mutateAction("check", { selector })} disabled={!sessionId.trim() || !selector.trim()}>Check</Button>
              <Button size="sm" variant="outline" onClick={() => mutateAction("uncheck", { selector })} disabled={!sessionId.trim() || !selector.trim()}>Uncheck</Button>
              <Button size="sm" variant="outline" onClick={() => mutateAction("hover", { selector })} disabled={!sessionId.trim() || !selector.trim()}>Hover</Button>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2"><CardTitle className="flex items-center gap-2 text-sm"><Type size={14} />Fill / Type / Select</CardTitle></CardHeader>
          <CardContent className="space-y-3">
            <label className="text-xs text-muted-foreground">
              Selector
              <Input value={selector} onChange={(e) => setSelector(e.target.value)} placeholder="input[name='name']" />
            </label>
            <label className="text-xs text-muted-foreground">
              Value/Text
              <Input value={value} onChange={(e) => setValue(e.target.value)} placeholder="Jane Doe" />
            </label>
            <div className="flex flex-wrap gap-2">
              <Button size="sm" onClick={() => mutateAction("fill", { selector, value })} disabled={!sessionId.trim() || !selector.trim()}>Fill</Button>
              <Button size="sm" variant="outline" onClick={() => mutateAction("type", { selector, text: value })} disabled={!sessionId.trim() || !selector.trim()}>Type</Button>
              <Button size="sm" variant="outline" onClick={() => mutateAction("select_option", { selector, value })} disabled={!sessionId.trim() || !selector.trim()}>Select</Button>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2"><CardTitle className="flex items-center gap-2 text-sm"><Upload size={14} />Upload</CardTitle></CardHeader>
          <CardContent className="space-y-3">
            <label className="text-xs text-muted-foreground">
              File Input Selector
              <Input value={selector} onChange={(e) => setSelector(e.target.value)} placeholder="input[type='file']" />
            </label>
            <label className="text-xs text-muted-foreground">
              File Paths (comma-separated)
              <Input value={filesCsv} onChange={(e) => setFilesCsv(e.target.value)} placeholder="/tmp/a.txt,/tmp/b.png" />
            </label>
            <Button
              size="sm"
              onClick={() => mutateAction("set_input_files", { selector, files: filesArray() })}
              disabled={!sessionId.trim() || !selector.trim() || filesArray().length === 0}
            >
              Set Input Files
            </Button>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2"><CardTitle className="flex items-center gap-2 text-sm"><Keyboard size={14} />Keyboard / Wait / Script</CardTitle></CardHeader>
          <CardContent className="space-y-3">
            <label className="text-xs text-muted-foreground">
              Key
              <Input value={pressKey} onChange={(e) => setPressKey(e.target.value)} placeholder="Enter, Tab, Escape" />
            </label>
            <label className="text-xs text-muted-foreground">
              Script / Expression
              <Textarea rows={3} value={script} onChange={(e) => setScript(e.target.value)} placeholder="document.title" />
            </label>
            <div className="flex flex-wrap gap-2">
              <Button size="sm" onClick={() => mutateAction("press", { key: pressKey })} disabled={!sessionId.trim() || !pressKey.trim()}>Press</Button>
              <Button size="sm" variant="outline" onClick={() => mutateAction("wait_for_selector", { selector })} disabled={!sessionId.trim() || !selector.trim()}>Wait For Selector</Button>
              <Button size="sm" variant="outline" onClick={() => mutateAction("screenshot", { screenshot_name: `shot-${Date.now()}.png` })} disabled={!sessionId.trim()}>Screenshot</Button>
              <Button size="sm" variant="outline" onClick={() => mutateAction("evaluate", { script })} disabled={!sessionId.trim() || !script.trim()}>Evaluate</Button>
              <Button size="sm" variant="outline" onClick={() => mutateAction("extract", { expression: script })} disabled={!sessionId.trim() || !script.trim()}>Extract</Button>
            </div>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader className="pb-2"><CardTitle>Tool Suite (Deep/Form/Upload/Report)</CardTitle></CardHeader>
        <CardContent className="space-y-3">
          <div className="grid gap-3 md:grid-cols-3">
            <label className="text-xs text-muted-foreground">
              Asset kind
              <select className="mt-1 w-full rounded border border-border bg-input px-2 py-2 text-sm text-foreground" value={assetKind} onChange={(e) => setAssetKind(e.target.value)}>
                <option value="image">image</option>
                <option value="video">video</option>
                <option value="pdf">pdf</option>
                <option value="text">text</option>
                <option value="csv">csv</option>
                <option value="json">json</option>
                <option value="binary">binary</option>
              </select>
            </label>
            <label className="text-xs text-muted-foreground">
              Asset name
              <Input value={assetName} onChange={(e) => setAssetName(e.target.value)} placeholder="upload-fixture" />
            </label>
            <label className="text-xs text-muted-foreground">
              Aggression
              <select className="mt-1 w-full rounded border border-border bg-input px-2 py-2 text-sm text-foreground" value={aggressionMode} onChange={(e) => setAggressionMode(e.target.value)}>
                <option value="safe">safe</option>
                <option value="normal">normal</option>
                <option value="aggressive">aggressive</option>
                <option value="destructive-test">destructive-test</option>
              </select>
            </label>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button
              size="sm"
              variant="outline"
              onClick={() =>
                runTool.mutate(
                  { tool: "generate_test_asset", payload: { node_id: nodeId.trim() || undefined, kind: assetKind, name: assetName } },
                  { onSuccess: (row) => setResult(row) },
                )
              }
            >
              Generate Asset
            </Button>
            <Button
              size="sm"
              variant="outline"
              onClick={() =>
                runTool.mutate(
                  {
                    tool: "deep_explore_page",
                    payload: {
                      node_id: nodeId.trim() || undefined,
                      session_id: sessionId.trim() || undefined,
                      aggression: aggressionMode,
                      allow_destructive: aggressionMode === "destructive-test",
                      items: [{ selector, text: value || selector, role: "button" }],
                    },
                  },
                  { onSuccess: (row) => setResult(row) },
                )
              }
            >
              Plan Deep Explore
            </Button>
            <Button
              size="sm"
              variant="outline"
              onClick={() =>
                runTool.mutate(
                  {
                    tool: "summarize_run",
                    payload: {
                      status: "interactive",
                      summary_text: "Interactive session summary",
                      counts: { actions: 1, session: sessionId ? 1 : 0 },
                    },
                  },
                  { onSuccess: (row) => setResult(row) },
                )
              }
            >
              Build Report
            </Button>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-2"><CardTitle>Advanced Action Executor</CardTitle></CardHeader>
        <CardContent className="space-y-3">
          <div className="grid gap-3 md:grid-cols-3">
            <label className="text-xs text-muted-foreground">
              Action
              <Input value={customAction} onChange={(e) => setCustomAction(e.target.value)} placeholder="scan_page, deep_explore_page, network_log..." />
            </label>
            <label className="text-xs text-muted-foreground md:col-span-2">
              JSON payload (merged with node/session/timeout)
              <Textarea rows={3} value={customPayload} onChange={(e) => setCustomPayload(e.target.value)} placeholder='{"selector":"button.submit"}' />
            </label>
          </div>
          <Button
            size="sm"
            variant="outline"
            onClick={() => {
              let parsed: Record<string, unknown> = {};
              try {
                parsed = customPayload.trim() ? (JSON.parse(customPayload) as Record<string, unknown>) : {};
              } catch (err) {
                setResult({ ok: false, error: `Invalid JSON payload: ${String(err)}` });
                return;
              }
              mutateAction(customAction.trim(), parsed);
            }}
            disabled={!sessionId.trim() || !customAction.trim()}
          >
            Execute Advanced Action
          </Button>
        </CardContent>
      </Card>

      {(createSession.error || getSessionStatus.error || closeSession.error || runAction.error || runTool.error) ? (
        <p className="text-sm text-danger">
          {String(createSession.error ?? getSessionStatus.error ?? closeSession.error ?? runAction.error ?? runTool.error)}
        </p>
      ) : null}

      <Card>
        <CardHeader className="pb-2"><CardTitle>Latest Action Result</CardTitle></CardHeader>
        <CardContent>
          <pre className="max-h-[420px] overflow-auto rounded border border-border bg-background/40 p-2 text-xs text-muted-foreground">
            {JSON.stringify(actionResult ?? { hint: "Start a session, then run click/fill/upload/press actions here." }, null, 2)}
          </pre>
        </CardContent>
      </Card>
    </div>
  );
}

function ReportsSection() {
  const reports = useWebAgentReports();
  return (
    <Card>
      <CardHeader className="pb-2"><CardTitle>Saved Reports</CardTitle></CardHeader>
      <CardContent className="space-y-2">
        {(reports.data ?? []).map((report) => (
          <div key={report.id} className="rounded border border-border p-2">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <p className="text-sm font-semibold">{report.title}</p>
              <p className="text-xs text-muted-foreground">{relTime(report.created_at)}</p>
            </div>
            <p className="mt-1 text-xs text-muted-foreground">{report.summary_markdown}</p>
            <div className="mt-2">
              <Link to={`/modules/webagent/runs/${report.run_id}`}><Button size="sm" variant="outline">Open Run</Button></Link>
            </div>
          </div>
        ))}
        {(reports.data?.length ?? 0) === 0 ? <p className="text-sm text-muted-foreground">No saved reports yet.</p> : null}
      </CardContent>
    </Card>
  );
}

function StatusSection() {
  const status = useWebAgentStatus();
  const node = status.data?.node;
  const cfg = status.data?.config;
  const setup = status.data?.setup;
  return (
    <div className="space-y-4">
      <Card>
        <CardHeader className="pb-2"><CardTitle>WebAgent Node Status</CardTitle></CardHeader>
        <CardContent className="grid gap-2 md:grid-cols-4">
          <MetricCard title="Node ID" value={node?.id ?? "-"} />
          <MetricCard title="Label" value={node?.label ?? "-"} />
          <MetricCard title="Enabled" value={String(node?.enabled ?? false)} />
          <MetricCard title="Base URL" value={node?.base_url ?? "-"} />
        </CardContent>
      </Card>
      <Card>
        <CardHeader className="pb-2"><CardTitle>Server Config Diagnostics</CardTitle></CardHeader>
        <CardContent className="grid gap-2 md:grid-cols-4">
          <MetricCard title="Configured" value={String(setup?.configured ?? cfg?.configured ?? false)} />
          <MetricCard title="Config Source" value={String(cfg?.source ?? "-")} />
          <MetricCard title="Token Ready" value={String(cfg?.node_api_token_configured ?? false)} />
          <MetricCard title="Bridge Base" value={String(cfg?.node_api_base ?? "-")} />
          {(setup?.issues ?? cfg?.issues ?? []).length > 0 ? (
            <div className="md:col-span-4 rounded border border-warning/40 bg-warning/10 p-2 text-xs text-warning">
              {(setup?.issues ?? cfg?.issues ?? []).join(" | ")}
            </div>
          ) : null}
        </CardContent>
      </Card>
      <Card>
        <CardHeader className="pb-2"><CardTitle>Capabilities</CardTitle></CardHeader>
        <CardContent className="flex flex-wrap gap-2">
          {(status.data?.capabilities ?? []).map((cap) => <span key={cap} className="rounded bg-primary/15 px-2 py-1 text-xs text-primary">{cap}</span>)}
        </CardContent>
      </Card>
      <Card>
        <CardHeader className="pb-2"><CardTitle>Raw Health</CardTitle></CardHeader>
        <CardContent>
          <pre className="max-h-80 overflow-auto rounded border border-border bg-background/40 p-2 text-xs text-muted-foreground">{JSON.stringify(status.data?.health ?? {}, null, 2)}</pre>
        </CardContent>
      </Card>
    </div>
  );
}

function MetricCard({ title, value }: { title: string; value: string }) {
  return (
    <Card>
      <CardHeader className="pb-1"><CardTitle className="text-xs text-muted-foreground">{title}</CardTitle></CardHeader>
      <CardContent><p className="text-lg font-bold">{value}</p></CardContent>
    </Card>
  );
}

function toRows(value: unknown): Array<Record<string, unknown>> {
  if (!Array.isArray(value)) return [];
  return value.filter((v) => typeof v === "object" && v !== null) as Array<Record<string, unknown>>;
}

function Panel({ title, icon, rows }: { title: string; icon: ReactNode; rows: Array<Record<string, unknown>> }) {
  return (
    <Card>
      <CardHeader className="pb-2"><CardTitle className="flex items-center gap-2 text-sm">{icon}{title}</CardTitle></CardHeader>
      <CardContent>
        <div className="max-h-56 space-y-1 overflow-auto rounded border border-border bg-background/40 p-2 text-xs text-muted-foreground">
          {rows.length ? rows.slice(0, 200).map((row, idx) => <pre key={idx}>{JSON.stringify(row, null, 2)}</pre>) : <p>No data.</p>}
        </div>
      </CardContent>
    </Card>
  );
}

export function WebAgentPage() {
  const location = useLocation();
  const path = location.pathname;
  const detail = path.startsWith("/modules/webagent/runs/") && path.split("/").length >= 5;
  const view = detail ? "run-detail" : path.endsWith("/new") ? "new" : path.endsWith("/interactive") ? "interactive" : path.endsWith("/runs") ? "runs" : path.endsWith("/reports") ? "reports" : path.endsWith("/status") ? "status" : "overview";

  return (
    <div className="space-y-4">
      <PageHeader compact title="WebAgent">
        <WebAgentTabs />
      </PageHeader>
      {view === "overview" ? <OverviewSection /> : null}
      {view === "new" ? <NewRunSection /> : null}
      {view === "interactive" ? <InteractiveSection /> : null}
      {view === "runs" ? <RunsSection /> : null}
      {view === "run-detail" ? <RunDetailSection /> : null}
      {view === "reports" ? <ReportsSection /> : null}
      {view === "status" ? <StatusSection /> : null}
    </div>
  );
}
