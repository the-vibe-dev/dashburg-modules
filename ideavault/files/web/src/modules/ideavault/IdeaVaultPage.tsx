import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import {
  Archive,
  ChevronDown,
  Pin,
  Plus,
  Search,
  Star,
  Tags,
  Timer,
  Trash2,
} from "lucide-react";

import {
  useCancelTopicFactoryQueueItem,
  useCreateIdeaVaultItem,
  useDeleteTopicFactoryQueueItem,
  useDeleteIdeaVaultItem,
  useEnqueueTopicFactory,
  useIdeaVaultItem,
  useIdeaVaultLineage,
  useIdeaVaultItems,
  usePatchIdeaVaultItem,
  useReorderIdeaVaultItems,
  useStartTopicFactoryQueueItem,
  useTopicFactoryQueue,
} from "../../shared/api/hooks";
import type { IdeaVaultItem, IdeaVaultType } from "../../shared/api/types";
import { Button } from "../../shared/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "../../shared/components/ui/card";
import { Input, Textarea } from "../../shared/components/ui/input";
import { PageHeader } from "../../shared/components/ui/page-header";
import { AdvancedRawJson, ObjectReadout } from "../../shared/components/ui/readouts";

const TYPES: IdeaVaultType[] = ["trend", "topic", "idea"];
const TRENDS_FOCUS_QUERY_STORAGE_KEY = "dashburg.trends.focusQuery";
const TRENDS_MODE_STORAGE_KEY = "dashburg.trends.mode";
const LINK_BUTTON_OUTLINE_SM =
  "inline-flex items-center justify-center gap-1.5 rounded-lg border border-border bg-transparent px-2.5 py-1 text-xs font-medium text-foreground transition-all duration-150 hover:bg-white/5 hover:border-border/80";

function typeClass(type: string): string {
  if (type === "trend") return "border-warning/30 bg-warning/10 text-warning";
  if (type === "topic") return "border-primary/30 bg-primary/10 text-primary";
  return "border-success/30 bg-success/10 text-success";
}

function relativeTime(ts: string): string {
  const d = new Date(ts);
  if (Number.isNaN(d.getTime())) return ts;
  const diff = Math.floor((Date.now() - d.getTime()) / 1000);
  if (diff < 60) return `${diff}s`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h`;
  return `${Math.floor(diff / 86400)}d`;
}

function ideaTypeFromItem(item: IdeaVaultItem): string {
  const payloadType = String((item.payload?.idea_type as string | undefined) ?? "").trim().toLowerCase();
  if (payloadType) return payloadType;
  const sourceType = String((item.source?.idea_type as string | undefined) ?? "").trim().toLowerCase();
  if (sourceType) return sourceType;
  return "opportunity";
}

export function IdeaVaultPage() {
  const [search, setSearch] = useState("");
  const [type, setType] = useState("");
  const [sort, setSort] = useState<"priority" | "newest" | "oldest" | "score">("priority");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [dragItemId, setDragItemId] = useState<string | null>(null);
  const [showAdd, setShowAdd] = useState(false);
  const [title, setTitle] = useState("");
  const [summary, setSummary] = useState("");
  const [tagsText, setTagsText] = useState("");
  const [itemType, setItemType] = useState<IdeaVaultType>("idea");
  const [notice, setNotice] = useState("");
  const [titleDraft, setTitleDraft] = useState("");
  const [summaryDraft, setSummaryDraft] = useState("");

  const itemsQuery = useIdeaVaultItems({
    search,
    type: type || undefined,
    sort,
    include_payload: false,
    limit: 300,
  });
  const queueQuery = useTopicFactoryQueue();

  const createItem = useCreateIdeaVaultItem();
  const patchItem = usePatchIdeaVaultItem();
  const deleteItem = useDeleteIdeaVaultItem();
  const reorderItems = useReorderIdeaVaultItems();
  const enqueue = useEnqueueTopicFactory();
  const startQueueItem = useStartTopicFactoryQueueItem();
  const cancelQueueItem = useCancelTopicFactoryQueueItem();
  const deleteQueueItem = useDeleteTopicFactoryQueueItem();

  const items = itemsQuery.data ?? [];
  const queueItems = queueQuery.data ?? [];

  const selectedDetailQuery = useIdeaVaultItem(selectedId);
  const selectedFromList = useMemo(() => items.find((item) => item.id === selectedId) ?? null, [items, selectedId]);
  const selected = useMemo(
    () => selectedDetailQuery.data ?? selectedFromList,
    [selectedDetailQuery.data, selectedFromList],
  );
  const selectedLineageQuery = useIdeaVaultLineage(selected?.id ?? null);
  const queueByIdea = useMemo(() => {
    const map = new Map<string, string>();
    for (const row of queueItems) {
      if (row.ideavault_item_id && !map.has(row.ideavault_item_id)) {
        map.set(row.ideavault_item_id, row.id);
      }
    }
    return map;
  }, [queueItems]);

  const allTags = useMemo(() => {
    const set = new Set<string>();
    for (const item of items) {
      for (const t of item.tags ?? []) set.add(String(t));
    }
    return Array.from(set).sort();
  }, [items]);


  useEffect(() => {
    if (!selected) {
      setTitleDraft("");
      setSummaryDraft("");
      return;
    }
    setTitleDraft(selected.title ?? "");
    setSummaryDraft(selected.summary ?? "");
  }, [selected?.id, selected?.title, selected?.summary]);

  useEffect(() => {
    if (!selected) return;
    const nextTitle = titleDraft.trim();
    const nextSummary = summaryDraft.trim();
    const currentTitle = (selected.title ?? "").trim();
    const currentSummary = (selected.summary ?? "").trim();
    if (nextTitle === currentTitle && nextSummary === currentSummary) return;
    const handle = window.setTimeout(() => {
      void patchItem.mutate({
        itemId: selected.id,
        payload: { title: nextTitle, summary: nextSummary },
      });
    }, 450);
    return () => window.clearTimeout(handle);
  }, [patchItem, selected, summaryDraft, titleDraft]);

  const onAdd = async () => {
    if (!title.trim()) return;
    await createItem.mutateAsync({
      title: title.trim(),
      summary: summary.trim(),
      type: itemType,
      tags: tagsText.split(",").map((t) => t.trim()).filter(Boolean),
      source: { module: "IdeaVault", created_manually: true },
      payload: {},
      status: "new",
    });
    setShowAdd(false);
    setTitle("");
    setSummary("");
    setTagsText("");
  };

  const onMove = async (fromId: string, toId: string) => {
    const from = items.findIndex((i) => i.id === fromId);
    const to = items.findIndex((i) => i.id === toId);
    if (from < 0 || to < 0 || from === to) return;
    const next = [...items];
    const [moved] = next.splice(from, 1);
    next.splice(to, 0, moved);
    await reorderItems.mutateAsync(next.map((row) => row.id));
  };

  const onQueueResearch = async (item: IdeaVaultItem) => {
    await enqueue.mutateAsync({
      topic_text: item.title,
      source: { ...(item.source ?? {}), tags: item.tags ?? [] },
      ideavault_item_id: item.id,
      params: { limit: 20, enable_youtube: false, tags: item.tags ?? [] },
    });
    setNotice("Sent to TopicFactory queue.");
  };

  const primeTrendsFocus = (item: IdeaVaultItem) => {
    try {
      window.sessionStorage.setItem(TRENDS_FOCUS_QUERY_STORAGE_KEY, item.title);
      window.sessionStorage.setItem(TRENDS_MODE_STORAGE_KEY, "focused");
    } catch {
      // no-op
    }
    setNotice(`Opened TrendsResearcher for "${item.title}".`);
  };

  return (
    <div className="space-y-4">
      <PageHeader
        title="IdeaVault"
        description="Save trends, topics, and ideas for later and queue research jobs."
        actions={<Button size="sm" onClick={() => setShowAdd((v) => !v)}><Plus size={13} /> Add Idea</Button>}
      />

      <Card>
        <CardContent className="pt-4 space-y-3">
          <div className="grid gap-2 md:grid-cols-[1fr_180px_180px]">
            <div className="relative">
              <Search size={14} className="absolute left-2.5 top-2.5 text-muted-foreground" />
              <Input className="pl-8" placeholder="Search ideas" value={search} onChange={(e) => setSearch(e.target.value)} />
            </div>
            <select className="rounded-lg border border-border bg-input px-3 py-2 text-sm" value={type} onChange={(e) => setType(e.target.value)}>
              <option value="">All types</option>
              {TYPES.map((s) => (
                <option key={s} value={s}>{s}</option>
              ))}
            </select>
            <select className="rounded-lg border border-border bg-input px-3 py-2 text-sm" value={sort} onChange={(e) => setSort(e.target.value as typeof sort)}>
              <option value="priority">Priority</option>
              <option value="newest">Newest</option>
              <option value="oldest">Oldest</option>
              <option value="score">Score</option>
            </select>
          </div>

          <div className="flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
            <Tags size={12} />
            {allTags.length === 0 ? <span>No tags</span> : allTags.map((tag) => <span key={tag} className="rounded bg-background/60 px-1.5 py-0.5">{tag}</span>)}
          </div>
          {notice ? <p className="text-xs text-primary">{notice}</p> : null}

          {showAdd ? (
            <div className="rounded-lg border border-border/60 bg-background/30 p-3 space-y-2">
              <div className="grid gap-2 md:grid-cols-3">
                <Input placeholder="Title" value={title} onChange={(e) => setTitle(e.target.value)} />
                <select className="rounded-lg border border-border bg-input px-3 py-2 text-sm" value={itemType} onChange={(e) => setItemType(e.target.value as IdeaVaultType)}>
                  {TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
                </select>
                <Input placeholder="Tags comma-separated" value={tagsText} onChange={(e) => setTagsText(e.target.value)} />
              </div>
              <Textarea rows={3} placeholder="Summary" value={summary} onChange={(e) => setSummary(e.target.value)} />
              <div className="flex gap-2">
                <Button size="sm" onClick={onAdd} disabled={createItem.isPending || !title.trim()}>
                  <Plus size={12} /> Save
                </Button>
                <Button size="sm" variant="outline" onClick={() => setShowAdd(false)}>Cancel</Button>
              </div>
            </div>
          ) : null}
        </CardContent>
      </Card>

      <div className="grid gap-4 lg:grid-cols-[1fr_380px]">
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {items.map((item) => (
            <div
              key={item.id}
              draggable
              onDragStart={() => setDragItemId(item.id)}
              onDragOver={(e) => e.preventDefault()}
              onDrop={async () => {
                if (dragItemId) await onMove(dragItemId, item.id);
                setDragItemId(null);
              }}
              className={`rounded-xl border bg-card p-3 transition ${selectedId === item.id ? "border-primary" : "border-border hover:border-primary/30"}`}
            >
              <div className="flex items-start justify-between gap-2">
                <button className="text-left" onClick={() => setSelectedId(item.id)}>
                  <p className="font-medium text-sm text-foreground line-clamp-2">{item.title}</p>
                </button>
                <button
                  onClick={() => patchItem.mutate({ itemId: item.id, payload: { pinned: !item.pinned } })}
                  className="text-muted-foreground hover:text-warning"
                >
                  {item.pinned ? <Star size={14} className="fill-warning text-warning" /> : <Pin size={14} />}
                </button>
              </div>

              <div className="mt-2 flex flex-wrap gap-1.5 text-[10px]">
                <span className={`rounded border px-1.5 py-0.5 uppercase ${typeClass(item.type)}`}>{item.type}</span>
                <span className="rounded border border-primary/30 bg-primary/10 px-1.5 py-0.5 uppercase text-primary">{ideaTypeFromItem(item)}</span>
                {item.score != null ? <span className="rounded border border-border px-1.5 py-0.5">score {item.score}</span> : null}
              </div>

              {item.summary ? <p className="mt-2 line-clamp-2 text-xs text-muted-foreground">{item.summary}</p> : null}
              <p className="mt-1 text-[10px] text-muted-foreground">
                source run: {String((item.source?.run_id as string | undefined) ?? (item.source?.source_run_id as string | undefined) ?? "-")}
              </p>

              <div className="mt-2 flex flex-wrap gap-1">
                {(item.tags ?? []).slice(0, 4).map((tag) => (
                  <span key={`${item.id}-${tag}`} className="rounded bg-background/60 px-1.5 py-0.5 text-[10px] text-muted-foreground">{tag}</span>
                ))}
              </div>

              <div className="mt-3 grid grid-cols-2 gap-1.5">
                <Button size="sm" className="w-full" variant="outline" onClick={() => onQueueResearch(item)}>
                  <Timer size={11} /> Send to TopicFactory
                </Button>
                <Link className={`${LINK_BUTTON_OUTLINE_SM} w-full`} to={`/modules/appgen?seed=${encodeURIComponent(item.title)}`}>
                  Open IdeaFactory
                </Link>
                <Link className={`${LINK_BUTTON_OUTLINE_SM} w-full`} to="/modules/topic-insights">
                  Open TopicInsights
                </Link>
                <Link
                  className={`${LINK_BUTTON_OUTLINE_SM} w-full`}
                  to={`/modules/trends?query=${encodeURIComponent(item.title)}`}
                  onClick={() => primeTrendsFocus(item)}
                >
                  Open in TrendsResearcher
                </Link>
                <Button size="sm" className="w-full" variant="outline" onClick={() => patchItem.mutate({ itemId: item.id, payload: { status: "archived" } })}>
                  <Archive size={11} /> Archive
                </Button>
                <Button size="sm" className="w-full col-span-2" variant="danger" onClick={() => deleteItem.mutate(item.id)}>
                  <Trash2 size={11} />
                  Delete
                </Button>
              </div>

              {queueByIdea.has(item.id) ? (
                <p className="mt-2 text-[10px] text-warning">Queued for research</p>
              ) : null}
            </div>
          ))}
          {items.length === 0 ? <div className="text-sm text-muted-foreground">No IdeaVault items found.</div> : null}
        </div>

        <div className="space-y-3">
          <Card className="lg:sticky lg:top-20">
            <CardHeader className="pb-2">
              <CardTitle className="text-[12px]">Detail</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              {!selected ? (
                <div className="rounded-lg border border-dashed border-border p-3 text-sm text-muted-foreground">Select an item.</div>
              ) : (
                <>
                  <Input value={titleDraft} onChange={(e) => setTitleDraft(e.target.value)} />
                  <Textarea rows={4} value={summaryDraft} onChange={(e) => setSummaryDraft(e.target.value)} />
                  <div className="grid gap-2 grid-cols-2">
                    <Button size="sm" className="w-full" onClick={() => onQueueResearch(selected)}>
                      <Timer size={12} /> Send to TopicFactory
                    </Button>
                    <Link className={`${LINK_BUTTON_OUTLINE_SM} w-full`} to={`/modules/appgen?seed=${encodeURIComponent(selected.title)}`}>
                      Open IdeaFactory
                    </Link>
                    <Link className={`${LINK_BUTTON_OUTLINE_SM} w-full`} to="/modules/topic-insights">
                      Open TopicInsights
                    </Link>
                    <Link
                      className={`${LINK_BUTTON_OUTLINE_SM} w-full col-span-2`}
                      to={`/modules/trends?query=${encodeURIComponent(selected.title)}`}
                      onClick={() => primeTrendsFocus(selected)}
                    >
                      Open in TrendsResearcher
                    </Link>
                  </div>
                  <div className="rounded-lg border border-border/60 bg-background/30 p-2 text-xs text-muted-foreground">
                    IdeaVault is packaged as an installable module. Queue research, inspect lineage, and hand promising items to TopicInsights, TrendsResearcher, or IdeaFactory.
                  </div>
                  <details>
                    <summary className="cursor-pointer text-xs text-muted-foreground">Opportunity lineage</summary>
                    <div className="mt-2 space-y-1">
                      {(selectedLineageQuery.data?.edges ?? []).slice(0, 12).map((edge) => (
                        <div key={edge.id} className="rounded border border-border/70 bg-background/40 px-2 py-1 text-[11px] text-muted-foreground">
                          {edge.from_kind}:{edge.from_id} {"->"} {edge.to_kind}:{edge.to_id} ({edge.relation})
                        </div>
                      ))}
                      {selectedLineageQuery.isLoading ? <div className="text-xs text-muted-foreground">Loading lineage…</div> : null}
                      {(selectedLineageQuery.data?.edges ?? []).length === 0 && !selectedLineageQuery.isLoading ? (
                        <div className="text-xs text-muted-foreground">No lineage edges recorded yet.</div>
                      ) : null}
                    </div>
                  </details>
                  <details>
                    <summary className="cursor-pointer text-xs text-muted-foreground flex items-center gap-1">
                      Payload <ChevronDown size={12} />
                    </summary>
                    <div className="mt-2 space-y-2">
                      <ObjectReadout data={(selected.payload as Record<string, unknown> | undefined) ?? {}} />
                      <AdvancedRawJson data={selected.payload ?? {}} />
                    </div>
                  </details>
                </>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-[12px]">TopicFactory Queue (Dashburg)</CardTitle>
            </CardHeader>
            <CardContent className="space-y-2 max-h-[340px] overflow-auto">
              {queueItems.length === 0 ? (
                <div className="text-sm text-muted-foreground">No queue items.</div>
              ) : (
                queueItems.map((row) => (
                  <div key={row.id} className="rounded-lg border border-border/60 bg-background/30 p-2">
                    <p className="text-xs font-medium text-foreground line-clamp-2">{row.topic_text}</p>
                    <p className="mt-1 text-[10px] text-muted-foreground">{row.status} • {relativeTime(row.created_at)}</p>
                    <div className="mt-2 flex gap-1.5">
                      {row.status === "queued" ? (
                        <Button size="sm" variant="outline" onClick={() => startQueueItem.mutate(row.id)}>Start</Button>
                      ) : null}
                      {row.status === "queued" || row.status === "running" ? (
                        <Button size="sm" variant="danger" onClick={() => cancelQueueItem.mutate(row.id)}>Cancel</Button>
                      ) : null}
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => {
                          if (!window.confirm("Remove this item from the IdeaFactory queue?")) return;
                          deleteQueueItem.mutate(row.id);
                        }}
                        disabled={deleteQueueItem.isPending}
                      >
                        Remove
                      </Button>
                    </div>
                  </div>
                ))
              )}
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}
