"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { ArrowLeft, Bookmark, BookmarkCheck, CheckCircle2, CircleDashed, ExternalLink, EyeOff, FileText, MinusCircle, RefreshCw, Send, Sparkles, XCircle } from "lucide-react";
import { PortalInfoCard } from "@/components/portal-info";
import { draftPayload, emptyDraft, QuestionCard, type QuestionDraft } from "@/components/questions";
import { Badge, Button, Card, CardHeader, LinkButton, LoadingBlock, Notice, RichText, useToast } from "@/components/ui";
import { api } from "@/lib/api";
import { fullDate, postedLabel, salaryLabel } from "@/lib/format";
import { errorMessage, useApi } from "@/lib/hooks";
import type { JobDetail, MatchItem, Profile, Question, ResumeVersion } from "@/lib/types";
import { cn } from "@/lib/utils";

const GROUPS: Array<{ status: string; title: string; icon: typeof CheckCircle2; tone: string }> = [
  { status: "matched", title: "You have these", icon: CheckCircle2, tone: "text-success" },
  { status: "partial", title: "Partly covered", icon: MinusCircle, tone: "text-accent" },
  { status: "unverified", title: "Not on your profile yet", icon: CircleDashed, tone: "text-warn" },
  { status: "in_progress", title: "You are learning", icon: CircleDashed, tone: "text-muted" },
  { status: "not_possessed", title: "You said you don't have these", icon: XCircle, tone: "text-danger" },
];

export default function JobDetailPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const toast = useToast();
  const { data: job, setData: setJob, error, reload } = useApi<JobDetail>(`/jobs/${params.id}`);
  const { data: profile } = useApi<Profile>("/profile");
  const { data: versions } = useApi<ResumeVersion[]>(`/resume-versions?job_id=${params.id}`);
  const [busy, setBusy] = useState("");
  const [answering, setAnswering] = useState<string | null>(null);
  const [draft, setDraft] = useState<QuestionDraft>(emptyDraft());

  useEffect(() => {
    setDraft(emptyDraft());
  }, [answering]);

  if (!job) return error ? <Notice tone="bad">{error}</Notice> : <LoadingBlock label="Loading job" />;

  async function prepare() {
    setBusy("prepare");
    try {
      const created = await api<{ id: string; status: string }>("/applications", { method: "POST", body: JSON.stringify({ job_id: params.id }) });
      router.push(`/applications/${created.id}`);
    } catch (err) {
      toast(errorMessage(err), "bad");
      setBusy("");
    }
  }

  async function tailor() {
    setBusy("tailor");
    try {
      const version = await api<{ id: string }>("/resume-versions/tailor", { method: "POST", body: JSON.stringify({ job_id: params.id }) });
      router.push(`/resume/versions/${version.id}`);
    } catch (err) {
      toast(errorMessage(err), "bad");
      setBusy("");
    }
  }

  async function toggleSave() {
    if (!job) return;
    await api(`/jobs/${job.id}/save`, { method: job.saved ? "DELETE" : "POST" });
    setJob({ ...job, saved: !job.saved });
  }

  async function dismiss() {
    if (!job) return;
    await api(`/jobs/${job.id}/${job.dismissed ? "dismiss" : "dismiss"}`, { method: job.dismissed ? "DELETE" : "POST" });
    toast(job.dismissed ? "This job is visible again." : "Hidden from your job list.");
    setJob({ ...job, dismissed: !job.dismissed });
  }

  async function verify() {
    setBusy("verify");
    try {
      const result = await api<{ is_active: boolean; description_updated?: boolean }>(`/jobs/${params.id}/verify`, { method: "POST" });
      toast(result.is_active ? (result.description_updated ? "Updated with the full description." : "The posting is still open.") : "The posting has closed.", result.is_active ? "good" : "warn");
      await reload();
    } finally {
      setBusy("");
    }
  }

  async function answer(item: MatchItem) {
    const question: Question = { id: `adhoc-${item.normalized_name}`, job_posting_id: params.id, normalized_name: item.normalized_name, display_name: item.name, prompt: "", priority: item.priority, min_years: null };
    const payload = { ...draftPayload(question, draft, profile), request_id: null };
    try {
      await api("/qualifications/answers", { method: "POST", body: JSON.stringify({ job_id: params.id, answers: [payload] }) });
      toast(`Saved your answer about ${item.name}.`, "good");
      setAnswering(null);
      await reload();
    } catch (err) {
      toast(errorMessage(err), "bad");
    }
  }

  function askAssistant() {
    try {
      sessionStorage.setItem("assistant-context", JSON.stringify({ job_id: params.id }));
    } catch {
      /* ignore */
    }
    router.push("/assistant?context=job");
  }

  const items = job.match.items.filter((item) => item.category !== "authorization");
  const vague = items.filter((item) => item.category === "other");
  const relevant = items.filter((item) => item.category !== "other" && (item.priority !== "optional" || item.status !== "unverified"));
  const counted = relevant.filter((item) => item.priority === "mandatory" || item.priority === "preferred");
  const have = counted.filter((item) => item.status === "matched").length;
  const salary = salaryLabel(job.salary_min, job.salary_max, job.salary_currency);

  return (
    <div>
      <Link href="/jobs" className="mb-4 inline-flex items-center gap-1 text-[13px] text-muted hover:text-ink">
        <ArrowLeft className="h-4 w-4" /> Jobs
      </Link>
      {!job.is_active && <Notice tone="warn" className="mb-4" title="This posting looks closed">It is no longer listed by the employer or has passed its closing date. You can still review it.</Notice>}
      {job.is_sample && <Notice tone="warn" className="mb-4" title="Practice listing">This is sample data for trying ApplyPilot. It is not a real job.</Notice>}
      <header className="mb-6 rounded-xl border border-line bg-surface p-5 shadow-card">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="min-w-0">
            <div className="text-[13.5px] font-medium text-muted">{job.company}</div>
            <h1 className="mt-0.5 text-[22px] font-semibold tracking-tight">{job.title}</h1>
            <div className="mt-1 text-[13.5px] text-muted">
              {job.location || job.location_label} · {postedLabel(job.posted_days_ago, job.discovered_at)}
              {salary && ` · ${salary}`}
            </div>
            <div className="mt-3 flex flex-wrap gap-1.5">
              <Badge tone={["intern", "new_grad"].includes(job.level) ? "accent" : job.level === "entry" ? "good" : "neutral"}>{job.level_label}</Badge>
              <Badge tone={job.location_scope === "gta" ? "good" : "neutral"}>{job.location_label}</Badge>
              {job.role_label && <Badge>{job.role_label}</Badge>}
              {job.employment_type && job.employment_type !== "unknown" && <Badge>{job.employment_type.replace("_", " ")}</Badge>}
              {job.work_arrangement && job.work_arrangement !== "unknown" && <Badge>{job.work_arrangement}</Badge>}
            </div>
          </div>
          {job.relevance !== undefined && (
            <div className="rounded-lg bg-surface2 px-4 py-2 text-center">
              <div className="text-[22px] font-semibold text-accent">{job.relevance}</div>
              <div className="text-[11px] text-muted">match</div>
            </div>
          )}
        </div>
        <div className="mt-4 flex flex-wrap gap-2">
          <Button icon={<Send className="h-4 w-4" />} loading={busy === "prepare"} onClick={prepare} disabled={!job.is_active}>
            Prepare application
          </Button>
          <Button variant="secondary" icon={<FileText className="h-4 w-4" />} loading={busy === "tailor"} onClick={tailor}>
            Tailor my resume
          </Button>
          {job.application_url && (
            <LinkButton href={job.application_url} external icon={<ExternalLink className="h-4 w-4" />}>
              Original posting
            </LinkButton>
          )}
          <Button variant="ghost" icon={job.saved ? <BookmarkCheck className="h-4 w-4 text-accent" /> : <Bookmark className="h-4 w-4" />} onClick={toggleSave}>
            {job.saved ? "Saved" : "Save"}
          </Button>
          <Button variant="ghost" icon={<EyeOff className="h-4 w-4" />} onClick={dismiss}>
            {job.dismissed ? "Show again" : "Not interested"}
          </Button>
          <Button variant="ghost" icon={<Sparkles className="h-4 w-4" />} onClick={askAssistant}>
            Ask the assistant
          </Button>
        </div>
      </header>

      <div className="grid gap-6 lg:grid-cols-[1fr_300px]">
        <div className="min-w-0 space-y-6">
          <Card>
            <CardHeader
              title="How you match"
              description={counted.length ? `You have ${have} of ${counted.length} required or preferred qualifications on your profile. Items not on your profile are unknown, not missing.` : "This posting does not list specific requirements ApplyPilot could read."}
            />
            {job.match.eligibility_conflicts.filter((item) => item.name !== "Work authorization").map((item) => (
              <Notice key={item.name} tone="warn" className="mb-3">{item.message}</Notice>
            ))}
            <div className="space-y-5">
              {GROUPS.map((group) => {
                const rows = relevant.filter((item) => item.status === group.status);
                if (!rows.length) return null;
                const Icon = group.icon;
                return (
                  <div key={group.status}>
                    <div className={cn("mb-2 flex items-center gap-1.5 text-[13px] font-semibold", group.tone)}>
                      <Icon className="h-4 w-4" /> {group.title}
                    </div>
                    <div className="divide-y divide-line rounded-lg border border-line">
                      {rows.map((item) => (
                        <div key={`${item.normalized_name}-${item.priority}`} className="px-3 py-2.5">
                          <div className="flex flex-wrap items-center justify-between gap-2">
                            <div className="flex items-center gap-2">
                              <span className="text-[13.5px] font-medium">{item.name}</span>
                              <Badge tone={item.priority === "mandatory" ? "warn" : "neutral"}>{item.priority === "mandatory" ? "Required" : item.priority === "preferred" ? "Preferred" : item.priority === "optional" ? "Mentioned" : "Unclear"}</Badge>
                            </div>
                            {group.status === "unverified" && item.category === "skill" && answering !== item.normalized_name && (
                              <Button size="sm" variant="subtle" onClick={() => setAnswering(item.normalized_name)}>
                                Answer
                              </Button>
                            )}
                          </div>
                          <p className="mt-0.5 text-[12.5px] text-muted">{item.explanation}</p>
                          {answering === item.normalized_name && (
                            <div className="mt-3 space-y-2">
                              <QuestionCard
                                question={{ id: item.normalized_name, job_posting_id: params.id, normalized_name: item.normalized_name, display_name: item.name, prompt: `Have you used ${item.name}? Your answer is remembered for every job.`, priority: item.priority, min_years: null }}
                                profile={profile}
                                draft={draft}
                                onChange={setDraft}
                              />
                              <div className="flex justify-end gap-2">
                                <Button size="sm" variant="ghost" onClick={() => setAnswering(null)}>Cancel</Button>
                                <Button size="sm" disabled={!draft.choice} onClick={() => answer(item)}>Save answer</Button>
                              </div>
                            </div>
                          )}
                        </div>
                      ))}
                    </div>
                  </div>
                );
              })}
            </div>
            {vague.length > 0 && (
              <div className="mt-5">
                <div className="mb-1.5 text-[13px] font-semibold text-muted">Also mentioned (too general to check)</div>
                <ul className="list-disc space-y-1 pl-5 text-[12.5px] text-muted">
                  {vague.map((item) => (
                    <li key={item.name}>{item.name}</li>
                  ))}
                </ul>
              </div>
            )}
            <p className="mt-4 text-[12px] text-muted">{job.match.disclaimer}</p>
          </Card>
          <Card>
            <CardHeader
              title="Job description"
              actions={
                <Button size="sm" variant="ghost" icon={<RefreshCw className="h-3.5 w-3.5" />} loading={busy === "verify"} onClick={verify}>
                  Check posting
                </Button>
              }
            />
            {job.needs_detail && <Notice tone="neutral" className="mb-3">This source lists only a summary. Use “Check posting” or open the original for the full text.</Notice>}
            <RichText text={job.description || "No description available."} className="text-[13.5px] text-ink/90" />
          </Card>
        </div>

        <aside className="space-y-4">
          {job.source === "yorku" && (
            <Notice tone="neutral" title="Private York posting">
              Kept on this computer and not sent to Claude, as York&rsquo;s co-op terms prohibit sharing postings. Matching, tailoring, and cover letters for it are done locally.
            </Notice>
          )}
          {job.portals && job.portals.length > 0 && <PortalInfoCard jobId={job.id} portals={job.portals} onChanged={() => reload()} />}
          <Card>
            <h3 className="mb-3 text-[13px] font-semibold">About this posting</h3>
            <dl className="space-y-2 text-[13px]">
              <Row label="Source">{job.source_label}</Row>
              {job.also_seen_on.length > 0 && (
                <Row label="Also listed on">
                  {job.also_seen_on.map((item) =>
                    item.url ? (
                      <a key={item.url} href={item.url} target="_blank" rel="noreferrer" className="block text-accent hover:underline">{item.label}</a>
                    ) : (
                      <span key={item.label} className="block">{item.label}</span>
                    ),
                  )}
                </Row>
              )}
              <Row label="Posted">{job.posted_at ? fullDate(job.posted_at) : "Not listed"}</Row>
              <Row label="Found">{fullDate(job.discovered_at)}</Row>
              {job.expires_at && <Row label="Closes">{fullDate(job.expires_at)}</Row>}
              {job.last_verified_at && <Row label="Last checked">{fullDate(job.last_verified_at)}</Row>}
              {job.level_reason && <Row label="Level">{job.level_reason}</Row>}
            </dl>
          </Card>
          {job.relevance_reasons && job.relevance_reasons.length > 0 && (
            <Card>
              <h3 className="mb-2 text-[13px] font-semibold">Why it is a match</h3>
              <ul className="space-y-1 text-[13px] text-muted">
                {job.relevance_reasons.map((reason) => (
                  <li key={reason} className="flex items-start gap-1.5">
                    <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-success" /> {reason}
                  </li>
                ))}
              </ul>
            </Card>
          )}
          {versions && versions.length > 0 && (
            <Card>
              <h3 className="mb-2 text-[13px] font-semibold">Tailored resumes for this job</h3>
              <div className="space-y-1">
                {versions.map((version) => (
                  <Link key={version.id} href={`/resume/versions/${version.id}`} className="flex items-center justify-between rounded-md px-2 py-1.5 text-[13px] hover:bg-surface2">
                    <span>{fullDate(version.created_at)}</span>
                    <span className="text-[12px] text-muted">{version.change_count} changes</span>
                  </Link>
                ))}
              </div>
            </Card>
          )}
        </aside>
      </div>
    </div>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <dt className="text-[11.5px] uppercase tracking-wide text-faint">{label}</dt>
      <dd className="mt-0.5">{children}</dd>
    </div>
  );
}
