import { useEffect, useMemo, useState } from "react";

import {
  useDiscordApprove,
  useDiscordApprovals,
  useDiscordDispatch,
  useDiscordDispatchRequests,
  useDiscordDispatchTargets,
  useDiscordMemoryAppend,
  useDiscordPolicyEvaluate,
  useDiscordReject,
  useDiscordReindexMemory,
  useDiscordSessionBootstrap,
  useDiscordSettings,
  useDiscordStatus,
  useDiscordTestConnectivity,
  useDiscordWorkers,
  useSaveDiscordSettings,
} from "../../shared/api/hooks";
import type {
  DiscordApprovalRequest,
  DiscordDispatchRequest,
  DiscordDispatchTarget,
  DiscordSettings,
  DispatchWorkerStatus,
} from "../../shared/api/types";
import { Button } from "../../shared/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "../../shared/components/ui/card";
import { Input, Textarea } from "../../shared/components/ui/input";
import { PageHeader } from "../../shared/components/ui/page-header";
import { StatusDot } from "../../shared/components/ui/status-dot";
import { Tabs } from "../../shared/components/ui/tabs";
import { DashburgAssistantPanel } from "../../shared/components/chat/DashburgAssistantPanel";

function fmtTs(value: string | null | undefined): string {
  if (!value) return "-";
  const dt = new Date(value);
  if (Number.isNaN(dt.getTime())) return value;
  return dt.toLocaleString();
}

function idsToText(ids: string[] | undefined): string {
  return (ids ?? []).join("\n");
}

function parseIds(raw: string): string[] {
  return raw
    .split(/[\n,\s]+/)
    .map((v) => v.trim())
    .filter(Boolean);
}

function pickReplayToken(approval: DiscordApprovalRequest): string {
  return String((approval as { replay_token?: string }).replay_token ?? "");
}

export function DiscordControlPage() {
  const [tab, setTab] = useState("overview");

  const settingsQuery = useDiscordSettings();
  const statusQuery = useDiscordStatus();
  const targetsQuery = useDiscordDispatchTargets();
  const requestsQuery = useDiscordDispatchRequests({ limit: 80 });
  const approvalsQuery = useDiscordApprovals({ status: "pending", limit: 80 });
  const workersQuery = useDiscordWorkers(50);

  const saveSettings = useSaveDiscordSettings();
  const testConnectivity = useDiscordTestConnectivity();
  const reindexMemory = useDiscordReindexMemory();
  const bootstrapSession = useDiscordSessionBootstrap();
  const memoryAppend = useDiscordMemoryAppend();
  const dispatchMutation = useDiscordDispatch();
  const approveMutation = useDiscordApprove();
  const rejectMutation = useDiscordReject();
  const policyEval = useDiscordPolicyEvaluate();

  const [form, setForm] = useState<DiscordSettings | null>(null);
  const [allowedUsersText, setAllowedUsersText] = useState("");
  const [allowedGuildsText, setAllowedGuildsText] = useState("");
  const [allowedChannelsText, setAllowedChannelsText] = useState("");
  const [allowedRolesText, setAllowedRolesText] = useState("");
  const [allowedApproversText, setAllowedApproversText] = useState("");

  const [bridgeApiKeyInput, setBridgeApiKeyInput] = useState("");
  const [botTokenInput, setBotTokenInput] = useState("");

  const [bootstrapUserId, setBootstrapUserId] = useState("");
  const [bootstrapGuildId, setBootstrapGuildId] = useState("");
  const [bootstrapChannelId, setBootstrapChannelId] = useState("");
  const [memoryCandidate, setMemoryCandidate] = useState("");

  const [dispatchActionType, setDispatchActionType] = useState("status.check");
  const [dispatchTarget, setDispatchTarget] = useState("dashburg-orchestration");
  const [dispatchPrompt, setDispatchPrompt] = useState("");
  const [dispatchArgsText, setDispatchArgsText] = useState('{\n  "query": "cluster status"\n}');
  const [requesterUserId, setRequesterUserId] = useState("");
  const [requesterGuildId, setRequesterGuildId] = useState("");
  const [requesterChannelId, setRequesterChannelId] = useState("");
  const [approverUserId, setApproverUserId] = useState("");

  useEffect(() => {
    if (!settingsQuery.data) return;
    setForm(settingsQuery.data);
    setAllowedUsersText(idsToText(settingsQuery.data.allowed_user_ids));
    setAllowedGuildsText(idsToText(settingsQuery.data.allowed_guild_ids));
    setAllowedChannelsText(idsToText(settingsQuery.data.allowed_channel_ids));
    setAllowedRolesText(idsToText(settingsQuery.data.allowed_role_ids));
    setAllowedApproversText(idsToText(settingsQuery.data.allowed_approver_ids));
  }, [settingsQuery.data]);

  const overview = statusQuery.data?.overview;
  const bridge = statusQuery.data?.bridge;
  const redis = statusQuery.data?.redis;
  const memory = statusQuery.data?.memory;
  const diagnostics = statusQuery.data?.diagnostics as
    | { reasons?: string[]; next_actions?: string[]; env_presence?: Record<string, boolean> }
    | undefined;

  const targets = useMemo<DiscordDispatchTarget[]>(() => {
    return targetsQuery.data?.targets ?? statusQuery.data?.dispatch?.targets ?? [];
  }, [targetsQuery.data?.targets, statusQuery.data?.dispatch?.targets]);

  const requests = useMemo<DiscordDispatchRequest[]>(() => requestsQuery.data?.items ?? [], [requestsQuery.data?.items]);
  const approvals = useMemo<DiscordApprovalRequest[]>(() => approvalsQuery.data?.items ?? [], [approvalsQuery.data?.items]);
  const workers = useMemo<DispatchWorkerStatus[]>(() => workersQuery.data?.items ?? [], [workersQuery.data?.items]);

  return (
    <div className="space-y-4">
      <PageHeader
        compact
        title="Discord Bot & Bridge"
        description="Secure Discord communications, agent dispatch routing, memory context, and session controls."
      >
        <div className="flex flex-wrap gap-2">
          <Button
            size="sm"
            variant="outline"
            onClick={() => {
              void statusQuery.refetch();
              void targetsQuery.refetch();
              void requestsQuery.refetch();
              void approvalsQuery.refetch();
              void workersQuery.refetch();
            }}
          >
            Refresh
          </Button>
          <Button
            size="sm"
            onClick={() =>
              void testConnectivity.mutateAsync({
                include_bridge: true,
                include_redis: true,
                include_memory: true,
              })
            }
          >
            Connection Test
          </Button>
        </div>
      </PageHeader>

      <Tabs
        active={tab}
        onChange={setTab}
        tabs={[
          { id: "overview", label: "Overview" },
          { id: "chat", label: "Chat Test Panel" },
          { id: "dispatch", label: "Dispatch Requests" },
          { id: "approvals", label: "Pending Approvals" },
          { id: "targets", label: "Dispatch Targets" },
          { id: "policy", label: "Policy / Safety" },
          { id: "memory", label: "Session / Memory" },
          { id: "settings", label: "Settings" },
        ]}
      />

      {tab === "overview" ? (
        <div className="grid gap-4 lg:grid-cols-2 xl:grid-cols-4">
          <OverviewCard title="Integration" ok={Boolean(overview?.integration_enabled)} detail={overview?.integration_enabled ? "Enabled" : "Disabled"} />
          <OverviewCard title="Bot" ok={Boolean(overview?.bot_online)} detail={overview?.bot_online ? "Online" : "Offline"} />
          <OverviewCard title="Bridge" ok={Boolean(overview?.bridge_reachable)} detail={overview?.bridge_reachable ? "Reachable" : "Unreachable"} />
          <OverviewCard title="Redis" ok={Boolean(overview?.redis_reachable)} detail={overview?.redis_reachable ? "Reachable" : "Unreachable"} />

          <Card className="xl:col-span-2">
            <CardHeader className="pb-2"><CardTitle>Runtime</CardTitle></CardHeader>
            <CardContent className="space-y-1 text-sm">
              <p><span className="text-muted-foreground">Dispatch readiness:</span> {String(overview?.dispatch_readiness ?? "-")}</p>
              <p><span className="text-muted-foreground">Last heartbeat:</span> {fmtTs(String(overview?.last_heartbeat ?? ""))}</p>
              <p><span className="text-muted-foreground">Last seen:</span> {fmtTs(String(overview?.last_seen ?? ""))}</p>
              <p><span className="text-muted-foreground">Last error:</span> {String(overview?.last_error ?? "") || "-"}</p>
              <p><span className="text-muted-foreground">Queue:</span> pending approval {Number((overview?.request_counts ?? {}).pending_approval ?? 0)} · queued {Number((overview?.request_counts ?? {}).queued ?? 0)} · running {Number((overview?.request_counts ?? {}).running ?? 0)}</p>
            </CardContent>
          </Card>

          <Card className="xl:col-span-2">
            <CardHeader className="pb-2"><CardTitle>Bridge / Redis Probe</CardTitle></CardHeader>
            <CardContent className="space-y-1 text-xs">
              <p><span className="text-muted-foreground">Bridge endpoint:</span> <span className="font-mono">{String(bridge?.endpoint ?? "-")}</span></p>
              <p><span className="text-muted-foreground">Bridge status:</span> {String(bridge?.status_code ?? "-")}</p>
              <p><span className="text-muted-foreground">Bridge error:</span> {String(bridge?.error ?? "") || "-"}</p>
              <p><span className="text-muted-foreground">Redis URL:</span> <span className="font-mono">{String(redis?.redis_url ?? "-")}</span></p>
              <p><span className="text-muted-foreground">Memory source:</span> <span className="font-mono">{String(memory?.source_path ?? "-")}</span></p>
              <p><span className="text-muted-foreground">Indexed sections:</span> {String(memory?.indexed_section_count ?? "-")}</p>
            </CardContent>
          </Card>

          <Card className="xl:col-span-4">
            <CardHeader className="pb-2"><CardTitle>Why It Is Offline</CardTitle></CardHeader>
            <CardContent className="space-y-2 text-sm">
              {(diagnostics?.reasons ?? []).length ? (
                <ul className="list-disc space-y-1 pl-5">
                  {(diagnostics?.reasons ?? []).map((reason) => (
                    <li key={reason}>{reason}</li>
                  ))}
                </ul>
              ) : (
                <p className="text-muted-foreground">No blocking issues detected from current probes.</p>
              )}
              {(diagnostics?.next_actions ?? []).length ? (
                <div className="rounded-md border border-border bg-background/50 p-2">
                  <p className="mb-1 text-xs uppercase tracking-wide text-muted-foreground">Next Actions</p>
                  <ul className="list-disc space-y-1 pl-5">
                    {(diagnostics?.next_actions ?? []).map((step) => (
                      <li key={step}>{step}</li>
                    ))}
                  </ul>
                </div>
              ) : null}
              <p className="text-xs text-muted-foreground">
                Env hints: DISCORD_TOKEN {diagnostics?.env_presence?.discord_token ? "present" : "missing"} · BRIDGE_URL {diagnostics?.env_presence?.bridge_base_url ? "present" : "missing"} · BRIDGE_API_KEY {diagnostics?.env_presence?.bridge_api_key ? "present" : "missing"}
              </p>
            </CardContent>
          </Card>
        </div>
      ) : null}

      {tab === "chat" ? (
        <DashburgAssistantPanel
          sessionId="discord-operator-session"
          title="Discord Session Test Chat"
          subtitle="Operator test panel using shared Redis chat sessions. Discord and web messages can share this timeline via session attach/sync."
          defaultModel={form?.default_model || "qwen3:14b"}
          allowSessionSwitch
          showSessionControls
          showMetadata
          heightClass="h-[480px]"
        />
      ) : null}

      {tab === "dispatch" ? (
        <div className="grid gap-4 xl:grid-cols-[1.2fr,1fr]">
          <Card>
            <CardHeader className="pb-2"><CardTitle>Submit Structured Request</CardTitle></CardHeader>
            <CardContent className="space-y-3 text-sm">
              <div className="grid gap-2 md:grid-cols-3">
                <label className="text-xs text-muted-foreground">Action type
                  <Input value={dispatchActionType} onChange={(e) => setDispatchActionType(e.target.value)} placeholder="status.check" />
                </label>
                <label className="text-xs text-muted-foreground">Target
                  <Input value={dispatchTarget} onChange={(e) => setDispatchTarget(e.target.value)} placeholder="service/target id" />
                </label>
                <label className="text-xs text-muted-foreground">Requester user ID
                  <Input value={requesterUserId} onChange={(e) => setRequesterUserId(e.target.value)} placeholder="discord user id" />
                </label>
              </div>
              <div className="grid gap-2 md:grid-cols-2">
                <label className="text-xs text-muted-foreground">Guild ID
                  <Input value={requesterGuildId} onChange={(e) => setRequesterGuildId(e.target.value)} placeholder="guild id" />
                </label>
                <label className="text-xs text-muted-foreground">Channel ID
                  <Input value={requesterChannelId} onChange={(e) => setRequesterChannelId(e.target.value)} placeholder="channel id" />
                </label>
              </div>
              <label className="text-xs text-muted-foreground">Prompt summary
                <Textarea rows={3} value={dispatchPrompt} onChange={(e) => setDispatchPrompt(e.target.value)} placeholder="short request summary" />
              </label>
              <label className="text-xs text-muted-foreground">Args JSON
                <Textarea rows={6} value={dispatchArgsText} onChange={(e) => setDispatchArgsText(e.target.value)} />
              </label>
              <div className="flex flex-wrap gap-2">
                <Button
                  size="sm"
                  onClick={() => {
                    let parsedArgs: Record<string, unknown> = {};
                    try {
                      parsedArgs = JSON.parse(dispatchArgsText) as Record<string, unknown>;
                    } catch {
                      parsedArgs = {};
                    }
                    void dispatchMutation.mutateAsync({
                      action_type: dispatchActionType,
                      target: dispatchTarget,
                      prompt: dispatchPrompt,
                      args: parsedArgs,
                      requester: {
                        user_id: requesterUserId,
                        guild_id: requesterGuildId,
                        channel_id: requesterChannelId,
                        role_ids: [],
                        is_dm: !requesterGuildId.trim(),
                      },
                    });
                  }}
                  disabled={dispatchMutation.isPending || !requesterUserId.trim()}
                >
                  Dispatch Request
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => {
                    let parsedArgs: Record<string, unknown> = {};
                    try {
                      parsedArgs = JSON.parse(dispatchArgsText) as Record<string, unknown>;
                    } catch {
                      parsedArgs = {};
                    }
                    void policyEval.mutateAsync({
                      action_type: dispatchActionType,
                      target: dispatchTarget,
                      args: parsedArgs,
                      requester: {
                        user_id: requesterUserId,
                        guild_id: requesterGuildId,
                        channel_id: requesterChannelId,
                        role_ids: [],
                        is_dm: !requesterGuildId.trim(),
                      },
                    });
                  }}
                >
                  Evaluate Policy
                </Button>
              </div>
              {dispatchMutation.data ? <pre className="overflow-auto rounded border border-border p-2 text-xs">{JSON.stringify(dispatchMutation.data, null, 2)}</pre> : null}
              {policyEval.data ? <pre className="overflow-auto rounded border border-border p-2 text-xs">{JSON.stringify(policyEval.data, null, 2)}</pre> : null}
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="pb-2"><CardTitle>Recent Requests</CardTitle></CardHeader>
            <CardContent className="space-y-2 text-xs">
              {(requests ?? []).slice(0, 18).map((row) => (
                <div key={row.id} className="rounded border border-border p-2">
                  <p className="font-medium">{row.action_type} → {row.target || "-"}</p>
                  <p className="text-muted-foreground">{row.status} · risk {row.risk_level ?? "-"} · {fmtTs(row.created_at)}</p>
                  <p className="font-mono">audit: {row.audit_id}</p>
                  <p>requester: {String((row.requester ?? {}).user_id ?? "-")}</p>
                </div>
              ))}
            </CardContent>
          </Card>
        </div>
      ) : null}

      {tab === "approvals" ? (
        <Card>
          <CardHeader className="pb-2"><CardTitle>Pending Approvals</CardTitle></CardHeader>
          <CardContent className="space-y-3 text-sm">
            <label className="text-xs text-muted-foreground">Approver Discord user ID
              <Input value={approverUserId} onChange={(e) => setApproverUserId(e.target.value)} placeholder="required for approve/reject" />
            </label>
            {(approvals ?? []).length === 0 ? <p className="text-xs text-muted-foreground">No pending approvals.</p> : null}
            {(approvals ?? []).map((row) => {
              const req = row.request;
              return (
                <div key={row.id} className="rounded border border-border p-3 space-y-2">
                  <p className="font-medium">{req?.action_type} → {req?.target || "-"}</p>
                  <p className="text-xs text-muted-foreground">audit {row.audit_id} · expires {fmtTs(row.expires_at)} · risk {req?.risk_level ?? "-"}</p>
                  <p className="text-xs">summary: {req?.prompt_summary || "-"}</p>
                  <div className="flex flex-wrap gap-2">
                    <Button
                      size="sm"
                      onClick={() => void approveMutation.mutateAsync({
                        dispatch_request_id: row.dispatch_request_id,
                        approver_user_id: approverUserId,
                        reason: "approved from Dashburg UI",
                        replay_token: pickReplayToken(row),
                      })}
                      disabled={!approverUserId.trim() || approveMutation.isPending}
                    >
                      Approve
                    </Button>
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => void rejectMutation.mutateAsync({
                        dispatch_request_id: row.dispatch_request_id,
                        approver_user_id: approverUserId,
                        reason: "rejected from Dashburg UI",
                        replay_token: pickReplayToken(row),
                      })}
                      disabled={!approverUserId.trim() || rejectMutation.isPending}
                    >
                      Reject
                    </Button>
                  </div>
                </div>
              );
            })}
          </CardContent>
        </Card>
      ) : null}

      {tab === "targets" ? (
        <div className="grid gap-4 xl:grid-cols-[1.6fr,1fr]">
          <Card>
            <CardHeader className="pb-2"><CardTitle>Dispatch Targets</CardTitle></CardHeader>
            <CardContent>
              <div className="overflow-auto rounded border border-border">
                <table className="w-full text-left text-xs">
                  <thead className="bg-muted/40">
                    <tr>
                      <th className="px-2 py-2">Service</th>
                      <th className="px-2 py-2">Capabilities</th>
                      <th className="px-2 py-2">Health</th>
                      <th className="px-2 py-2">Safe</th>
                      <th className="px-2 py-2">Isolated</th>
                      <th className="px-2 py-2">Write</th>
                    </tr>
                  </thead>
                  <tbody>
                    {targets.map((row) => (
                      <tr key={row.id} className="border-t border-border/60">
                        <td className="px-2 py-2">
                          <p className="font-medium">{row.label}</p>
                          <p className="text-muted-foreground">{row.id}</p>
                        </td>
                        <td className="px-2 py-2 font-mono">{(row.capabilities ?? []).join(", ") || "-"}</td>
                        <td className="px-2 py-2">{row.health_status}</td>
                        <td className="px-2 py-2">{String(row.safe_for_discord)}</td>
                        <td className="px-2 py-2">{String(row.requires_isolated_execution ?? false)}</td>
                        <td className="px-2 py-2">{String(row.write_capable ?? false)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="pb-2"><CardTitle>Dispatch Workers</CardTitle></CardHeader>
            <CardContent className="space-y-2 text-xs">
              {(workers ?? []).map((worker) => (
                <div key={worker.id} className="rounded border border-border p-2">
                  <p className="font-medium">{worker.label || worker.id}</p>
                  <p className="text-muted-foreground">{worker.host} · {worker.status}</p>
                  <p>isolated: {String(worker.supports_isolated_execution)} · enabled: {String(worker.dispatch_enabled)}</p>
                  <p className="font-mono">{(worker.capabilities ?? []).join(", ") || "-"}</p>
                </div>
              ))}
            </CardContent>
          </Card>
        </div>
      ) : null}

      {tab === "policy" && form ? (
        <Card>
          <CardHeader className="pb-2"><CardTitle>Policy / Safety</CardTitle></CardHeader>
          <CardContent className="grid gap-3 md:grid-cols-2 xl:grid-cols-3 text-sm">
            <label className="inline-flex items-center gap-2 text-xs"><input type="checkbox" checked={form.policy_deterministic_enabled ?? true} onChange={(e) => setForm({ ...form, policy_deterministic_enabled: e.target.checked })} />Deterministic policy engine enabled</label>
            <label className="inline-flex items-center gap-2 text-xs"><input type="checkbox" checked={form.llm_reviewer_enabled ?? false} onChange={(e) => setForm({ ...form, llm_reviewer_enabled: e.target.checked })} />LLM reviewer enabled (advisory)</label>
            <label className="inline-flex items-center gap-2 text-xs"><input type="checkbox" checked={form.isolated_execution_required_for_risky ?? true} onChange={(e) => setForm({ ...form, isolated_execution_required_for_risky: e.target.checked })} />Isolated execution required for risky actions</label>
            <label className="inline-flex items-center gap-2 text-xs"><input type="checkbox" checked={form.direct_execution_disabled ?? true} onChange={(e) => setForm({ ...form, direct_execution_disabled: e.target.checked })} />Direct execution disabled</label>
            <label className="inline-flex items-center gap-2 text-xs"><input type="checkbox" checked={form.raw_shell_disabled ?? true} onChange={(e) => setForm({ ...form, raw_shell_disabled: e.target.checked })} />Raw shell disabled</label>
            <label className="text-xs text-muted-foreground">Reviewer model
              <Input value={String(form.llm_reviewer_model ?? "")} onChange={(e) => setForm({ ...form, llm_reviewer_model: e.target.value })} />
            </label>
            <label className="text-xs text-muted-foreground md:col-span-2 xl:col-span-3">Allowed approver user IDs
              <Textarea rows={3} value={allowedApproversText} onChange={(e) => setAllowedApproversText(e.target.value)} placeholder="One approver ID per line" />
            </label>
            <div className="md:col-span-2 xl:col-span-3">
              <Button
                size="sm"
                onClick={() =>
                  void saveSettings.mutateAsync({
                    policy_deterministic_enabled: form.policy_deterministic_enabled,
                    llm_reviewer_enabled: form.llm_reviewer_enabled,
                    llm_reviewer_model: form.llm_reviewer_model,
                    isolated_execution_required_for_risky: form.isolated_execution_required_for_risky,
                    direct_execution_disabled: form.direct_execution_disabled,
                    raw_shell_disabled: form.raw_shell_disabled,
                    allowed_approver_ids: parseIds(allowedApproversText),
                  })
                }
              >
                Save Policy Settings
              </Button>
            </div>
          </CardContent>
        </Card>
      ) : null}

      {tab === "memory" && form ? (
        <Card>
          <CardHeader className="pb-2"><CardTitle>Session / Memory</CardTitle></CardHeader>
          <CardContent className="space-y-3 text-sm">
            <p className="text-xs text-muted-foreground">Discord sessions use Redis session state plus indexed MEM.md references, not full raw memory dumps.</p>
            <div className="grid gap-2 md:grid-cols-3">
              <Input value={bootstrapUserId} onChange={(e) => setBootstrapUserId(e.target.value)} placeholder="discord user id" />
              <Input value={bootstrapGuildId} onChange={(e) => setBootstrapGuildId(e.target.value)} placeholder="guild id" />
              <Input value={bootstrapChannelId} onChange={(e) => setBootstrapChannelId(e.target.value)} placeholder="channel id" />
            </div>
            <div className="flex flex-wrap gap-2">
              <Button
                size="sm"
                variant="outline"
                onClick={() => void bootstrapSession.mutateAsync({ user_id: bootstrapUserId, guild_id: bootstrapGuildId, channel_id: bootstrapChannelId })}
                disabled={!bootstrapUserId.trim()}
              >
                Resolve Session
              </Button>
              <Button size="sm" variant="outline" onClick={() => void reindexMemory.mutateAsync({ dry_run: false })}>Re-index MEM</Button>
            </div>
            {bootstrapSession.data ? <pre className="overflow-auto rounded border border-border p-2 text-xs">{JSON.stringify(bootstrapSession.data, null, 2)}</pre> : null}
            {reindexMemory.data ? <pre className="overflow-auto rounded border border-border p-2 text-xs">{JSON.stringify(reindexMemory.data, null, 2)}</pre> : null}

            <label className="text-xs text-muted-foreground">Memory append candidate dry-run
              <Textarea rows={3} value={memoryCandidate} onChange={(e) => setMemoryCandidate(e.target.value)} placeholder="Significant operational note candidate" />
            </label>
            <Button
              size="sm"
              variant="outline"
              onClick={() => void memoryAppend.mutateAsync({ note: memoryCandidate, kind: "operational_note", relevance: 1.0, dry_run: true })}
              disabled={memoryCandidate.trim().length < 8}
            >
              Preview Append Candidate
            </Button>
            {memoryAppend.data ? <pre className="overflow-auto rounded border border-border p-2 text-xs">{JSON.stringify(memoryAppend.data, null, 2)}</pre> : null}
          </CardContent>
        </Card>
      ) : null}

      {tab === "settings" && form ? (
        <Card>
          <CardHeader className="pb-2"><CardTitle>Core Settings</CardTitle></CardHeader>
          <CardContent className="grid gap-3 md:grid-cols-2 xl:grid-cols-3 text-sm">
            <label className="inline-flex items-center gap-2 text-xs"><input type="checkbox" checked={form.enabled} onChange={(e) => setForm({ ...form, enabled: e.target.checked })} />Integration enabled</label>
            <label className="inline-flex items-center gap-2 text-xs"><input type="checkbox" checked={form.bridge_auth_enabled} onChange={(e) => setForm({ ...form, bridge_auth_enabled: e.target.checked })} />Bridge auth enabled</label>
            <label className="inline-flex items-center gap-2 text-xs"><input type="checkbox" checked={form.dispatch_enabled} onChange={(e) => setForm({ ...form, dispatch_enabled: e.target.checked })} />Dispatch enabled</label>
            <label className="inline-flex items-center gap-2 text-xs"><input type="checkbox" checked={form.read_only_mode} onChange={(e) => setForm({ ...form, read_only_mode: e.target.checked })} />Read-only mode</label>
            <label className="inline-flex items-center gap-2 text-xs"><input type="checkbox" checked={form.require_explicit_approval} onChange={(e) => setForm({ ...form, require_explicit_approval: e.target.checked })} />Require explicit approval</label>
            <label className="inline-flex items-center gap-2 text-xs"><input type="checkbox" checked={form.dm_disabled} onChange={(e) => setForm({ ...form, dm_disabled: e.target.checked })} />DM disabled</label>

            <label className="text-xs text-muted-foreground">Bridge URL
              <Input value={form.bridge_url} onChange={(e) => setForm({ ...form, bridge_url: e.target.value })} />
            </label>
            <label className="text-xs text-muted-foreground">Guild sync mode
              <Input value={form.guild_sync_mode} onChange={(e) => setForm({ ...form, guild_sync_mode: e.target.value })} />
            </label>
            <label className="text-xs text-muted-foreground">Heartbeat poll seconds
              <Input type="number" value={String(form.heartbeat_poll_seconds)} onChange={(e) => setForm({ ...form, heartbeat_poll_seconds: Number(e.target.value || 30) })} />
            </label>

            <label className="text-xs text-muted-foreground">New bridge auth key
              <Input type="password" value={bridgeApiKeyInput} onChange={(e) => setBridgeApiKeyInput(e.target.value)} />
            </label>
            <label className="text-xs text-muted-foreground">New bot token
              <Input type="password" value={botTokenInput} onChange={(e) => setBotTokenInput(e.target.value)} />
            </label>
            <div className="text-xs text-muted-foreground">
              <p>Bridge key: <span className="font-mono">{form.bridge_api_key_masked || "-"}</span></p>
              <p>Bot token: <span className="font-mono">{form.bot_token_masked || "-"}</span></p>
            </div>

            <label className="text-xs text-muted-foreground">Allowed user IDs
              <Textarea rows={3} value={allowedUsersText} onChange={(e) => setAllowedUsersText(e.target.value)} />
            </label>
            <label className="text-xs text-muted-foreground">Allowed guild IDs
              <Textarea rows={3} value={allowedGuildsText} onChange={(e) => setAllowedGuildsText(e.target.value)} />
            </label>
            <label className="text-xs text-muted-foreground">Allowed channel IDs
              <Textarea rows={3} value={allowedChannelsText} onChange={(e) => setAllowedChannelsText(e.target.value)} />
            </label>
            <label className="text-xs text-muted-foreground md:col-span-2 xl:col-span-1">Allowed role IDs
              <Textarea rows={3} value={allowedRolesText} onChange={(e) => setAllowedRolesText(e.target.value)} />
            </label>

            <div className="md:col-span-2 xl:col-span-3">
              <Button
                size="sm"
                onClick={() =>
                  void saveSettings.mutateAsync({
                    enabled: form.enabled,
                    bridge_url: form.bridge_url,
                    bridge_auth_enabled: form.bridge_auth_enabled,
                    dispatch_enabled: form.dispatch_enabled,
                    read_only_mode: form.read_only_mode,
                    require_explicit_approval: form.require_explicit_approval,
                    dm_disabled: form.dm_disabled,
                    guild_sync_mode: form.guild_sync_mode,
                    heartbeat_poll_seconds: form.heartbeat_poll_seconds,
                    allowed_user_ids: parseIds(allowedUsersText),
                    allowed_guild_ids: parseIds(allowedGuildsText),
                    allowed_channel_ids: parseIds(allowedChannelsText),
                    allowed_role_ids: parseIds(allowedRolesText),
                    ...(bridgeApiKeyInput.trim() ? { bridge_api_key: bridgeApiKeyInput.trim() } : {}),
                    ...(botTokenInput.trim() ? { bot_token: botTokenInput.trim() } : {}),
                  }).then(() => {
                    setBridgeApiKeyInput("");
                    setBotTokenInput("");
                  })
                }
              >
                Save Core Settings
              </Button>
            </div>
          </CardContent>
        </Card>
      ) : null}
    </div>
  );
}

function OverviewCard({ title, ok, detail }: { title: string; ok: boolean; detail: string }) {
  return (
    <Card>
      <CardHeader className="pb-2"><CardTitle>{title}</CardTitle></CardHeader>
      <CardContent>
        <div className="flex items-center gap-2">
          <StatusDot status={ok ? "healthy" : "down"} size="md" pulse={ok} />
          <span className="text-sm">{detail}</span>
        </div>
      </CardContent>
    </Card>
  );
}
