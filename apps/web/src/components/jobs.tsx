"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { Bookmark, BookmarkCheck, Building2, CheckCircle2, CircleDashed, ExternalLink, EyeOff, Link2, MapPin, Radar, XCircle } from "lucide-react";
import { Bookmarklet } from "@/components/bookmarklet";
import { Badge, Button, Checkbox, Modal, Notice, Textarea, Input, useToast } from "@/components/ui";
import { api } from "@/lib/api";
import { postedLabel, salaryLabel } from "@/lib/format";
import { errorMessage } from "@/lib/hooks";
import type { DiscoveryStatus, JobCard } from "@/lib/types";
import { cn } from "@/lib/utils";

const LEVEL_TONE: Record<string, "accent" | "good" | "neutral" | "warn"> = {
  intern: "accent",
  new_grad: "accent",
  entry: "good",
  unspecified: "neutral",
  mid: "warn",
  senior: "warn",
  lead: "warn",
  manager: "warn",
};

export function relevanceTone(value: number | undefined) {
  if (value === undefined) return "text-muted";
  if (value >= 80) return "text-success";
  if (value >= 60) return "text-accent";
  return "text-muted";
}

export function JobRow({
  job,
  selected,
  onSelect,
  onSave,
  onDismiss,
  compact,
}: {
  job: JobCard;
  selected?: boolean;
  onSelect?: (value: boolean) => void;
  onSave?: (job: JobCard) => void;
  onDismiss?: (job: JobCard) => void;
  compact?: boolean;
}) {
  const matched = job.matched_skills || [];
  const unverified = job.unverified_skills || [];
  const salary = salaryLabel(job.salary_min, job.salary_max, job.salary_currency);
  return (
    <div className={cn("group relative rounded-xl border bg-surface p-4 shadow-card transition hover:border-accent/40", selected ? "border-accent/60 ring-1 ring-accent/30" : "border-line")}>
      <div className="flex gap-3">
        {onSelect && (
          <div className="pt-0.5">
            <Checkbox checked={Boolean(selected)} onChange={onSelect} />
          </div>
        )}
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-start justify-between gap-x-3 gap-y-1">
            <div className="min-w-0">
              <Link href={`/jobs/${job.id}`} className="block text-[15px] font-semibold leading-snug text-ink hover:text-accent">
                {job.title}
              </Link>
              <div className="mt-0.5 flex flex-wrap items-center gap-x-3 gap-y-0.5 text-[13px] text-muted">
                <span className="inline-flex items-center gap-1 font-medium text-ink/80">
                  <Building2 className="h-3.5 w-3.5 text-faint" />
                  {job.company}
                </span>
                <span className="inline-flex items-center gap-1">
                  <MapPin className="h-3.5 w-3.5 text-faint" />
                  {job.location || job.location_label}
                </span>
                <span>{postedLabel(job.posted_days_ago, job.discovered_at)}</span>
                {salary && <span>{salary}</span>}
              </div>
            </div>
            {job.relevance !== undefined && (
              <div className="text-right" title={(job.relevance_reasons || []).join(" · ") || "Relevance to your saved search"}>
                <div className={cn("text-[18px] font-semibold leading-none", relevanceTone(job.relevance))}>{job.relevance}</div>
                <div className="text-[11px] text-muted">match</div>
              </div>
            )}
          </div>
          <div className="mt-2.5 flex flex-wrap items-center gap-1.5">
            {job.is_sample && <Badge tone="warn">Practice listing</Badge>}
            <Badge tone={LEVEL_TONE[job.level] || "neutral"}>{job.level_label}</Badge>
            <Badge tone={job.location_scope === "gta" ? "good" : "neutral"}>{job.location_label}</Badge>
            {job.role_label && <Badge>{job.role_label}</Badge>}
            {job.work_arrangement && job.work_arrangement !== "unknown" && job.work_arrangement !== "remote" && <Badge>{job.work_arrangement === "onsite" ? "On-site" : "Hybrid"}</Badge>}
            {job.is_user_added && <Badge tone="accent">Added by you</Badge>}
          </div>
          {!compact && (matched.length > 0 || unverified.length > 0) && (
            <div className="mt-2.5 space-y-1 text-[12.5px]">
              {matched.length > 0 && (
                <div className="flex flex-wrap items-center gap-1">
                  <CheckCircle2 className="h-3.5 w-3.5 text-success" />
                  <span className="text-muted">You have</span>
                  {matched.slice(0, 7).map((skill) => (
                    <span key={skill} className="rounded bg-success-soft px-1.5 py-px text-success">{skill}</span>
                  ))}
                </div>
              )}
              {unverified.length > 0 && (
                <div className="flex flex-wrap items-center gap-1">
                  <CircleDashed className="h-3.5 w-3.5 text-warn" />
                  <span className="text-muted">Not on your profile yet</span>
                  {unverified.slice(0, 6).map((skill) => (
                    <span key={skill} className="rounded bg-warn-soft px-1.5 py-px text-warn">{skill}</span>
                  ))}
                </div>
              )}
            </div>
          )}
          <div className="mt-3 flex flex-wrap items-center justify-between gap-2 border-t border-line pt-2.5">
            <div className="flex flex-wrap items-center gap-x-2 text-[12px] text-muted">
              <span>
                via <span className="font-medium text-ink/80">{job.source_label}</span>
              </span>
              {job.also_seen_on?.length > 0 && <span>· also on {job.also_seen_on.map((item) => item.label).join(", ")}</span>}
            </div>
            <div className="flex items-center gap-1">
              {job.application_url && (
                <a href={job.application_url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-[12.5px] text-muted hover:bg-surface2 hover:text-ink">
                  <ExternalLink className="h-3.5 w-3.5" /> Original
                </a>
              )}
              {onDismiss && (
                <button onClick={() => onDismiss(job)} className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-[12.5px] text-muted hover:bg-surface2 hover:text-ink" title="Not interested">
                  <EyeOff className="h-3.5 w-3.5" /> Hide
                </button>
              )}
              {onSave && (
                <button onClick={() => onSave(job)} className={cn("inline-flex items-center gap-1 rounded-md px-2 py-1 text-[12.5px] hover:bg-surface2", job.saved ? "text-accent" : "text-muted hover:text-ink")}>
                  {job.saved ? <BookmarkCheck className="h-3.5 w-3.5" /> : <Bookmark className="h-3.5 w-3.5" />}
                  {job.saved ? "Saved" : "Save"}
                </button>
              )}
              <Link href={`/jobs/${job.id}`} className="rounded-md bg-surface2 px-2.5 py-1 text-[12.5px] font-medium text-ink hover:bg-line">
                View
              </Link>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

/** Starts and follows a background discovery run. */
export function useDiscovery(onFinished?: () => void) {
  const [status, setStatus] = useState<DiscoveryStatus | null>(null);
  const [running, setRunning] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const finished = useRef(onFinished);
  finished.current = onFinished;

  const poll = useCallback(async (taskId: string) => {
    try {
      const next = await api<DiscoveryStatus>(`/jobs/discover/${taskId}`);
      setStatus(next);
      if (next.done) {
        setRunning(false);
        finished.current?.();
        return;
      }
    } catch {
      /* keep polling */
    }
    timer.current = setTimeout(() => poll(taskId), 1500);
  }, []);

  useEffect(() => {
    api<DiscoveryStatus | Record<string, never>>("/jobs/discover/latest")
      .then((latest) => {
        if (latest && "id" in latest) {
          setStatus(latest as DiscoveryStatus);
          if (!(latest as DiscoveryStatus).done) {
            setRunning(true);
            poll((latest as DiscoveryStatus).id);
          }
        }
      })
      .catch(() => undefined);
    return () => {
      if (timer.current) clearTimeout(timer.current);
    };
  }, [poll]);

  const start = useCallback(
    async (profileId?: string, keywords = "") => {
      setRunning(true);
      const { task_id } = await api<{ task_id: string }>("/jobs/discover", { method: "POST", body: JSON.stringify({ profile_id: profileId, keywords }) });
      poll(task_id);
    },
    [poll],
  );

  const follow = useCallback(
    (taskId: string) => {
      setRunning(true);
      poll(taskId);
    },
    [poll],
  );

  return { status, running, start, follow };
}

export function DiscoveryPanel({ status, running }: { status: DiscoveryStatus | null; running: boolean }) {
  const [expanded, setExpanded] = useState(false);
  if (!status) return null;
  const sources = Object.entries(status.sources || {});
  const done = sources.filter(([, item]) => item.status === "done" || item.status === "error").length;
  const found = sources.reduce((sum, [, item]) => sum + (item.found || 0), 0);
  const errors = sources.filter(([, item]) => item.status === "error");
  const pct = sources.length ? Math.round((100 * done) / sources.length) : running ? 5 : 100;
  return (
    <div className="rounded-xl border border-line bg-surface p-4 shadow-card">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2 text-[13.5px]">
          <Radar className={cn("h-4 w-4", running ? "animate-pulse text-accent" : "text-muted")} />
          {running ? (
            <span>
              Searching {sources.length || "all"} sources… <span className="text-muted">{done}/{sources.length} done, {found} relevant so far</span>
            </span>
          ) : (
            <span>
              Last search {status.finished_at ? new Date(status.finished_at).toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }) : ""}:{" "}
              <span className="font-medium">{status.found ?? status.created + status.updated} relevant postings found, {status.created} new</span>
              {status.expired > 0 && <span className="text-muted">, {status.expired} closed postings removed</span>}
            </span>
          )}
        </div>
        {sources.length > 0 && (
          <button className="text-[12.5px] text-muted hover:text-ink" onClick={() => setExpanded((value) => !value)}>
            {expanded ? "Hide sources" : `Show ${sources.length} sources`}
            {errors.length > 0 && <span className="ml-1 text-warn">({errors.length} had problems)</span>}
          </button>
        )}
      </div>
      {running && (
        <div className="mt-3 h-1 overflow-hidden rounded-full bg-surface2">
          <div className="h-full rounded-full bg-accent transition-all" style={{ width: `${Math.max(pct, 4)}%` }} />
        </div>
      )}
      {expanded && (
        <div className="mt-3 grid gap-x-6 gap-y-1 text-[12.5px] sm:grid-cols-2 lg:grid-cols-3">
          {sources
            .sort((a, b) => (b[1].found || 0) - (a[1].found || 0))
            .map(([key, item]) => (
              <div key={key} className="flex items-center justify-between gap-2 border-b border-line/60 py-1">
                <span className="flex min-w-0 items-center gap-1.5 truncate">
                  {item.status === "error" ? <XCircle className="h-3.5 w-3.5 shrink-0 text-warn" /> : item.status === "done" ? <CheckCircle2 className="h-3.5 w-3.5 shrink-0 text-success" /> : <CircleDashed className="h-3.5 w-3.5 shrink-0 animate-spin text-faint" />}
                  <span className="truncate" title={item.error || ""}>{item.label}</span>
                </span>
                <span className="shrink-0 text-muted">{item.status === "error" ? "unavailable" : `${item.found}${item.new ? ` (${item.new} new)` : ""}`}</span>
              </div>
            ))}
        </div>
      )}
    </div>
  );
}

const BOOKMARKLET = `javascript:(()=>{const s=window.getSelection().toString();const ld=[...document.querySelectorAll('script[type="application/ld+json"]')].map(e=>e.textContent).join('\\n');const t=(s||document.body.innerText).slice(0,15000);const d={url:location.href,title:document.title,text:t,ld:ld.slice(0,15000)};window.open('ORIGIN/jobs/import#'+encodeURIComponent(JSON.stringify(d)),'_blank');})();`;

export function bookmarkletCode() {
  if (typeof window === "undefined") return "";
  return BOOKMARKLET.replace("ORIGIN", window.location.origin);
}

export function ImportJobModal({ open, onClose, onImported, initial }: { open: boolean; onClose: () => void; onImported: (id: string) => void; initial?: { url?: string; title?: string; company?: string; description?: string } }) {
  const toast = useToast();
  const [url, setUrl] = useState(initial?.url || "");
  const [title, setTitle] = useState(initial?.title || "");
  const [company, setCompany] = useState(initial?.company || "");
  const [location, setLocation] = useState("");
  const [description, setDescription] = useState(initial?.description || "");
  const [needsText, setNeedsText] = useState<string>("");
  const [pending, setPending] = useState(false);

  useEffect(() => {
    if (open && initial) {
      setUrl(initial.url || "");
      setTitle(initial.title || "");
      setCompany(initial.company || "");
      setDescription(initial.description || "");
    }
  }, [open, initial]);

  async function openInBrowser() {
    setPending(true);
    try {
      await api("/jobs/capture/start", { method: "POST", body: JSON.stringify({ portal: "web", url }) });
      toast("Opened in the ApplyPilot window. Sign in there if asked; the posting is saved once it is on screen. Follow it on the Jobs page.", "good");
      onClose();
    } catch (err) {
      setNeedsText(errorMessage(err));
    } finally {
      setPending(false);
    }
  }

  async function submit() {
    setPending(true);
    try {
      const created = await api<{ id: string; title: string; company: string }>("/jobs/import", {
        method: "POST",
        body: JSON.stringify({ url: url || null, title: title || null, company: company || null, location: location || null, description: description || null }),
      });
      toast(`Added ${created.title} at ${created.company}.`, "good");
      onImported(created.id);
      onClose();
    } catch (err) {
      setNeedsText(errorMessage(err));
    } finally {
      setPending(false);
    }
  }

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Add a job"
      description="Paste a link to a posting. Workday, Greenhouse, Lever, Ashby, and most employer sites are read automatically. LinkedIn and Experience York links open in the ApplyPilot window, where you sign in yourself."
      wide
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>Cancel</Button>
          <Button onClick={submit} loading={pending} disabled={!url && description.length < 40}>Add job</Button>
        </>
      }
    >
      <div className="space-y-3">
        <Input label="Posting URL" placeholder="https://…" value={url} onChange={(event) => setUrl(event.target.value)} />
        {needsText && (
          <Notice
            tone="warn"
            action={url ? <Button size="sm" variant="secondary" onClick={openInBrowser} loading={pending}>Open it in the ApplyPilot window</Button> : undefined}
          >
            {needsText} Or let ApplyPilot open it in its own browser window, where you are signed in, and save it from the page you see.
          </Notice>
        )}
        <div className="grid gap-3 sm:grid-cols-3">
          <Input label="Job title" value={title} onChange={(event) => setTitle(event.target.value)} placeholder="Optional with a supported link" />
          <Input label="Company" value={company} onChange={(event) => setCompany(event.target.value)} />
          <Input label="Location" value={location} onChange={(event) => setLocation(event.target.value)} placeholder="Toronto, ON" />
        </div>
        <Textarea label="Job description" value={description} onChange={(event) => setDescription(event.target.value)} className="min-h-40" placeholder="Paste the full description, including requirements." />
        <div className="rounded-lg bg-surface2 p-3 text-[12.5px] text-muted">
          <div className="mb-1 flex items-center gap-1.5 font-medium text-ink">
            <Link2 className="h-3.5 w-3.5" /> One-click import from any job page
          </div>
          Drag this button to your bookmarks bar:{" "}
          <Bookmarklet code={bookmarkletCode()} className="mx-1 inline-block cursor-grab rounded-md bg-accent px-2 py-0.5 font-medium text-accent-ink">
            Send to ApplyPilot
          </Bookmarklet>
          . On a LinkedIn or Indeed posting you are viewing, click it to open the posting here with the text filled in. It only reads the page you are looking at. For Experience York, use the bookmark on the York co-op page, which keeps postings private.
        </div>
      </div>
    </Modal>
  );
}
