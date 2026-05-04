import { type FormEvent, useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { AlertTriangle, Bot, CheckCircle2, Globe2, Loader2, Play, Plus, RefreshCw, Search, ShieldAlert, Square } from "lucide-react";

import {
  useCreateSkilledAgent,
  useCreateSkilledSkill,
  useCreateSkilledAgentFromTemplate,
  useSkilledAgent,
  useSkilledAgentLatestSnapshot,
  useSkilledAgentLogs,
  useSkilledAgentManifest,
  useSkilledAgentSnapshots,
  useSkilledAgentStatus,
  useSkilledAgentWorkspace,
  useSkilledAgents,
  useSkilledAgentsHealth,
  useSkilledDeployAgent,
  useSkilledStarterTemplates,
  useSkilledPrepareAgent,
  usePreviewSkilledAgentFromTemplate,
  useSkilledRunSmokeTest,
  useSkilledRunValidation,
  useSkilledRunAgent,
  useSkilledSkills,
  useSkilledStopAgent,
  useSkilledTemplate,
  useSkilledTemplates,
  useUpdateSkilledAgent,
} from "../../shared/api/hooks";
import type {
  SkilledAgent,
  SkilledAgentCreateRequest,
  SkilledStarterTemplate,
  SkilledAgentTemplateSummary,
  SkilledSkillSummary,
} from "../../shared/api/types";
import { Button } from "../../shared/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "../../shared/components/ui/card";
import { Input, Textarea } from "../../shared/components/ui/input";
import { PageHeader } from "../../shared/components/ui/page-header";

type WizardStep = 1 | 2 | 3 | 4 | 5;

function rel(iso?: string | null): string {
  if (!iso) return "Never";
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return "Unknown";
  const sec = Math.max(0, Math.floor((Date.now() - t) / 1000));
  if (sec < 60) return `${sec}s ago`;
  const min = Math.floor(sec / 60);
  if (min < 60) return `${min}m ago`;
  const hr = Math.floor(min / 60);
  if (hr < 24) return `${hr}h ago`;
  return `${Math.floor(hr / 24)}d ago`;
}

function tone(status?: string): string {
  const s = String(status ?? "").toLowerCase();
  if (["running", "deploying", "preparing"].includes(s)) return "text-warning bg-warning/10 border-warning/30";
  if (["error", "failed"].includes(s)) return "text-danger bg-danger/10 border-danger/30";
  if (["deployed", "prepared", "idle"].includes(s)) return "text-success bg-success/10 border-success/30";
  return "text-muted-foreground bg-background/30 border-border";
}

const DEPLOY_MODE_DESCRIPTIONS: Record<string, string> = {
  safe: "Read-only, no network, no YOLO. Best for low-risk dry runs.",
  sandboxed: "Workspace-write, no network, no YOLO. Good default.",
  networked: "Workspace-write with network access; still no YOLO.",
  yolo: "Danger-full-access with network and high autonomy.",
};

function CompatibilityBadges({ badges }: { badges?: Record<string, boolean> }) {
  const rows = Object.entries(badges || {}).filter(([, v]) => Boolean(v));
  if (rows.length === 0) return <span className="text-xs text-muted-foreground">No special requirements</span>;
  return (
    <div className="flex flex-wrap gap-1">
      {rows.map(([k]) => (
        <span key={k} className="rounded border border-border px-1.5 py-0.5 text-[11px] text-muted-foreground">
          {k.replace(/^requires_/, "")}
        </span>
      ))}
    </div>
  );
}

function SkilledAgentsTabs() {
  return (
    <div className="flex flex-wrap gap-2">
      <Link to="/modules/skilled-agents"><Button size="sm" variant="outline">Overview</Button></Link>
      <Link to="/modules/skilled-agents/new"><Button size="sm" variant="outline">Create Wizard</Button></Link>
      <Link to="/modules/skilled-agents/library"><Button size="sm" variant="outline">Templates + Skills</Button></Link>
    </div>
  );
}

function SkillPicker({
  skills,
  selected,
  onToggle,
  showCategory = true,
}: {
  skills: SkilledSkillSummary[];
  selected: string[];
  onToggle: (skill: SkilledSkillSummary) => void;
  showCategory?: boolean;
}) {
  const [q, setQ] = useState("");
  const categories = useMemo(
    () => Array.from(new Set(skills.map((s) => s.category).filter(Boolean))).sort(),
    [skills],
  );
  const [category, setCategory] = useState<string>("all");

  const filtered = useMemo(
    () => skills.filter((s) => {
      const hay = `${s.name} ${s.slug} ${s.description} ${(s.tags || []).join(" ")}`.toLowerCase();
      const qok = !q.trim() || hay.includes(q.trim().toLowerCase());
      const cok = category === "all" || s.category === category;
      return qok && cok;
    }),
    [skills, q, category],
  );

  return (
    <div className="space-y-3">
      <div className="grid gap-2 md:grid-cols-3">
        <label className="md:col-span-2 text-xs text-muted-foreground">
          Search Skills
          <div className="relative mt-1">
            <Search size={14} className="absolute left-2 top-2.5 text-muted-foreground" />
            <Input className="pl-7" value={q} onChange={(e) => setQ(e.target.value)} placeholder="search by name, category, tags..." />
          </div>
        </label>
        {showCategory ? (
          <label className="text-xs text-muted-foreground">
            Category
            <select
              className="mt-1 w-full rounded-lg border border-border bg-input px-2 py-2 text-sm"
              value={category}
              onChange={(e) => setCategory(e.target.value)}
            >
              <option value="all">All</option>
              {categories.map((c) => <option key={c} value={c}>{c}</option>)}
            </select>
          </label>
        ) : null}
      </div>

      <div className="max-h-[420px] overflow-auto space-y-2 pr-1">
        {filtered.map((skill) => {
          const active = selected.includes(skill.id) || selected.includes(skill.slug);
          return (
            <button
              type="button"
              key={skill.id}
              onClick={() => onToggle(skill)}
              className={`w-full rounded-lg border p-3 text-left transition ${active ? "border-primary/50 bg-primary/10" : "border-border bg-background/20 hover:bg-background/35"}`}
            >
              <div className="flex items-start justify-between gap-3">
                <div>
                  <p className="text-sm font-semibold text-foreground">{skill.name}</p>
                  <p className="text-[11px] text-muted-foreground">{skill.slug} · {skill.category} · v{skill.version}</p>
                </div>
                <span className={`rounded border px-2 py-0.5 text-[11px] ${active ? "border-primary/40 text-primary" : "border-border text-muted-foreground"}`}>
                  {active ? "Selected" : "Attach"}
                </span>
              </div>
              <p className="mt-1 text-xs text-muted-foreground">{skill.description}</p>
            </button>
          );
        })}
        {filtered.length === 0 ? (
          <div className="rounded-lg border border-border bg-background/20 p-3 text-sm text-muted-foreground">No matching skills.</div>
        ) : null}
      </div>
    </div>
  );
}

export function SkilledAgentsOverviewPage() {
  const { data: agents = [], isLoading, refetch, isFetching } = useSkilledAgents();
  const { data: health } = useSkilledAgentsHealth();
  const { data: starterTemplates = [] } = useSkilledStarterTemplates();

  const metrics = useMemo(() => {
    const active = agents.filter((a) => ["running", "deploying", "preparing"].includes(String(a.status).toLowerCase())).length;
    const failed = agents.filter((a) => ["error", "failed"].includes(String(a.status).toLowerCase())).length;
    const recentlyRun = agents.filter((a) => a.last_run_at).length;
    return { total: agents.length, active, failed, recentlyRun };
  }, [agents]);

  return (
    <div className="space-y-4">
      <PageHeader
        compact
        title="Skilled Agents"
        description="Create, configure, deploy, and monitor specialized agents through a wizard-driven control plane."
        actions={
          <>
            <Button variant="outline" onClick={() => refetch()} disabled={isFetching}>{isFetching ? <Loader2 size={13} className="animate-spin" /> : <RefreshCw size={13} />} Refresh</Button>
            <Link to="/modules/skilled-agents/new"><Button><Plus size={13} /> Create Agent</Button></Link>
          </>
        }
      >
        <SkilledAgentsTabs />
      </PageHeader>

      <div className="grid gap-3 md:grid-cols-4">
        <MetricCard label="Total Agents" value={metrics.total} />
        <MetricCard label="Active Agents" value={metrics.active} tone="success" />
        <MetricCard label="Failed Agents" value={metrics.failed} tone="danger" />
        <MetricCard label="Recently Run" value={metrics.recentlyRun} tone="warning" />
      </div>
      <div className="grid gap-3 md:grid-cols-4">
        <MetricCard label="Starter Templates" value={starterTemplates.length} />
        <MetricCard label="WebAgent Templates" value={starterTemplates.filter((t) => t.uses_webagent).length} tone="warning" />
      </div>

      <Card>
        <CardHeader className="pb-2">
          <CardTitle>Server Health</CardTitle>
        </CardHeader>
        <CardContent className="text-sm text-muted-foreground">
          {health ? (
            <div className="flex flex-wrap items-center gap-3">
              <span className={`rounded border px-2 py-1 text-xs ${health.ok ? "border-success/40 bg-success/10 text-success" : "border-danger/40 bg-danger/10 text-danger"}`}>
                {health.ok ? "Healthy" : "Unhealthy"}
              </span>
              <span>Service: {health.service}</span>
              <span>Tracked agents: {health.agents_count ?? "-"}</span>
              <span>Starter templates: {health.starter_templates_count ?? starterTemplates.length}</span>
            </div>
          ) : (
            <span>No health data yet.</span>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-2">
          <CardTitle>Agents</CardTitle>
        </CardHeader>
        <CardContent>
          {isLoading ? <p className="text-sm text-muted-foreground">Loading agents...</p> : null}
          {!isLoading && agents.length === 0 ? (
            <div className="rounded-lg border border-border bg-background/20 p-4 text-sm text-muted-foreground">
              No agents found. Create your first specialized agent.
            </div>
          ) : null}
          {agents.length > 0 ? (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[920px] text-sm">
                <thead>
                  <tr className="text-left text-xs uppercase tracking-[0.08em] text-muted-foreground">
                    <th className="px-3 py-2">Name</th>
                    <th className="px-3 py-2">Type</th>
                    <th className="px-3 py-2">Skills</th>
                    <th className="px-3 py-2">Status</th>
                    <th className="px-3 py-2">Mode</th>
                    <th className="px-3 py-2">Last Run</th>
                    <th className="px-3 py-2">Quick Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {agents.map((agent) => (
                    <tr key={agent.id} className="border-t border-border/60">
                      <td className="px-3 py-2">
                        <Link className="font-medium text-foreground hover:text-primary" to={`/modules/skilled-agents/${agent.id}`}>
                          {agent.name}
                        </Link>
                        <p className="text-xs text-muted-foreground">{agent.slug}</p>
                      </td>
                      <td className="px-3 py-2 text-xs text-muted-foreground">{agent.agent_type}</td>
                      <td className="px-3 py-2 text-xs text-muted-foreground">{agent.selected_skills.length}</td>
                      <td className="px-3 py-2">
                        <span className={`rounded border px-2 py-0.5 text-xs ${tone(agent.status)}`}>{agent.status}</span>
                      </td>
                      <td className="px-3 py-2 text-xs">
                        <span className={`rounded border px-1.5 py-0.5 ${agent.yolo_mode ? "border-warning/40 bg-warning/10 text-warning" : "border-border text-muted-foreground"}`}>YOLO {agent.yolo_mode ? "On" : "Off"}</span>
                        <span className="ml-1 rounded border border-border px-1.5 py-0.5 text-muted-foreground">{agent.sandbox_mode}</span>
                      </td>
                      <td className="px-3 py-2 text-xs text-muted-foreground">{rel(agent.last_run_at)}</td>
                      <td className="px-3 py-2">
                        <div className="flex flex-wrap gap-1">
                          <Link to={`/modules/skilled-agents/${agent.id}`}><Button size="sm" variant="outline">Open</Button></Link>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : null}
        </CardContent>
      </Card>
    </div>
  );
}

function MetricCard({ label, value, tone: _tone = "default" }: { label: string; value: number; tone?: "default" | "success" | "warning" | "danger" }) {
  return (
    <Card>
      <CardContent className="px-4 py-4">
        <p className="text-[11px] uppercase tracking-[0.1em] text-muted-foreground">{label}</p>
        <p className="mt-1 text-2xl font-semibold text-foreground">{value}</p>
      </CardContent>
    </Card>
  );
}

function buildInitialForm(): SkilledAgentCreateRequest {
  return {
    name: "",
    slug: "",
    description: "",
    agent_type: "general",
    runtime: "python",
    model_provider: "openai",
    model_name: "gpt-5",
    model_settings: { temperature: 0.2 },
    selected_skills: [],
    env_config: {},
    flags: {},
    network_access: false,
    sandbox_mode: "workspace-write",
    yolo_mode: false,
    template_id: null,
    specialization_mode: "strict",
    role_identity: "general",
    domain_focus: "",
    execution_mode: "task",
    allowed_tools: [],
    runtime_policies: {},
    saved_prompts: {},
    specialization_metadata: {},
  };
}

function firstTemplateId(templates: SkilledAgentTemplateSummary[]): string | null {
  return templates.length > 0 ? templates[0].id : null;
}

export function SkilledAgentCreatePage() {
  const navigate = useNavigate();
  const { data: skills = [] } = useSkilledSkills();
  const { data: starterTemplates = [] } = useSkilledStarterTemplates();
  const sortedStarterTemplates = useMemo(
    () => [...starterTemplates].sort((a, b) => {
      const atop = a.is_top_agent ? 0 : 1;
      const btop = b.is_top_agent ? 0 : 1;
      if (atop !== btop) return atop - btop;
      const arank = Number(a.top_rank ?? 999);
      const brank = Number(b.top_rank ?? 999);
      if (arank !== brank) return arank - brank;
      return a.name.localeCompare(b.name);
    }),
    [starterTemplates],
  );
  const { data: templates = [] } = useSkilledTemplates();
  const [selectedTemplateId, setSelectedTemplateId] = useState<string | null>(null);
  const { data: selectedTemplate } = useSkilledTemplate(selectedTemplateId);
  const createAgent = useCreateSkilledAgent();
  const createFromTemplate = useCreateSkilledAgentFromTemplate();
  const previewFromTemplate = usePreviewSkilledAgentFromTemplate();
  const prepare = useSkilledPrepareAgent();
  const deploy = useSkilledDeployAgent();

  const [step, setStep] = useState<WizardStep>(1);
  const [startingPoint, setStartingPoint] = useState<"blank" | "starter-template">("starter-template");
  const [starterSlug, setStarterSlug] = useState<string>("");
  const [form, setForm] = useState<SkilledAgentCreateRequest>(buildInitialForm());
  const [skillConfig, setSkillConfig] = useState<Record<string, Record<string, unknown>>>({});
  const [deployMode, setDeployMode] = useState<"safe" | "sandboxed" | "networked" | "yolo">("sandboxed");
  const [createMode, setCreateMode] = useState<"create" | "create_prepare" | "create_deploy">("create_deploy");

  useEffect(() => {
    if (selectedTemplateId || templates.length === 0) return;
    const first = firstTemplateId(templates);
    if (first) setSelectedTemplateId(first);
  }, [selectedTemplateId, templates]);

  useEffect(() => {
    if (!selectedTemplate) return;
    setForm((prev) => ({
      ...prev,
      template_id: selectedTemplate.id,
      specialization_mode:
        prev.template_id !== selectedTemplate.id
          ? (selectedTemplate.strict_by_default ? "strict" : "custom")
          : (prev.specialization_mode || "strict"),
      agent_type: selectedTemplate.agent_type || prev.agent_type,
      role_identity: prev.role_identity && prev.role_identity !== "general" ? prev.role_identity : selectedTemplate.agent_type,
      domain_focus: prev.domain_focus || selectedTemplate.domain_focus,
      execution_mode: prev.execution_mode || selectedTemplate.execution_mode,
      runtime: selectedTemplate.runtime || prev.runtime,
      model_provider: prev.model_provider || selectedTemplate.model_provider || null,
      model_name: prev.model_name || selectedTemplate.model_name || null,
      selected_skills: Array.from(new Set([...(selectedTemplate.recommended_skills || []), ...(prev.selected_skills || [])])),
      allowed_tools: prev.allowed_tools && prev.allowed_tools.length > 0 ? prev.allowed_tools : selectedTemplate.allowed_tools,
      runtime_policies: { ...(selectedTemplate.runtime_policies || {}), ...(prev.runtime_policies || {}) },
      saved_prompts: { ...(selectedTemplate.default_prompts || {}), ...(prev.saved_prompts || {}) },
      specialization_metadata: {
        ...(prev.specialization_metadata || {}),
        template_version: selectedTemplate.version,
        disallowed_capabilities: selectedTemplate.disallowed_capabilities,
        execution_expectations: selectedTemplate.execution_expectations,
        ui_hints: selectedTemplate.ui_hints,
      },
    }));
  }, [selectedTemplate]);

  useEffect(() => {
    if (starterSlug || sortedStarterTemplates.length === 0) return;
    setStarterSlug(sortedStarterTemplates[0].slug);
  }, [starterSlug, sortedStarterTemplates]);

  const selectedStarter = useMemo(
    () => sortedStarterTemplates.find((t) => t.slug === starterSlug) ?? null,
    [sortedStarterTemplates, starterSlug],
  );

  const activeSkills = useMemo(
    () => skills.filter((s) => (form.selected_skills || []).includes(s.id) || (form.selected_skills || []).includes(s.slug)),
    [skills, form.selected_skills],
  );

  const canNextBasics = Boolean(form.name?.trim() && form.slug?.trim());

  async function createAndDeploy() {
    if (startingPoint === "starter-template" && selectedStarter) {
      const created = await createFromTemplate.mutateAsync({
        template_slug: selectedStarter.slug,
        name: form.name,
        slug: form.slug,
        description: form.description,
        deploy_mode: deployMode,
        overrides: {
          runtime: form.runtime,
          model_provider: form.model_provider,
          model_name: form.model_name,
          selected_skills: form.selected_skills,
          flags: { ...(form.flags || {}), skill_config: skillConfig },
        },
      });
      if (createMode !== "create") {
        await prepare.mutateAsync({ agentId: created.id });
      }
      if (createMode === "create_deploy") {
        await deploy.mutateAsync({ agentId: created.id });
      }
      navigate(`/modules/skilled-agents/${created.id}`);
      return;
    }

    const payload: SkilledAgentCreateRequest = {
      ...form,
      flags: { ...(form.flags || {}), skill_config: skillConfig },
    };
    const created = await createAgent.mutateAsync(payload);
    if (createMode !== "create") {
      await prepare.mutateAsync({ agentId: created.id });
    }
    if (createMode === "create_deploy") {
      await deploy.mutateAsync({ agentId: created.id });
    }
    navigate(`/modules/skilled-agents/${created.id}`);
  }

  return (
    <div className="space-y-4">
      <PageHeader compact title="Create Skilled Agent" description="Five-step wizard for predictable, auditable agent setup.">
        <SkilledAgentsTabs />
      </PageHeader>

      <Card>
        <CardContent className="px-4 py-4">
          <div className="flex flex-wrap gap-2">
            {[1, 2, 3, 4, 5].map((s) => (
              <button
                key={s}
                className={`rounded px-2 py-1 text-xs border ${step === s ? "border-primary/40 bg-primary/15 text-primary" : "border-border text-muted-foreground"}`}
                onClick={() => setStep(s as WizardStep)}
                type="button"
              >
                Step {s}
              </button>
            ))}
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardContent className="px-4 py-4 space-y-4">
          {step === 1 ? (
            <div className="space-y-3">
              <h3 className="text-sm font-semibold">1. Basics</h3>
              <div className="grid gap-3 md:grid-cols-2">
                <label className="text-xs text-muted-foreground">
                  Starting Point
                  <select
                    className="mt-1 w-full rounded-lg border border-border bg-input px-2 py-2 text-sm"
                    value={startingPoint}
                    onChange={(e) => setStartingPoint(e.target.value as "blank" | "starter-template")}
                  >
                    <option value="starter-template">Starter Template</option>
                    <option value="blank">Blank Agent</option>
                  </select>
                </label>
                <label className="text-xs text-muted-foreground">
                  Agent Template
                  <select
                    className="mt-1 w-full rounded-lg border border-border bg-input px-2 py-2 text-sm"
                    value={startingPoint === "starter-template" ? starterSlug : (selectedTemplateId ?? "")}
                    onChange={(e) => {
                      if (startingPoint === "starter-template") setStarterSlug(e.target.value);
                      else setSelectedTemplateId(e.target.value);
                    }}
                  >
                    {startingPoint === "starter-template"
                      ? sortedStarterTemplates.map((t) => <option key={t.slug} value={t.slug}>{t.is_top_agent ? `Top: ${t.name}` : t.name}</option>)
                      : templates.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
                  </select>
                </label>
                <label className="text-xs text-muted-foreground">
                  Name
                  <Input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="Market Research Agent" />
                </label>
                <label className="text-xs text-muted-foreground">
                  Slug
                  <Input
                    value={form.slug}
                    onChange={(e) => setForm({ ...form, slug: e.target.value.toLowerCase().replace(/[^a-z0-9-]/g, "-") })}
                    placeholder="market-research-agent"
                  />
                </label>
                <label className="text-xs text-muted-foreground md:col-span-2">
                  Description
                  <Textarea rows={3} value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} />
                </label>
                {startingPoint === "starter-template" && selectedStarter ? (
                  <div className="md:col-span-2 rounded-lg border border-border bg-background/20 p-3 text-xs text-muted-foreground space-y-2">
                    <p className="font-semibold text-foreground">{selectedStarter.name}</p>
                    <p>{selectedStarter.description}</p>
                    {selectedStarter.is_top_agent ? <p><strong>Tier:</strong> Top Agent #{selectedStarter.top_rank ?? "-"}</p> : null}
                    <p><strong>Pack:</strong> {selectedStarter.pack_version} ({selectedStarter.source_pack})</p>
                    <p><strong>Recommended Deploy Mode:</strong> {selectedStarter.recommended_deploy_mode}</p>
                    <CompatibilityBadges badges={selectedStarter.compatibility_badges} />
                    {selectedStarter.uses_webagent ? (
                      <p className="text-warning flex items-center gap-1"><Globe2 size={12} /> Uses WebAgent (delegated Playwright analyzer)</p>
                    ) : null}
                  </div>
                ) : null}
                {startingPoint === "blank" && selectedTemplate ? (
                  <div className="md:col-span-2 rounded-lg border border-border bg-background/20 p-3 text-xs text-muted-foreground space-y-1">
                    <p className="font-semibold text-foreground">{selectedTemplate.name}</p>
                    <p>{selectedTemplate.description}</p>
                    <p><strong>Expectations:</strong> {selectedTemplate.execution_expectations.join(" | ") || "n/a"}</p>
                    <p><strong>Disallowed:</strong> {selectedTemplate.disallowed_capabilities.join(", ") || "none"}</p>
                  </div>
                ) : null}
              </div>
            </div>
          ) : null}

          {step === 2 ? (
            <div className="space-y-3">
              <h3 className="text-sm font-semibold">2. Runtime</h3>
              <div className="grid gap-3 md:grid-cols-2">
                <label className="text-xs text-muted-foreground">
                  Runtime
                  <select className="mt-1 w-full rounded-lg border border-border bg-input px-2 py-2 text-sm" value={form.runtime} onChange={(e) => setForm({ ...form, runtime: e.target.value })}>
                    <option value="python">python</option>
                    <option value="node">node</option>
                    <option value="bash">bash</option>
                  </select>
                </label>
                <label className="text-xs text-muted-foreground">
                  Model Provider
                  <Input value={form.model_provider ?? ""} onChange={(e) => setForm({ ...form, model_provider: e.target.value })} placeholder="openai" />
                </label>
                <label className="text-xs text-muted-foreground">
                  Model Name
                  <Input value={form.model_name ?? ""} onChange={(e) => setForm({ ...form, model_name: e.target.value })} placeholder="gpt-5" />
                </label>
                <label className="text-xs text-muted-foreground">
                  Workspace Path (optional)
                  <Input value={form.workspace_path ?? ""} onChange={(e) => setForm({ ...form, workspace_path: e.target.value || null })} placeholder="/srv/skilledagents/workspaces/my-agent" />
                </label>
              </div>
            </div>
          ) : null}

          {step === 3 ? (
            <div className="space-y-3">
              <h3 className="text-sm font-semibold">3. Skills</h3>
              <p className="text-xs text-muted-foreground">Attach capability packs. Each skill includes metadata and description for transparent composition.</p>
              <SkillPicker
                skills={skills}
                selected={form.selected_skills || []}
                onToggle={(skill) => {
                  const has = (form.selected_skills || []).includes(skill.id) || (form.selected_skills || []).includes(skill.slug);
                  setForm({
                    ...form,
                    selected_skills: has
                      ? (form.selected_skills || []).filter((s) => s !== skill.id && s !== skill.slug)
                      : [...(form.selected_skills || []), skill.slug],
                  });
                }}
              />

              {activeSkills.length > 0 ? (
                <div className="space-y-2">
                  <p className="text-xs font-semibold text-muted-foreground uppercase tracking-[0.1em]">Skill Options</p>
                  {activeSkills.map((skill) => (
                    <div key={skill.id} className="rounded-lg border border-border bg-background/20 p-3">
                      <p className="text-sm font-medium">{skill.name}</p>
                      <p className="text-xs text-muted-foreground mb-2">{skill.description}</p>
                      <label className="text-xs text-muted-foreground">
                        JSON Options (from skill schema if available)
                        <Textarea
                          rows={3}
                          value={JSON.stringify(skillConfig[skill.slug] || {}, null, 2)}
                          onChange={(e) => {
                            try {
                              const parsed = JSON.parse(e.target.value || "{}");
                              setSkillConfig((prev) => ({ ...prev, [skill.slug]: parsed }));
                            } catch {
                              // keep existing config until valid json
                            }
                          }}
                        />
                      </label>
                    </div>
                  ))}
                </div>
              ) : null}
            </div>
          ) : null}

          {step === 4 ? (
            <div className="space-y-3">
              <h3 className="text-sm font-semibold">4. Permissions / Execution Mode</h3>
              <div className="grid gap-3 md:grid-cols-2">
                <label className="text-xs text-muted-foreground">
                  Deploy Mode
                  <select
                    className="mt-1 w-full rounded-lg border border-border bg-input px-2 py-2 text-sm"
                    value={deployMode}
                    onChange={(e) => setDeployMode(e.target.value as "safe" | "sandboxed" | "networked" | "yolo")}
                  >
                    <option value="safe">safe</option>
                    <option value="sandboxed">sandboxed</option>
                    <option value="networked">networked</option>
                    <option value="yolo">yolo</option>
                  </select>
                  <p className="mt-1 text-[11px]">{DEPLOY_MODE_DESCRIPTIONS[deployMode]}</p>
                  {selectedStarter && selectedStarter.recommended_deploy_mode !== deployMode ? (
                    <p className="mt-1 text-warning flex items-center gap-1"><AlertTriangle size={12} /> Template recommends `{selectedStarter.recommended_deploy_mode}`</p>
                  ) : null}
                </label>
                <label className="text-xs text-muted-foreground">
                  Specialization Mode
                  <select
                    className="mt-1 w-full rounded-lg border border-border bg-input px-2 py-2 text-sm"
                    value={form.specialization_mode || "strict"}
                    onChange={(e) => setForm({ ...form, specialization_mode: e.target.value as "strict" | "custom" })}
                  >
                    <option value="strict">strict specialization</option>
                    <option value="custom">advanced override / custom</option>
                  </select>
                </label>
                <label className="text-xs text-muted-foreground">
                  Role Identity
                  <Input
                    value={form.role_identity ?? ""}
                    onChange={(e) => setForm({ ...form, role_identity: e.target.value })}
                    disabled={(form.specialization_mode || "strict") !== "custom"}
                    placeholder="marketing_ideas_agent"
                  />
                </label>
                <label className="text-xs text-muted-foreground">
                  Domain Focus
                  <Input value={form.domain_focus ?? ""} onChange={(e) => setForm({ ...form, domain_focus: e.target.value })} placeholder="content research" />
                </label>
                <label className="text-xs text-muted-foreground">
                  Execution Mode
                  <Input value={form.execution_mode ?? ""} onChange={(e) => setForm({ ...form, execution_mode: e.target.value })} placeholder="task | research | brainstorm" />
                </label>
                <label className="text-xs text-muted-foreground">
                  Sandbox Mode
                  <select className="mt-1 w-full rounded-lg border border-border bg-input px-2 py-2 text-sm" value={form.sandbox_mode} onChange={(e) => setForm({ ...form, sandbox_mode: e.target.value })}>
                    <option value="workspace-write">workspace-write</option>
                    <option value="read-only">read-only</option>
                    <option value="danger-full-access">danger-full-access</option>
                  </select>
                </label>
                <label className="text-xs text-muted-foreground">
                  Network Access
                  <select
                    className="mt-1 w-full rounded-lg border border-border bg-input px-2 py-2 text-sm"
                    value={String(form.network_access ?? false)}
                    onChange={(e) => setForm({ ...form, network_access: e.target.value === "true" })}
                    disabled={(form.specialization_mode || "strict") === "strict" && Boolean(selectedTemplate?.disallowed_capabilities.includes("network_access"))}
                  >
                    <option value="false">disabled</option>
                    <option value="true">enabled</option>
                  </select>
                </label>
                <label className="inline-flex items-center gap-2 text-sm text-muted-foreground md:col-span-2">
                  <input
                    type="checkbox"
                    checked={Boolean(form.yolo_mode)}
                    onChange={(e) => setForm({ ...form, yolo_mode: e.target.checked })}
                    disabled={(form.specialization_mode || "strict") === "strict" && Boolean(selectedTemplate?.disallowed_capabilities.includes("yolo_mode"))}
                  />
                  Enable YOLO mode (high-autonomy execution)
                </label>
              </div>
            </div>
          ) : null}

          {step === 5 ? (
            <div className="space-y-3">
              <h3 className="text-sm font-semibold">5. Review & Deploy</h3>
              {startingPoint === "starter-template" && selectedStarter ? (
                <Button
                  size="sm"
                  variant="outline"
                  disabled={previewFromTemplate.isPending}
                  onClick={() => previewFromTemplate.mutate({ template_slug: selectedStarter.slug, deploy_mode: deployMode })}
                >
                  {previewFromTemplate.isPending ? <Loader2 size={12} className="animate-spin" /> : null}
                  Refresh Workspace Preview
                </Button>
              ) : null}
              <div className="rounded-lg border border-border bg-background/20 p-3 text-sm space-y-1">
                <p><strong>Name:</strong> {form.name || "-"}</p>
                <p><strong>Slug:</strong> {form.slug || "-"}</p>
                <p><strong>Starting Point:</strong> {startingPoint === "starter-template" ? "starter-template" : "blank"}</p>
                <p><strong>Template:</strong> {selectedStarter?.name || selectedTemplate?.name || form.template_id || "-"}</p>
                <p><strong>Type:</strong> {form.agent_type}</p>
                <p><strong>Role Identity:</strong> {form.role_identity || "-"}</p>
                <p><strong>Specialization:</strong> {form.specialization_mode || "strict"}</p>
                <p><strong>Domain Focus:</strong> {form.domain_focus || "-"}</p>
                <p><strong>Execution Mode:</strong> {form.execution_mode || "-"}</p>
                <p><strong>Deploy Mode:</strong> {deployMode}</p>
                <p><strong>Runtime:</strong> {form.runtime}</p>
                <p><strong>Model:</strong> {form.model_provider || "-"} / {form.model_name || "-"}</p>
                <p><strong>Skills:</strong> {(form.selected_skills || []).join(", ") || "None"}</p>
                <p><strong>Sandbox:</strong> {form.sandbox_mode}</p>
                <p><strong>Network:</strong> {form.network_access ? "enabled" : "disabled"}</p>
                <p><strong>YOLO:</strong> {form.yolo_mode ? "enabled" : "disabled"}</p>
              </div>
              {previewFromTemplate.data?.preview ? (
                <div className="rounded-lg border border-border bg-background/20 p-3 text-xs space-y-1">
                  <p className="font-semibold">Generated Workspace Preview</p>
                  <p><strong>Entrypoint:</strong> {previewFromTemplate.data.preview.entrypoint}</p>
                  <p><strong>Final Execution Mode:</strong> {previewFromTemplate.data.preview.final_execution_mode}</p>
                  <p><strong>Files:</strong> {previewFromTemplate.data.preview.files_to_create.join(", ") || "none"}</p>
                  <p><strong>Dependencies:</strong> {previewFromTemplate.data.preview.dependencies_to_install.join(", ") || "none"}</p>
                  <p><strong>Skills:</strong> {previewFromTemplate.data.preview.skills_to_attach.join(", ") || "none"}</p>
                  <CompatibilityBadges badges={previewFromTemplate.data.preview.compatibility_badges} />
                  {previewFromTemplate.data.preview.uses_webagent ? (
                    <p className="text-warning flex items-center gap-1"><Globe2 size={12} /> Uses WebAgent (delegated Playwright)</p>
                  ) : null}
                  {(previewFromTemplate.data.preview.external_dependencies || []).length > 0 ? (
                    <p><strong>External Dependencies:</strong> {previewFromTemplate.data.preview.external_dependencies.join(", ")}</p>
                  ) : null}
                  {(previewFromTemplate.data.preview.warnings || []).map((w) => (
                    <p key={w} className="text-warning flex items-center gap-1"><ShieldAlert size={12} /> {w}</p>
                  ))}
                </div>
              ) : null}

              {createAgent.error ? <p className="text-xs text-danger">{String(createAgent.error)}</p> : null}
              {createFromTemplate.error ? <p className="text-xs text-danger">{String(createFromTemplate.error)}</p> : null}
              {prepare.error ? <p className="text-xs text-danger">{String(prepare.error)}</p> : null}
              {deploy.error ? <p className="text-xs text-danger">{String(deploy.error)}</p> : null}
            </div>
          ) : null}

          <div className="flex flex-wrap justify-between gap-2 border-t border-border pt-3">
            <Button variant="outline" disabled={step === 1} onClick={() => setStep((Math.max(1, step - 1) as WizardStep))}>Back</Button>
            <div className="flex gap-2">
              {step < 5 ? (
                <Button disabled={step === 1 && !canNextBasics} onClick={() => setStep((Math.min(5, step + 1) as WizardStep))}>Next</Button>
              ) : (
                <>
                  <label className="text-xs text-muted-foreground">
                    Create Action
                    <select
                      className="ml-2 rounded border border-border bg-input px-2 py-1 text-xs"
                      value={createMode}
                      onChange={(e) => setCreateMode(e.target.value as "create" | "create_prepare" | "create_deploy")}
                    >
                      <option value="create">create only</option>
                      <option value="create_prepare">create + prepare</option>
                      <option value="create_deploy">create + deploy</option>
                    </select>
                  </label>
                  <Button onClick={createAndDeploy} disabled={createAgent.isPending || createFromTemplate.isPending || prepare.isPending || deploy.isPending || !canNextBasics}>
                    {(createAgent.isPending || createFromTemplate.isPending || prepare.isPending || deploy.isPending) ? <Loader2 size={13} className="animate-spin" /> : <CheckCircle2 size={13} />}
                  Create + Deploy
                  </Button>
                </>
              )}
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

function AgentActions({ agentId }: { agentId: string }) {
  const prepare = useSkilledPrepareAgent();
  const deploy = useSkilledDeployAgent();
  const run = useSkilledRunAgent();
  const stop = useSkilledStopAgent();
  const validate = useSkilledRunValidation();
  const smoke = useSkilledRunSmokeTest();

  return (
    <div className="flex flex-wrap gap-2">
      <Button size="sm" variant="outline" onClick={() => prepare.mutate({ agentId })} disabled={prepare.isPending}><Bot size={12} />Prepare</Button>
      <Button size="sm" variant="outline" onClick={() => deploy.mutate({ agentId })} disabled={deploy.isPending}><CheckCircle2 size={12} />Deploy</Button>
      <Button size="sm" variant="success" onClick={() => run.mutate({ agentId, payload: {} })} disabled={run.isPending}><Play size={12} />Run</Button>
      <Button size="sm" variant="danger" onClick={() => stop.mutate({ agentId })} disabled={stop.isPending}><Square size={12} />Stop</Button>
      <Button size="sm" variant="outline" onClick={() => validate.mutate({ agentId })} disabled={validate.isPending}>Validate</Button>
      <Button size="sm" variant="outline" onClick={() => smoke.mutate({ agentId })} disabled={smoke.isPending}>Smoke Test</Button>
    </div>
  );
}

export function SkilledAgentDetailPage() {
  const { id } = useParams<{ id: string }>();
  const { data: agent, isLoading, refetch, isFetching } = useSkilledAgent(id ?? null);
  const { data: status } = useSkilledAgentStatus(id ?? null);
  const { data: logs } = useSkilledAgentLogs(id ?? null, 200);
  const { data: workspace } = useSkilledAgentWorkspace(id ?? null);
  const { data: manifest } = useSkilledAgentManifest(id ?? null);
  const { data: snapshots } = useSkilledAgentSnapshots(id ?? null);
  const { data: latestSnapshot } = useSkilledAgentLatestSnapshot(id ?? null);
  const patchAgent = useUpdateSkilledAgent();

  const [description, setDescription] = useState("");
  const [networkAccess, setNetworkAccess] = useState(false);
  const [yolo, setYolo] = useState(false);

  useEffect(() => {
    if (!agent) return;
    setDescription(agent.description || "");
    setNetworkAccess(Boolean(agent.network_access));
    setYolo(Boolean(agent.yolo_mode));
  }, [agent]);

  if (!id) return null;

  return (
    <div className="space-y-4">
      <PageHeader
        compact
        title={agent ? `Agent: ${agent.name}` : "Agent"}
        description="Status, logs, runtime config, skill attachments, and control actions."
        actions={
          <>
            <Button variant="outline" onClick={() => refetch()} disabled={isFetching}>{isFetching ? <Loader2 size={13} className="animate-spin" /> : <RefreshCw size={13} />} Refresh</Button>
            <AgentActions agentId={id} />
          </>
        }
      >
        <SkilledAgentsTabs />
      </PageHeader>

      {isLoading ? <p className="text-sm text-muted-foreground">Loading agent...</p> : null}
      {!isLoading && !agent ? <p className="text-sm text-danger">Agent not found.</p> : null}

      {agent ? (
        <>
          <div className="grid gap-4 lg:grid-cols-3">
            <Card className="lg:col-span-2">
              <CardHeader className="pb-2"><CardTitle>Summary</CardTitle></CardHeader>
              <CardContent className="space-y-2 text-sm">
                <p><strong>Type:</strong> {agent.agent_type}</p>
                <p><strong>Template:</strong> {agent.template_id || "-"}</p>
                <p><strong>Role Identity:</strong> {agent.role_identity || "-"}</p>
                <p><strong>Specialization:</strong> {agent.specialization_mode}</p>
                <p><strong>Domain Focus:</strong> {agent.domain_focus || "-"}</p>
                <p><strong>Starter Pack:</strong> {String((agent.flags?.starter_template as Record<string, unknown> | undefined)?.pack_version ?? "-")}</p>
                <p><strong>Starter Source:</strong> {String((agent.flags?.starter_template as Record<string, unknown> | undefined)?.source_pack ?? "-")}</p>
                <p><strong>Status:</strong> <span className={`rounded border px-2 py-0.5 text-xs ${tone(status?.status || agent.status)}`}>{status?.status || agent.status}</span></p>
                <p><strong>Runtime:</strong> {agent.runtime}</p>
                <p><strong>Model:</strong> {agent.model_provider || "-"} / {agent.model_name || "-"}</p>
                <p><strong>Workspace:</strong> <span className="font-mono text-xs">{agent.workspace_path}</span></p>
                <p><strong>Last Run:</strong> {rel(status?.last_run_at || agent.last_run_at)}</p>
                <p><strong>Last Error:</strong> <span className="text-danger">{status?.last_error || agent.last_error || "none"}</span></p>
                <CompatibilityBadges badges={(agent.flags?.compatibility_badges as Record<string, boolean> | undefined) || {}} />
                {Boolean(agent.flags?.uses_webagent) ? (
                  <p className="text-warning flex items-center gap-1"><Globe2 size={12} /> Uses WebAgent (delegated Playwright analyzer)</p>
                ) : null}
              </CardContent>
            </Card>

            <Card>
              <CardHeader className="pb-2"><CardTitle>Execution</CardTitle></CardHeader>
              <CardContent className="space-y-2 text-sm">
                <p><strong>Deploy Mode:</strong> {String(agent.flags?.deploy_mode ?? "-")}</p>
                <p><strong>Sandbox:</strong> {agent.sandbox_mode}</p>
                <p><strong>Network:</strong> {agent.network_access ? "enabled" : "disabled"}</p>
                <p><strong>YOLO:</strong> {agent.yolo_mode ? "enabled" : "disabled"}</p>
                <p><strong>Active PID:</strong> {status?.pid ?? "-"}</p>
                <p><strong>Active Run:</strong> {status?.active_run_id ?? "-"}</p>
                <p><strong>Validation Hook:</strong> {String(agent.flags?.validation_hook ?? "not configured")}</p>
                <p><strong>Smoke Test:</strong> {String(agent.flags?.smoke_test_command ?? "not configured")}</p>
              </CardContent>
            </Card>
          </div>

          <div className="grid gap-4 lg:grid-cols-3">
            <Card>
              <CardHeader className="pb-2"><CardTitle>Skills</CardTitle></CardHeader>
              <CardContent>
                {agent.selected_skills.length === 0 ? (
                  <p className="text-sm text-muted-foreground">No skills attached.</p>
                ) : (
                  <div className="space-y-1">
                    {agent.selected_skills.map((s) => (
                      <div key={s} className="rounded border border-border bg-background/20 px-2 py-1 text-xs text-foreground">{s}</div>
                    ))}
                  </div>
                )}
              </CardContent>
            </Card>

            <Card>
              <CardHeader className="pb-2"><CardTitle>Workspace</CardTitle></CardHeader>
              <CardContent className="space-y-2">
                <p className="text-xs text-muted-foreground">Path</p>
                <p className="font-mono text-xs break-all">{workspace?.workspace_path || "-"}</p>
                <p className="text-xs text-muted-foreground">Files</p>
                <div className="max-h-28 overflow-auto rounded border border-border bg-background/20 p-2">
                  {(workspace?.files || []).map((f) => (
                    <p key={f} className="font-mono text-[11px] text-foreground">{f}</p>
                  ))}
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardHeader className="pb-2"><CardTitle>Config Editor</CardTitle></CardHeader>
              <CardContent className="space-y-2">
                <label className="text-xs text-muted-foreground">
                  Description
                  <Textarea rows={2} value={description} onChange={(e) => setDescription(e.target.value)} />
                </label>
                <label className="inline-flex items-center gap-2 text-xs text-muted-foreground">
                  <input type="checkbox" checked={networkAccess} onChange={(e) => setNetworkAccess(e.target.checked)} /> Network access
                </label>
                <label className="inline-flex items-center gap-2 text-xs text-muted-foreground">
                  <input type="checkbox" checked={yolo} onChange={(e) => setYolo(e.target.checked)} /> YOLO mode
                </label>
                <Button
                  size="sm"
                  onClick={() => patchAgent.mutate({ agentId: id, payload: { description, network_access: networkAccess, yolo_mode: yolo } })}
                  disabled={patchAgent.isPending}
                >
                  {patchAgent.isPending ? <Loader2 size={12} className="animate-spin" /> : null}
                  Save Config
                </Button>
              </CardContent>
            </Card>
          </div>

          <div className="grid gap-4 lg:grid-cols-2">
            <Card>
              <CardHeader className="pb-2"><CardTitle>Latest Snapshot</CardTitle></CardHeader>
              <CardContent>
                <div className="max-h-[260px] overflow-auto rounded-lg border border-border bg-black/20 p-2 font-mono text-[11px] text-foreground">
                  <pre>{JSON.stringify(latestSnapshot?.snapshot?.snapshot || {}, null, 2)}</pre>
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardHeader className="pb-2"><CardTitle>Snapshot History</CardTitle></CardHeader>
              <CardContent>
                <div className="max-h-[260px] overflow-auto rounded border border-border bg-background/20 p-2 text-xs">
                  {(snapshots?.snapshots || []).map((item) => (
                    <div key={item.id} className="mb-2 border-b border-border/60 pb-2">
                      <p className="font-mono text-[11px]">{item.id}</p>
                      <p className="text-muted-foreground">{item.reason} · {rel(item.created_at)}</p>
                    </div>
                  ))}
                  {(snapshots?.snapshots || []).length === 0 ? <p className="text-muted-foreground">No snapshots yet.</p> : null}
                </div>
              </CardContent>
            </Card>
          </div>

          <div className="grid gap-4 lg:grid-cols-2">
            <Card>
              <CardHeader className="pb-2"><CardTitle>Latest Logs</CardTitle></CardHeader>
              <CardContent>
                <div className="max-h-[340px] overflow-auto rounded-lg border border-border bg-black/30 p-2 font-mono text-[11px]">
                  {(logs?.logs || []).map((line) => (
                    <div key={line.id} className="mb-1 border-b border-white/5 pb-1">
                      <span className="text-muted-foreground">[{line.created_at}]</span>{" "}
                      <span className="text-primary">{line.level}</span>{" "}
                      <span className="text-foreground whitespace-pre-wrap break-words">{line.message}</span>
                    </div>
                  ))}
                  {(logs?.logs || []).length === 0 ? <p className="text-muted-foreground">No logs yet.</p> : null}
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardHeader className="pb-2"><CardTitle>Manifest / Runtime View</CardTitle></CardHeader>
              <CardContent>
                <div className="max-h-[340px] overflow-auto rounded-lg border border-border bg-black/20 p-2 font-mono text-[11px] text-foreground">
                  <pre>{JSON.stringify(manifest?.manifest || {}, null, 2)}</pre>
                </div>
                <div className="mt-2 rounded border border-border bg-background/20 p-2 text-xs">
                  <p><strong>Last Validation:</strong> {JSON.stringify(agent.flags?.last_validation_result || null)}</p>
                  <p><strong>Last Smoke:</strong> {JSON.stringify(agent.flags?.last_smoke_test_result || null)}</p>
                </div>
              </CardContent>
            </Card>
          </div>
        </>
      ) : null}
    </div>
  );
}

export function SkilledSkillLibraryPage() {
  const { data: skills = [], refetch, isFetching } = useSkilledSkills();
  const { data: starterTemplates = [] } = useSkilledStarterTemplates();
  const createSkill = useCreateSkilledSkill();
  const [selected, setSelected] = useState<SkilledSkillSummary | null>(null);
  const [selectedStarter, setSelectedStarter] = useState<SkilledStarterTemplate | null>(null);
  const [newSkill, setNewSkill] = useState({
    id: "",
    name: "",
    category: "custom",
    version: "1.0.0",
    tags: "",
    description: "",
  });
  const [createError, setCreateError] = useState<string | null>(null);

  useEffect(() => {
    if (!selected && skills.length > 0) setSelected(skills[0]);
  }, [skills, selected]);
  useEffect(() => {
    if (!selectedStarter && starterTemplates.length > 0) setSelectedStarter(starterTemplates[0]);
  }, [starterTemplates, selectedStarter]);

  function normalizeSkillId(raw: string): string {
    return raw
      .toLowerCase()
      .trim()
      .replace(/[^a-z0-9-]+/g, "-")
      .replace(/-+/g, "-")
      .replace(/^-|-$/g, "");
  }

  async function submitNewSkill(event: FormEvent) {
    event.preventDefault();
    setCreateError(null);
    const id = normalizeSkillId(newSkill.id || newSkill.name);
    if (!id) {
      setCreateError("Skill id is required.");
      return;
    }
    try {
      const created = await createSkill.mutateAsync({
        id,
        name: newSkill.name.trim() || undefined,
        category: newSkill.category.trim() || "custom",
        version: newSkill.version.trim() || "1.0.0",
        tags: newSkill.tags.split(",").map((s) => s.trim()).filter(Boolean),
        description: newSkill.description.trim(),
      });
      setNewSkill({ id: "", name: "", category: "custom", version: "1.0.0", tags: "", description: "" });
      setSelected(created);
      refetch();
    } catch (error) {
      const msg = error instanceof Error ? error.message : "Failed to create skill.";
      setCreateError(msg);
    }
  }

  return (
    <div className="space-y-4">
      <PageHeader
        compact
        title="Skill Library"
        description="Browse attachable capability packs with metadata and descriptions."
        actions={<Button variant="outline" onClick={() => refetch()} disabled={isFetching}>{isFetching ? <Loader2 size={13} className="animate-spin" /> : <RefreshCw size={13} />} Refresh</Button>}
      >
        <SkilledAgentsTabs />
      </PageHeader>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader className="pb-2"><CardTitle>Starter Templates</CardTitle></CardHeader>
          <CardContent>
            <div className="max-h-[500px] overflow-auto space-y-2 pr-1">
              {starterTemplates.map((tpl) => (
                <button
                  key={tpl.slug}
                  type="button"
                  onClick={() => setSelectedStarter(tpl)}
                  className={`w-full rounded-lg border p-3 text-left ${selectedStarter?.slug === tpl.slug ? "border-primary/50 bg-primary/10" : "border-border bg-background/20 hover:bg-background/35"}`}
                >
                  <p className="text-sm font-semibold">{tpl.name}</p>
                  <p className="text-[11px] text-muted-foreground">{tpl.slug} · {tpl.pack_version} · {tpl.template_version}</p>
                  <p className="mt-1 text-xs text-muted-foreground">{tpl.description}</p>
                  <div className="mt-1"><CompatibilityBadges badges={tpl.compatibility_badges} /></div>
                  {tpl.uses_webagent ? <p className="mt-1 text-[11px] text-warning">Uses WebAgent</p> : null}
                </button>
              ))}
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2"><CardTitle>Template Detail</CardTitle></CardHeader>
          <CardContent className="space-y-2 text-sm">
            {selectedStarter ? (
              <>
                <p className="font-semibold">{selectedStarter.name}</p>
                <p className="text-xs text-muted-foreground">{selectedStarter.slug}</p>
                <p className="text-xs text-muted-foreground">{selectedStarter.description}</p>
                <p className="text-xs">Pack: {selectedStarter.pack_version} · Source: {selectedStarter.source_pack}</p>
                <p className="text-xs">Recommended deploy mode: {selectedStarter.recommended_deploy_mode}</p>
                <CompatibilityBadges badges={selectedStarter.compatibility_badges} />
                <Link to="/modules/skilled-agents/new"><Button size="sm"><Bot size={12} />Create From Template</Button></Link>
              </>
            ) : (
              <p className="text-xs text-muted-foreground">No starter templates imported yet.</p>
            )}
          </CardContent>
        </Card>
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader className="pb-2"><CardTitle>Skills</CardTitle></CardHeader>
          <CardContent>
            <SkillPicker skills={skills} selected={selected ? [selected.id] : []} onToggle={(skill) => setSelected(skill)} showCategory />
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2"><CardTitle>Selected Skill</CardTitle></CardHeader>
          <CardContent>
            {selected ? (
              <div className="space-y-2 text-sm">
                <p className="font-semibold text-foreground">{selected.name}</p>
                <p className="text-xs text-muted-foreground">{selected.slug} · {selected.category} · v{selected.version}</p>
                <p className="text-xs text-muted-foreground">{selected.description}</p>
                <div className="flex flex-wrap gap-1">
                  {(selected.tags || []).map((tag) => (
                    <span key={tag} className="rounded border border-border px-1.5 py-0.5 text-[11px] text-muted-foreground">{tag}</span>
                  ))}
                </div>
                <Link to="/modules/skilled-agents/new"><Button size="sm"><Bot size={12} />Use In Wizard</Button></Link>
              </div>
            ) : (
              <p className="text-sm text-muted-foreground">Pick a skill to preview.</p>
            )}
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader className="pb-2"><CardTitle>Add Skill</CardTitle></CardHeader>
        <CardContent>
          <form className="grid gap-3 md:grid-cols-2" onSubmit={submitNewSkill}>
            <label className="text-xs text-muted-foreground">
              Skill ID
              <Input
                value={newSkill.id}
                onChange={(e) => setNewSkill((prev) => ({ ...prev, id: e.target.value }))}
                placeholder="my-custom-skill"
              />
            </label>
            <label className="text-xs text-muted-foreground">
              Name
              <Input
                value={newSkill.name}
                onChange={(e) => setNewSkill((prev) => ({ ...prev, name: e.target.value }))}
                placeholder="My Custom Skill"
              />
            </label>
            <label className="text-xs text-muted-foreground">
              Category
              <Input
                value={newSkill.category}
                onChange={(e) => setNewSkill((prev) => ({ ...prev, category: e.target.value }))}
                placeholder="custom"
              />
            </label>
            <label className="text-xs text-muted-foreground">
              Version
              <Input
                value={newSkill.version}
                onChange={(e) => setNewSkill((prev) => ({ ...prev, version: e.target.value }))}
                placeholder="1.0.0"
              />
            </label>
            <label className="text-xs text-muted-foreground md:col-span-2">
              Tags (comma separated)
              <Input
                value={newSkill.tags}
                onChange={(e) => setNewSkill((prev) => ({ ...prev, tags: e.target.value }))}
                placeholder="automation, content, qa"
              />
            </label>
            <label className="text-xs text-muted-foreground md:col-span-2">
              Description
              <Textarea
                rows={3}
                value={newSkill.description}
                onChange={(e) => setNewSkill((prev) => ({ ...prev, description: e.target.value }))}
                placeholder="What this skill does and when to use it."
              />
            </label>
            <div className="md:col-span-2 flex items-center gap-2">
              <Button type="submit" disabled={createSkill.isPending}>
                {createSkill.isPending ? <Loader2 size={13} className="animate-spin" /> : <Plus size={13} />}
                Create Skill
              </Button>
              {createError ? <span className="text-xs text-danger">{createError}</span> : null}
              {createSkill.isSuccess ? <span className="text-xs text-success">Skill created.</span> : null}
            </div>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
