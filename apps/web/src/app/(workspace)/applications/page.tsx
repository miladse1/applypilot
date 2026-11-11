"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { CheckCheck, HelpCircle, Send, Sparkles } from "lucide-react";
import { ApplyQueue, StartApplyModal, supportBadge } from "@/components/apply-queue";
import { Badge, Button, Checkbox, EmptyState, LinkButton, LoadingBlock, Notice, PageHeader, Tabs, useToast } from "@/components/ui";
import { api } from "@/lib/api";
import { fullDate } from "@/lib/format";
import { errorMessage, useApi } from "@/lib/hooks";
import { STAGE_TONE } from "@/lib/labels";
import type { Application } from "@/lib/types";

const TABS: Array<{ value: string; label: string; statuses: string[] }> = [
  { value: "action", label: "Needs you", statuses: ["preparing", "awaiting_skill_verification", "awaiting_review", "approved", "submitting", "manual_action_required", "failed"] },
  { value: "submitted", label: "Submitted", statuses: ["submitted"] },
  { value: "interviewing", label: "Interviews & offers", statuses: ["interview", "offer"] },
  { value: "closed", label: "Closed", statuses: ["rejected", "withdrawn"] },
  { value: "all", label: "All", statuses: [] },
];

export default function ApplicationsPage() {
  const toast = useToast();
  const { data, reload, error } = useApi<Application[]>("/applications");
  const [tab, setTab] = useState("action");
  const [selected, setSelected] = useState<string[]>([]);
  const [pending, setPending] = useState(false);
  const [applyIds, setApplyIds] = useState<string[] | null>(null);

  const counts = useMemo(() => Object.fromEntries(TABS.map((item) => [item.value, (data || []).filter((row) => !item.statuses.length || item.statuses.includes(row.status)).length])), [data]);
  const rows = (data || []).filter((row) => {
    const active = TABS.find((item) => item.value === tab)!;
    return !active.statuses.length || active.statuses.includes(row.status);
  });
  const selectable = rows.filter((row) => row.status === "awaiting_review" || (row.status === "approved" && row.approval_valid && !row.is_sample));
  const selectedReview = selected.filter((id) => rows.find((row) => row.id === id)?.status === "awaiting_review");
  const selectedApproved = selected.filter((id) => rows.find((row) => row.id === id)?.status === "approved");

  async function approveSelected(thenApply: boolean) {
    setPending(true);
    try {
      const result = await api<{ approved_ids: string[] }>("/applications/approve-batch", {
        method: "POST",
        body: JSON.stringify({ application_ids: selectedReview, acknowledge_unverified: true, acknowledge_gaps: true }),
      });
      toast(`Approved ${result.approved_ids.length} draft${result.approved_ids.length === 1 ? "" : "s"}.`, "good");
      await reload();
      if (thenApply) setApplyIds([...selectedApproved, ...result.approved_ids]);
      setSelected([]);
    } catch (err) {
      toast(errorMessage(err), "bad");
    } finally {
      setPending(false);
    }
  }

  return (
    <div>
      <PageHeader
        title="Applications"
        description="Every draft waits for your approval. ApplyPilot can then fill in and submit approved applications in a Chrome window, and it counts one as submitted only when the employer's confirmation appears."
        actions={<LinkButton href="/jobs" icon={<Send className="h-4 w-4" />}>Find jobs to apply to</LinkButton>}
      />
      {error && <Notice tone="bad">{error}</Notice>}
      <ApplyQueue onChange={reload} />
      <Tabs items={TABS.map((item) => ({ value: item.value, label: item.label, count: counts[item.value] }))} value={tab} onChange={(value) => { setTab(value); setSelected([]); }} className="mb-4" />
      {!data ? (
        <LoadingBlock label="Loading applications" />
      ) : rows.length === 0 ? (
        <EmptyState icon={<Send className="h-5 w-5" />} title={tab === "action" ? "Nothing needs you right now" : "No applications here yet"} action={<LinkButton href="/jobs">Browse jobs</LinkButton>}>
          Select jobs on the Jobs page and choose “Prepare applications”, or ask the assistant to prepare them.
        </EmptyState>
      ) : (
        <>
          {selectable.length > 0 && (
            <div className="mb-3 flex flex-wrap items-center justify-between gap-2 text-[13px]">
              <Checkbox
                checked={selected.length > 0 && selected.length === selectable.length}
                onChange={(value) => setSelected(value ? selectable.map((row) => row.id) : [])}
                label={<span className="text-muted">Select all ready to approve or apply ({selectable.length})</span>}
              />
              <div className="flex flex-wrap gap-2">
                {selectedReview.length > 0 && (
                  <Button size="sm" variant="secondary" icon={<CheckCheck className="h-4 w-4" />} loading={pending} onClick={() => approveSelected(false)}>
                    Approve {selectedReview.length}
                  </Button>
                )}
                {selected.length > 0 && (
                  <Button
                    size="sm"
                    icon={<Sparkles className="h-4 w-4" />}
                    loading={pending}
                    onClick={() => (selectedReview.length ? approveSelected(true) : setApplyIds(selectedApproved))}
                  >
                    {selectedReview.length ? "Approve & apply" : "Apply"} with ApplyPilot ({selected.length})
                  </Button>
                )}
              </div>
            </div>
          )}
          <div className="overflow-hidden rounded-xl border border-line bg-surface shadow-card">
            {rows.map((row) => (
              <div key={row.id} className="flex flex-wrap items-center gap-3 border-b border-line px-4 py-3 last:border-b-0 hover:bg-surface2/50">
                <div className="w-5">
                  {selectable.includes(row) && <Checkbox checked={selected.includes(row.id)} onChange={(value) => setSelected((current) => (value ? [...current, row.id] : current.filter((id) => id !== row.id)))} />}
                </div>
                <Link href={`/applications/${row.id}`} className="min-w-0 flex-1">
                  <div className="truncate text-[14px] font-medium hover:text-accent">{row.title}</div>
                  <div className="truncate text-[12.5px] text-muted">
                    {row.company} · {row.location || "Location not listed"} · updated {fullDate(row.updated_at)}
                  </div>
                </Link>
                <div className="flex flex-wrap items-center gap-1.5">
                  {row.is_sample && <Badge tone="warn">Practice</Badge>}
                  {row.open_questions > 0 && (
                    <Badge tone="warn" icon={<HelpCircle className="h-3 w-3" />}>
                      {row.open_questions} question{row.open_questions === 1 ? "" : "s"}
                    </Badge>
                  )}
                  {row.resume?.generation?.method === "ai" && <Badge tone="accent">Claude-tailored</Badge>}
                  {["approved", "awaiting_review"].includes(row.status) && !row.is_sample && supportBadge(row.autoapply)}
                  {row.submission_label ? <Badge tone={row.submission_label.startsWith("Simulated") ? "warn" : "good"}>{row.submission_label}</Badge> : <Badge tone={STAGE_TONE[row.status] || "neutral"}>{row.stage}</Badge>}
                  {row.submission_label && row.status !== "submitted" && <Badge tone={STAGE_TONE[row.status] || "neutral"}>{row.stage}</Badge>}
                </div>
              </div>
            ))}
          </div>
        </>
      )}
      {applyIds && (
        <StartApplyModal
          open
          onClose={() => setApplyIds(null)}
          rows={(data || []).filter((row) => applyIds.includes(row.id))}
          onStarted={reload}
        />
      )}
    </div>
  );
}
