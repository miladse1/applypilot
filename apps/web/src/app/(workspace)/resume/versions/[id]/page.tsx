"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useMemo, useState } from "react";
import { ArrowLeft, ArrowUpDown, BadgeCheck, Bold, Download, Eye, EyeOff, LayoutList, MessageSquare, PenLine, Plus, RefreshCw, RotateCcw, Send, ShieldAlert, Sparkles } from "lucide-react";
import { PdfFrame } from "@/components/pdf-frame";
import { ResumeChat } from "@/components/resume-chat";
import { Badge, Button, Card, CardHeader, LinkButton, LoadingBlock, Notice, Tabs, Textarea, useToast } from "@/components/ui";
import { api } from "@/lib/api";
import { fullDate, stripMarkup } from "@/lib/format";
import { errorMessage, useApi } from "@/lib/hooks";
import type { Change, ResumeDocument, ResumeVersion } from "@/lib/types";

const KIND_LABEL: Record<string, { label: string; icon: typeof Sparkles }> = {
  select_projects: { label: "Projects chosen for this job", icon: LayoutList },
  rewrite: { label: "Reworded", icon: Sparkles },
  summary: { label: "Summary rewritten", icon: Sparkles },
  reorder_bullets: { label: "Bullets reordered", icon: ArrowUpDown },
  reorder_entries: { label: "Projects reordered", icon: ArrowUpDown },
  reorder_skills: { label: "Skills reordered", icon: ArrowUpDown },
  reorder_tech: { label: "Tools reordered", icon: ArrowUpDown },
  emphasis: { label: "Highlighted", icon: Bold },
  add_skill: { label: "Skill added", icon: Plus },
  hide_bullet: { label: "Bullet hidden", icon: EyeOff },
  chat: { label: "Changed in chat", icon: MessageSquare },
};

function findText(document: ResumeDocument | undefined, id: string | undefined) {
  if (!document || !id) return undefined;
  for (const section of document.sections) {
    for (const paragraph of section.paragraphs || []) if (paragraph.id === id) return paragraph;
    for (const entry of section.entries || []) for (const bullet of entry.bullets) if (bullet.id === id) return bullet;
  }
  return undefined;
}

function Highlighted({ text }: { text: string }) {
  const parts = text.split(/(\*\*.+?\*\*)/g);
  return (
    <>
      {parts.map((part, index) =>
        part.startsWith("**") && part.endsWith("**") ? (
          <strong key={index} className="font-semibold">{part.slice(2, -2)}</strong>
        ) : (
          <span key={index}>{part}</span>
        ),
      )}
    </>
  );
}

export default function VersionPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const toast = useToast();
  const { data: version, setData, error } = useApi<ResumeVersion>(`/resume-versions/${params.id}`);
  const [view, setView] = useState("side");
  const [editing, setEditing] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState("");
  const [stamp, setStamp] = useState(0);

  const content = version?.content;
  const changes = useMemo(() => content?.changes || [], [content]);

  if (!version || !content) return error ? <Notice tone="bad">{error}</Notice> : <LoadingBlock label="Loading resume" />;
  if (content.format !== "document") {
    return (
      <div>
        <Notice tone="warn" title="This version uses the older format">
          It was generated before ApplyPilot kept your original layout. Regenerate it to get a version built from your own resume.
        </Notice>
        <div className="mt-4 flex gap-2">
          <LinkButton href={`/api/v1/resume-versions/${version.id}/download?format=pdf`} external>Download PDF</LinkButton>
          {version.job_posting_id && <Button onClick={regenerate} title="Asks Claude for a new draft (about $0.02 of API credit)">Regenerate</Button>}
        </div>
      </div>
    );
  }

  async function edit(body: Record<string, unknown>, message: string) {
    setBusy("edit");
    try {
      const updated = await api<ResumeVersion>(`/resume-versions/${params.id}`, { method: "PATCH", body: JSON.stringify(body) });
      setData(updated);
      setStamp(Date.now());
      setEditing(null);
      toast(updated.warnings?.length ? updated.warnings.join(" ") : message, updated.warnings?.length ? "warn" : "good");
    } catch (err) {
      toast(errorMessage(err), "bad");
    } finally {
      setBusy("");
    }
  }

  async function regenerate() {
    setBusy("regen");
    try {
      const next = await api<ResumeVersion>(`/resume-versions/${params.id}/regenerate`, { method: "POST" });
      router.push(`/resume/versions/${next.id}`);
    } catch (err) {
      toast(errorMessage(err), "bad");
      setBusy("");
    }
  }

  async function approve() {
    setBusy("approve");
    try {
      setData(await api<ResumeVersion>(`/resume-versions/${params.id}/approve`, { method: "POST" }));
      toast("Approved. ApplyPilot uses this exact version for this job; any later edit asks you to approve again.", "good");
    } catch (err) {
      toast(errorMessage(err), "bad");
    } finally {
      setBusy("");
    }
  }

  async function prepare() {
    if (!version?.job_posting_id) return;
    setBusy("prepare");
    try {
      const created = await api<{ id: string }>("/applications", { method: "POST", body: JSON.stringify({ job_id: version.job_posting_id }) });
      router.push(`/applications/${created.id}`);
    } catch (err) {
      toast(errorMessage(err), "bad");
      setBusy("");
    }
  }

  const pdf = `/api/v1/resume-versions/${version.id}/download?format=pdf&inline=true&t=${stamp}`;
  const original = content.source_resume_id ? `/api/v1/resumes/${content.source_resume_id}/preview` : null;
  const rejected = (content.generation?.rejected || []) as Change[];

  return (
    <div>
      <Link href={content.job ? `/jobs/${content.job.id}` : "/resume"} className="mb-4 inline-flex items-center gap-1 text-[13px] text-muted hover:text-ink">
        <ArrowLeft className="h-4 w-4" /> {content.job ? "Back to job" : "Resume"}
      </Link>
      <header className="mb-5 flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="text-[13px] text-muted">Tailored resume · {fullDate(version.created_at)}</div>
          <h1 className="text-[22px] font-semibold tracking-tight">{content.job ? `${content.job.title}, ${content.job.company}` : version.title}</h1>
          <div className="mt-2 flex flex-wrap gap-1.5">
            <Badge tone={content.generation?.method === "ai" ? "accent" : "neutral"}>{content.generation?.method === "ai" ? "Rewritten by Claude, fact-checked" : "Reordered and highlighted"}</Badge>
            <Badge tone={content.origin === "original" ? "good" : "warn"}>{content.origin === "original" ? "Built from your original layout" : "Built from your profile"}</Badge>
            {version.kind === "tailored" && (version.approved_by_user ? <Badge tone="good" icon={<BadgeCheck className="h-3.5 w-3.5" />}>Approved by you</Badge> : <Badge tone="warn">Not approved yet</Badge>)}
            {content.fit && <Badge tone={content.fit.fits ? "good" : "warn"}>{content.fit.fits ? `Fits ${content.fit.pages} page${content.fit.pages === 1 ? "" : "s"}` : `${content.fit.pages} pages (original: ${content.fit.target_pages})`}</Badge>}
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          <LinkButton href={`/api/v1/resume-versions/${version.id}/download?format=pdf`} external icon={<Download className="h-4 w-4" />}>PDF</LinkButton>
          <LinkButton href={`/api/v1/resume-versions/${version.id}/download?format=docx`} external icon={<Download className="h-4 w-4" />}>DOCX</LinkButton>
          {version.job_posting_id && (
            <>
              <Button variant="secondary" icon={<RefreshCw className="h-4 w-4" />} loading={busy === "regen"} onClick={regenerate} title="Asks Claude for a new draft (about $0.02 of API credit)">Regenerate</Button>
              {!version.approved_by_user && <Button variant="secondary" icon={<BadgeCheck className="h-4 w-4" />} loading={busy === "approve"} onClick={approve} title="You checked this version; ApplyPilot may upload it">Approve resume</Button>}
              <Button icon={<Send className="h-4 w-4" />} loading={busy === "prepare"} onClick={prepare}>Use in an application</Button>
            </>
          )}
        </div>
      </header>
      {content.generation?.note && <Notice tone={content.generation.method === "ai" ? "accent" : "neutral"} className="mb-4">{content.generation.note}</Notice>}

      <div className="grid gap-6 xl:grid-cols-[1fr_380px]">
        <Card padded={false} className="overflow-hidden">
          <div className="flex items-center justify-between border-b border-line px-4 pt-2">
            <Tabs
              items={[
                { value: "side", label: "Side by side" },
                { value: "tailored", label: "Tailored" },
                { value: "original", label: "Original" },
              ]}
              value={view}
              onChange={setView}
              className="border-b-0"
            />
          </div>
          <div className={view === "side" ? "grid gap-px bg-line md:grid-cols-2" : ""}>
            {(view === "side" || view === "original") && (
              <div className="bg-surface">
                {view === "side" && <div className="px-3 py-1.5 text-[12px] font-medium text-muted">Original</div>}
                {original ? <PdfFrame src={original} title="Original resume" className="h-[860px]" /> : <div className="p-6 text-[13px] text-muted">The original file is not available.</div>}
              </div>
            )}
            {(view === "side" || view === "tailored") && (
              <div className="bg-surface">
                {view === "side" && <div className="px-3 py-1.5 text-[12px] font-medium text-accent">Tailored for this job</div>}
                <PdfFrame key={stamp} src={pdf} title="Tailored resume" className="h-[860px]" />
              </div>
            )}
          </div>
        </Card>

        <div className="space-y-4">
          {version.kind === "tailored" && (
            <ResumeChat
              version={version}
              onUpdated={(next, changed) => {
                setData(next);
                if (changed) setStamp(Date.now());
              }}
            />
          )}
          {content.keywords && (
            <Card>
              <h3 className="mb-2 text-[13px] font-semibold">Job keywords</h3>
              <div className="flex flex-wrap gap-1">
                {content.keywords.covered.map((item) => (
                  <span key={item} className="rounded bg-success-soft px-1.5 py-0.5 text-[12px] text-success">{item}</span>
                ))}
                {content.keywords.missing.map((item) => (
                  <span key={item} className="rounded bg-surface2 px-1.5 py-0.5 text-[12px] text-muted line-through decoration-faint">{item}</span>
                ))}
              </div>
              {content.keywords.missing.length > 0 && (
                <p className="mt-2 text-[12px] text-muted">
                  Not covered: {content.keywords.missing.join(", ")}. If you have used any of these, answer on the{" "}
                  {content.job ? <Link className="text-accent hover:underline" href={`/jobs/${content.job.id}`}>job page</Link> : "job page"} and regenerate. ApplyPilot never adds skills you have not confirmed.
                </p>
              )}
            </Card>
          )}

          <Card>
            <CardHeader title={`What changed (${changes.length})`} description="Everything comes from your resume or answers you gave." />
            {changes.length === 0 && <p className="text-[13px] text-muted">No changes were needed for this job.</p>}
            <div className="space-y-3">
              {changes.map((change: Change) => {
                const meta = KIND_LABEL[change.kind] || { label: change.kind, icon: PenLine };
                const Icon = meta.icon;
                const targetId = change.bullet_id || change.paragraph_id;
                const current = findText(content.document, targetId);
                const hidden = Boolean(current && "hidden" in current && current.hidden);
                return (
                  <div key={change.id} className="rounded-lg border border-line p-3 text-[13px]">
                    <div className="mb-1 flex items-center justify-between gap-2">
                      <span className="inline-flex items-center gap-1.5 font-medium">
                        <Icon className="h-3.5 w-3.5 text-accent" /> {meta.label}
                        {change.entry && <span className="font-normal text-muted">· {stripMarkup(change.entry)}</span>}
                        {change.group && <span className="font-normal text-muted">· {change.group}</span>}
                      </span>
                    </div>
                    {change.kind === "add_skill" && <div><Badge tone="good">{change.skill}</Badge></div>}
                    {(change.kind === "rewrite" || change.kind === "summary" || change.kind === "emphasis") && typeof change.before === "string" && (
                      <div className="space-y-1.5">
                        {change.kind !== "emphasis" && <div className="rounded bg-danger-soft/60 px-2 py-1 text-ink/70 line-through decoration-danger/40">{stripMarkup(change.before)}</div>}
                        {editing === targetId ? (
                          <div className="space-y-2">
                            <Textarea value={draft} onChange={(event) => setDraft(event.target.value)} className="min-h-24" hint="Wrap tools in **double asterisks** to bold them." />
                            <div className="flex justify-end gap-2">
                              <Button size="sm" variant="ghost" onClick={() => setEditing(null)}>Cancel</Button>
                              <Button size="sm" loading={busy === "edit"} onClick={() => edit({ text: { [targetId!]: draft } }, "Saved your edit.")}>Save</Button>
                            </div>
                          </div>
                        ) : (
                          <div className="rounded bg-success-soft/60 px-2 py-1"><Highlighted text={current?.text || String(change.after || "")} /></div>
                        )}
                      </div>
                    )}
                    {change.kind === "reorder_skills" && Array.isArray(change.after) && <div className="text-muted">{(change.after as string[]).join(", ")}</div>}
                    {change.kind === "reorder_entries" && change.names && <div className="text-muted">{change.names.join(" → ")}</div>}
                    {change.kind === "select_projects" && change.names && (
                      <div className="flex flex-wrap gap-1">
                        {change.names.map((name) => <Badge key={name} tone={change.added?.includes(name) ? "good" : "neutral"}>{name}{change.added?.includes(name) ? " · from profile" : ""}</Badge>)}
                      </div>
                    )}
                    {change.kind === "hide_bullet" && typeof change.before === "string" && <div className="text-muted">{stripMarkup(change.before)}</div>}
                    <p className="mt-1.5 text-[12px] text-muted">{change.reason}</p>
                    {targetId && change.kind !== "add_skill" && (
                      <div className="mt-2 flex gap-1.5">
                        {(change.kind === "rewrite" || change.kind === "summary" || change.kind === "emphasis") && editing !== targetId && (
                          <>
                            <Button size="sm" variant="ghost" icon={<PenLine className="h-3.5 w-3.5" />} onClick={() => { setEditing(targetId); setDraft(current?.text || String(change.after || "")); }}>
                              Edit
                            </Button>
                            <Button size="sm" variant="ghost" icon={<RotateCcw className="h-3.5 w-3.5" />} onClick={() => edit({ revert: [targetId] }, "Restored your original wording.")}>
                              Use original
                            </Button>
                          </>
                        )}
                        {change.kind === "hide_bullet" && (
                          <Button size="sm" variant="ghost" icon={<Eye className="h-3.5 w-3.5" />} onClick={() => edit({ hidden: { [targetId]: !hidden } }, hidden ? "Bullet restored." : "Bullet hidden.")}>
                            {hidden ? "Restore" : "Hide again"}
                          </Button>
                        )}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </Card>

          {rejected.length > 0 && (
            <Card>
              <h3 className="mb-2 flex items-center gap-1.5 text-[13px] font-semibold">
                <ShieldAlert className="h-4 w-4 text-warn" /> Suggestions that were blocked
              </h3>
              <p className="mb-2 text-[12px] text-muted">Claude proposed these, but they added facts that are not in your resume, so your original text was kept.</p>
              <div className="space-y-2">
                {rejected.map((item) => (
                  <div key={item.id} className="rounded-lg bg-surface2 p-2.5 text-[12.5px]">
                    <div>{stripMarkup(String(item.after || ""))}</div>
                    <div className="mt-1 text-warn">{(item.problems || []).join(" ")}</div>
                  </div>
                ))}
              </div>
            </Card>
          )}
        </div>
      </div>
    </div>
  );
}
