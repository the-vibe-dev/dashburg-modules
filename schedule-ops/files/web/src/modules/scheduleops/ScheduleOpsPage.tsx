import { useEffect, useMemo, useState } from "react";

import {
  useApplyScheduleOpsNode,
  useDelegateNodeDiagnostic,
  useOrchestrationOverview,
  useScheduleOpsNode,
  useScheduleOpsNodes,
  useScheduleOpsStatus,
  useUpdateScheduleOpsNode,
} from "../../shared/api/hooks";
import type { ScheduleOpsConfig, ScheduleOpsEntry } from "../../shared/api/types";
import { Button } from "../../shared/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "../../shared/components/ui/card";
import { Input, Textarea } from "../../shared/components/ui/input";
import { PageHeader } from "../../shared/components/ui/page-header";
import { Tabs } from "../../shared/components/ui/tabs";

function cloneConfig(config: ScheduleOpsConfig): ScheduleOpsConfig {
  return JSON.parse(JSON.stringify(config)) as ScheduleOpsConfig;
}

function newEntry(kind: "mailbox_dispatch" | "shell_command" = "mailbox_dispatch"): ScheduleOpsEntry {
  return {
    id: `entry-${Math.random().toString(16).slice(2, 8)}`,
    label: kind === "mailbox_dispatch" ? "Mailbox Dispatch" : "Shell Command",
    kind,
    enabled: true,
    cron: "0 * * * *",
    recipient_kind: "any",
    recipient: "",
    limit: 200,
    command: "",
  };
}

function toneForStatus(status: string): string {
  const normalized = String(status || "").toLowerCase();
  if (["running", "healthy", "ok", "idle", "succeeded"].includes(normalized)) return "text-emerald-500";
  if (["scheduled", "queued", "pending"].includes(normalized)) return "text-amber-500";
  if (["missing", "failed", "error", "down", "unreachable"].includes(normalized)) return "text-rose-500";
  return "text-muted-foreground";
}

function fmtTs(value: string | null | undefined): string {
  if (!value) return "-";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleString();
}

export function ScheduleOpsPage() {
  const [activeTab, setActiveTab] = useState("dashboard");
  const { data: nodes = [], isLoading: nodesLoading } = useScheduleOpsNodes();
  const { data: clusterStatus, isLoading: statusLoading, refetch: refetchStatus } = useScheduleOpsStatus();
  const { data: orchestration, refetch: refetchOrchestration } = useOrchestrationOverview();

  const [selectedNode, setSelectedNode] = useState<string>("");
  const [form, setForm] = useState<ScheduleOpsConfig | null>(null);
  const [diagnosticIssue, setDiagnosticIssue] = useState("");

  useEffect(() => {
    if (selectedNode) return;
    const preferred = clusterStatus?.items?.[0]?.node?.id || nodes[0]?.id;
    if (preferred) setSelectedNode(preferred);
  }, [clusterStatus?.items, nodes, selectedNode]);

  const detail = useScheduleOpsNode(selectedNode || null);
  const updateNode = useUpdateScheduleOpsNode();
  const applyNode = useApplyScheduleOpsNode();
  const delegateDiagnostic = useDelegateNodeDiagnostic();

  useEffect(() => {
    const config = detail.data?.config;
    if (config) setForm(cloneConfig(config));
  }, [detail.data?.config, selectedNode]);

  const renderedPreview = useMemo(() => {
    return (detail.data?.rendered?.lines ?? []).join("\n");
  }, [detail.data?.rendered?.lines]);

  const dirty = useMemo(() => {
    if (!form || !detail.data?.config) return false;
    return JSON.stringify(form) !== JSON.stringify(detail.data.config);
  }, [form, detail.data?.config]);

  const jobCountsByNode = useMemo(() => {
    const out: Record<string, { running: number; queued: number }> = {};
    for (const row of orchestration?.running_jobs ?? []) {
      const node = String(row.target_node || "");
      if (!node) continue;
      out[node] = out[node] ?? { running: 0, queued: 0 };
      out[node].running += 1;
    }
    for (const row of orchestration?.queued_jobs ?? []) {
      const node = String(row.target_node || "");
      if (!node) continue;
      out[node] = out[node] ?? { running: 0, queued: 0 };
      out[node].queued += 1;
    }
    return out;
  }, [orchestration?.queued_jobs, orchestration?.running_jobs]);

  const selectedNodeStatus = useMemo(
    () => clusterStatus?.items?.find((row) => row.node?.id === selectedNode),
    [clusterStatus?.items, selectedNode],
  );

  const dashboardNodes = clusterStatus?.items ?? [];

  return (
    <div className="space-y-4">
      <PageHeader compact title="ScheduleOps">
        <p className="text-sm text-muted-foreground">
          Central cron control for node runner dispatch + agent-addressed mailbox workers.
        </p>
      </PageHeader>

      <Tabs
        active={activeTab}
        onChange={setActiveTab}
        tabs={[
          { id: "dashboard", label: "Jobs Dashboard" },
          { id: "config", label: "Setup & Config" },
        ]}
      />

      {activeTab === "dashboard" ? (
        <div className="space-y-4">
          <Card>
            <CardHeader className="pb-2">
              <div className="flex items-center justify-between gap-2">
                <CardTitle>Node Job + Cron Status</CardTitle>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={() => {
                    void refetchStatus();
                    void refetchOrchestration();
                  }}
                >
                  Refresh
                </Button>
              </div>
            </CardHeader>
            <CardContent className="space-y-2">
              {statusLoading ? <p className="text-sm text-muted-foreground">Loading status...</p> : null}
              <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-3">
                {dashboardNodes.map((row) => {
                  const nodeId = row.node?.id ?? row.node_id;
                  const jobs = jobCountsByNode[nodeId] ?? { running: 0, queued: 0 };
                  const activeCron = (row.entries ?? []).filter((entry) => entry.running_now).length;
                  const hasError = Boolean(row.error);
                  return (
                    <button
                      key={nodeId}
                      type="button"
                      className={`rounded border px-3 py-2 text-left ${selectedNode === nodeId ? "border-primary bg-primary/10" : "border-border"}`}
                      onClick={() => setSelectedNode(nodeId)}
                    >
                      <div className="flex items-center justify-between gap-2">
                        <span className="font-medium">{row.node?.label ?? nodeId}</span>
                        <span className={`text-xs ${toneForStatus(row.node?.health_status || "unknown")}`}>{row.node?.health_status || "unknown"}</span>
                      </div>
                      <p className="mt-1 text-xs text-muted-foreground">{nodeId}</p>
                      <div className="mt-2 grid grid-cols-3 gap-2 text-xs">
                        <div>
                          <p className="text-muted-foreground">Cron Running</p>
                          <p className={toneForStatus(activeCron > 0 ? "running" : "idle")}>{activeCron}</p>
                        </div>
                        <div>
                          <p className="text-muted-foreground">Jobs Running</p>
                          <p className={toneForStatus(jobs.running > 0 ? "running" : "idle")}>{jobs.running}</p>
                        </div>
                        <div>
                          <p className="text-muted-foreground">Jobs Queued</p>
                          <p className={toneForStatus(jobs.queued > 0 ? "queued" : "idle")}>{jobs.queued}</p>
                        </div>
                      </div>
                      {hasError ? <p className="mt-2 text-xs text-rose-500">{row.error}</p> : null}
                    </button>
                  );
                })}
              </div>
            </CardContent>
          </Card>

          <div className="grid gap-4 xl:grid-cols-[2fr,1fr]">
            <Card>
              <CardHeader className="pb-2">
                <CardTitle>Active Cron Entries: {(selectedNodeStatus?.node?.label ?? selectedNode) || "-"}</CardTitle>
              </CardHeader>
              <CardContent className="space-y-2">
                {!selectedNodeStatus ? <p className="text-sm text-muted-foreground">Select a node.</p> : null}
                {selectedNodeStatus ? (
                  <>
                    <div className="grid gap-2 md:grid-cols-4 text-xs">
                      <div>
                        <p className="text-muted-foreground">Installed</p>
                        <p className={toneForStatus(selectedNodeStatus.install?.installed ? "ok" : "missing")}>{selectedNodeStatus.install?.installed ? "yes" : "no"}</p>
                      </div>
                      <div>
                        <p className="text-muted-foreground">Managed Header</p>
                        <p className={toneForStatus(selectedNodeStatus.install?.managed_header ? "ok" : "missing")}>{selectedNodeStatus.install?.managed_header ? "yes" : "no"}</p>
                      </div>
                      <div>
                        <p className="text-muted-foreground">Config Updated</p>
                        <p>{fmtTs(selectedNodeStatus.config_updated_at)}</p>
                      </div>
                      <div>
                        <p className="text-muted-foreground">Status Snapshot</p>
                        <p>{fmtTs(selectedNodeStatus.generated_at)}</p>
                      </div>
                    </div>
                    <div className="overflow-auto rounded border border-border">
                      <table className="w-full text-left text-xs">
                        <thead className="bg-muted/40">
                          <tr>
                            <th className="px-2 py-2">Entry</th>
                            <th className="px-2 py-2">Kind</th>
                            <th className="px-2 py-2">Cron</th>
                            <th className="px-2 py-2">Status</th>
                            <th className="px-2 py-2">Running</th>
                            <th className="px-2 py-2">Last Seen</th>
                          </tr>
                        </thead>
                        <tbody>
                          {(selectedNodeStatus.entries ?? []).map((entry) => (
                            <tr key={entry.id} className="border-t border-border">
                              <td className="px-2 py-2">
                                <p className="font-medium">{entry.label || entry.id}</p>
                                <p className="text-muted-foreground">{entry.id}</p>
                              </td>
                              <td className="px-2 py-2">{entry.kind}</td>
                              <td className="px-2 py-2">{entry.cron}</td>
                              <td className={`px-2 py-2 ${toneForStatus(entry.status)}`}>{entry.status}</td>
                              <td className="px-2 py-2">{entry.running_now ? `yes (${entry.matching_pids.length})` : "no"}</td>
                              <td className="px-2 py-2">{fmtTs(entry.last_seen_at)}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </>
                ) : null}
              </CardContent>
            </Card>

            <Card>
              <CardHeader className="pb-2">
                <CardTitle>Orchestration Jobs</CardTitle>
              </CardHeader>
              <CardContent className="space-y-3 text-xs">
                <div>
                  <p className="mb-1 font-medium">Running</p>
                  {(orchestration?.running_jobs ?? []).slice(0, 8).map((job) => (
                    <div key={job.id} className="mb-1 rounded border border-border p-2">
                      <p className="font-medium">{job.title || job.id}</p>
                      <p className="text-muted-foreground">{job.target_node} · {job.status}</p>
                    </div>
                  ))}
                </div>
                <div>
                  <p className="mb-1 font-medium">Queued</p>
                  {(orchestration?.queued_jobs ?? []).slice(0, 8).map((job) => (
                    <div key={job.id} className="mb-1 rounded border border-border p-2">
                      <p className="font-medium">{job.title || job.id}</p>
                      <p className="text-muted-foreground">{job.target_node} · {job.status}</p>
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>
          </div>
        </div>
      ) : null}

      {activeTab === "config" ? (
        <div className="grid gap-4 lg:grid-cols-[320px,1fr]">
          <Card>
            <CardHeader className="pb-2">
              <CardTitle>Nodes</CardTitle>
            </CardHeader>
            <CardContent className="space-y-2">
              {nodesLoading ? <p className="text-sm text-muted-foreground">Loading nodes...</p> : null}
              {nodes.map((node) => (
                <button
                  key={node.id}
                  type="button"
                  className={`w-full rounded border px-3 py-2 text-left text-sm ${selectedNode === node.id ? "border-primary bg-primary/10" : "border-border"}`}
                  onClick={() => setSelectedNode(node.id)}
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-medium">{node.label}</span>
                    <span className={`text-xs ${node.health_ok ? "text-emerald-500" : "text-amber-500"}`}>{node.health_status}</span>
                  </div>
                  <p className="mt-1 text-xs text-muted-foreground">{node.id}</p>
                </button>
              ))}
            </CardContent>
          </Card>

          <div className="space-y-4">
            <Card>
              <CardHeader className="pb-2">
                <CardTitle>Node Schedule</CardTitle>
              </CardHeader>
              <CardContent className="space-y-3">
                {!selectedNode ? <p className="text-sm text-muted-foreground">Select a node.</p> : null}
                {selectedNode && detail.isLoading ? <p className="text-sm text-muted-foreground">Loading schedule...</p> : null}
                {selectedNode && form ? (
                  <>
                    <div className="grid gap-2 md:grid-cols-2">
                      <label className="text-xs text-muted-foreground">
                        Timezone
                        <Input value={form.timezone} onChange={(e) => setForm({ ...form, timezone: e.target.value })} />
                      </label>
                      <label className="text-xs text-muted-foreground">
                        Node
                        <Input value={form.node_id} onChange={(e) => setForm({ ...form, node_id: e.target.value })} />
                      </label>
                    </div>
                    <label className="text-xs text-muted-foreground">
                      Notes
                      <Textarea value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} rows={2} />
                    </label>

                    <div className="space-y-2">
                      {form.entries.map((entry, idx) => (
                        <div key={entry.id || idx} className="rounded border border-border p-2">
                          <div className="grid gap-2 md:grid-cols-6">
                            <Input
                              value={entry.id}
                              onChange={(e) => {
                                const entries = [...form.entries];
                                entries[idx] = { ...entry, id: e.target.value };
                                setForm({ ...form, entries });
                              }}
                              placeholder="entry id"
                            />
                            <Input
                              value={entry.label}
                              onChange={(e) => {
                                const entries = [...form.entries];
                                entries[idx] = { ...entry, label: e.target.value };
                                setForm({ ...form, entries });
                              }}
                              placeholder="label"
                            />
                            <Input
                              value={entry.cron}
                              onChange={(e) => {
                                const entries = [...form.entries];
                                entries[idx] = { ...entry, cron: e.target.value };
                                setForm({ ...form, entries });
                              }}
                              placeholder="cron"
                            />
                            <select
                              className="rounded border border-border bg-input px-2 py-2 text-sm"
                              value={entry.kind}
                              onChange={(e) => {
                                const entries = [...form.entries];
                                entries[idx] = { ...entry, kind: e.target.value };
                                setForm({ ...form, entries });
                              }}
                            >
                              <option value="mailbox_dispatch">mailbox_dispatch</option>
                              <option value="shell_command">shell_command</option>
                            </select>
                            <select
                              className="rounded border border-border bg-input px-2 py-2 text-sm"
                              value={entry.recipient_kind}
                              onChange={(e) => {
                                const entries = [...form.entries];
                                entries[idx] = { ...entry, recipient_kind: e.target.value };
                                setForm({ ...form, entries });
                              }}
                            >
                              <option value="any">any</option>
                              <option value="runner">runner</option>
                              <option value="agent">agent</option>
                            </select>
                            <label className="flex items-center gap-2 rounded border border-border px-2 py-2 text-xs">
                              <input
                                type="checkbox"
                                checked={Boolean(entry.enabled)}
                                onChange={(e) => {
                                  const entries = [...form.entries];
                                  entries[idx] = { ...entry, enabled: e.target.checked };
                                  setForm({ ...form, entries });
                                }}
                              />
                              enabled
                            </label>
                          </div>
                          <div className="mt-2 grid gap-2 md:grid-cols-[2fr,1fr,auto]">
                            <Input
                              value={entry.recipient}
                              onChange={(e) => {
                                const entries = [...form.entries];
                                entries[idx] = { ...entry, recipient: e.target.value };
                                setForm({ ...form, entries });
                              }}
                              placeholder="recipient route e.g. node:aitts/agent:buildbot"
                            />
                            <Input
                              type="number"
                              min={1}
                              max={500}
                              value={entry.limit}
                              onChange={(e) => {
                                const entries = [...form.entries];
                                entries[idx] = { ...entry, limit: Number(e.target.value || 200) };
                                setForm({ ...form, entries });
                              }}
                              placeholder="limit"
                            />
                            <Button
                              type="button"
                              variant="outline"
                              onClick={() => setForm({ ...form, entries: form.entries.filter((_, i) => i !== idx) })}
                            >
                              Remove
                            </Button>
                          </div>
                          {entry.kind === "shell_command" ? (
                            <Input
                              className="mt-2"
                              value={entry.command}
                              onChange={(e) => {
                                const entries = [...form.entries];
                                entries[idx] = { ...entry, command: e.target.value };
                                setForm({ ...form, entries });
                              }}
                              placeholder="shell command"
                            />
                          ) : null}
                        </div>
                      ))}
                      <div className="flex gap-2">
                        <Button type="button" variant="outline" onClick={() => setForm({ ...form, entries: [...form.entries, newEntry("mailbox_dispatch")] })}>
                          Add Mailbox Entry
                        </Button>
                        <Button type="button" variant="outline" onClick={() => setForm({ ...form, entries: [...form.entries, newEntry("shell_command")] })}>
                          Add Shell Entry
                        </Button>
                      </div>
                    </div>

                    <div className="flex flex-wrap gap-2">
                      <Button
                        type="button"
                        disabled={!dirty || updateNode.isPending || !selectedNode}
                        onClick={async () => {
                          if (!selectedNode || !form) return;
                          await updateNode.mutateAsync({ nodeId: selectedNode, config: form });
                        }}
                      >
                        {updateNode.isPending ? "Saving..." : "Save Schedule"}
                      </Button>
                      <Button
                        type="button"
                        variant="outline"
                        disabled={!selectedNode || applyNode.isPending}
                        onClick={async () => {
                          if (!selectedNode) return;
                          await applyNode.mutateAsync(selectedNode);
                          await detail.refetch();
                          await refetchStatus();
                        }}
                      >
                        {applyNode.isPending ? "Applying..." : "Apply To Cron"}
                      </Button>
                    </div>
                  </>
                ) : null}
              </CardContent>
            </Card>

            <Card>
              <CardHeader className="pb-2">
                <CardTitle>Delegate Diagnostic</CardTitle>
              </CardHeader>
              <CardContent className="space-y-2">
                <Textarea
                  rows={4}
                  placeholder="Describe issue x/y/z on this node..."
                  value={diagnosticIssue}
                  onChange={(e) => setDiagnosticIssue(e.target.value)}
                />
                <Button
                  type="button"
                  disabled={!selectedNode || !diagnosticIssue.trim() || delegateDiagnostic.isPending}
                  onClick={async () => {
                    if (!selectedNode || !diagnosticIssue.trim()) return;
                    await delegateDiagnostic.mutateAsync({ node_id: selectedNode, issue: diagnosticIssue.trim() });
                    setDiagnosticIssue("");
                  }}
                >
                  {delegateDiagnostic.isPending ? "Queueing..." : "Create Orchestration Diagnostic Job"}
                </Button>
              </CardContent>
            </Card>

            <Card>
              <CardHeader className="pb-2">
                <CardTitle>Rendered Cron Preview</CardTitle>
              </CardHeader>
              <CardContent>
                <pre className="max-h-72 overflow-auto rounded border border-border bg-background p-2 text-xs">{renderedPreview || "No preview yet."}</pre>
              </CardContent>
            </Card>
          </div>
        </div>
      ) : null}
    </div>
  );
}
