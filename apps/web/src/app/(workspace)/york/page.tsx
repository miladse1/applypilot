"use client";

import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";
import { Bookmark, FileUp, GraduationCap, ShieldCheck, Sparkles } from "lucide-react";
import { Bookmarklet, yorkBookmarklet } from "@/components/bookmarklet";
import { Badge, Button, Card, CardHeader, Checkbox, EmptyState, LoadingBlock, Notice, PageHeader, Switch, useToast } from "@/components/ui";
import { api } from "@/lib/api";
import { errorMessage, useApi } from "@/lib/hooks";

type YorkPosting = {
  id: string;
  posting_id: string;
  title: string;
  company: string;
  location: string | null;
  deadline: string | null;
  days_left: number | null;
  tier: "apply_first" | "worth_applying" | "stretch" | "needs_details" | "other" | "closed";
  score: number;
  qualification: number | null;
  has_details: boolean;
  submit_on: Array<"york" | "employer">;
  employer_url: string | null;
  documents: string | null;
  reasons: string[];
  application_id: string | null;
};

type YorkData = { postings: YorkPosting[]; counts: Record<string, number>; total: number; ai_permission: boolean };

const TIERS: Array<{ key: YorkPosting["tier"]; title: string; note: string; tone: "good" | "accent" | "warn" | "neutral" }> = [
  { key: "apply_first", title: "Apply first", note: "Strong match with your skills and projects, no missing requirements.", tone: "good" },
  { key: "worth_applying", title: "Worth applying", note: "Good overlap; a requirement or two may need your answer.", tone: "accent" },
  { key: "stretch", title: "Stretch", note: "Some fit, but several requirements are not on your profile.", tone: "warn" },
  { key: "needs_details", title: "Needs details", note: "Only the list entry is saved. Open it on Experience York and click the bookmark to compare it.", tone: "neutral" },
  { key: "other", title: "Outside your search", note: "Not software, data, or AI/ML roles.", tone: "neutral" },
  { key: "closed", title: "Deadline passed", note: "", tone: "neutral" },
];

export default function YorkPage() {
  const toast = useToast();
  const { data, setData, reload, error } = useApi<YorkData>("/jobs/york");
  const [selected, setSelected] = useState<string[]>([]);
  const [busy, setBusy] = useState("");
  const [origin, setOrigin] = useState("");
  const [dragging, setDragging] = useState(false);
  const input = useRef<HTMLInputElement>(null);

  useEffect(() => setOrigin(window.location.origin), []);
  const grouped = useMemo(() => TIERS.map((tier) => ({ ...tier, items: (data?.postings || []).filter((item) => item.tier === tier.key) })).filter((tier) => tier.items.length), [data]);

  async function upload(files: FileList | File[]) {
    const list = [...files];
    if (!list.length) return;
    setBusy("files");
    const form = new FormData();
    list.forEach((file) => form.append("files", file));
    try {
      const result = await api<{ saved: number; results: Array<{ file: string; kind: string; message: string }> }>("/jobs/york/files", { method: "POST", body: form });
      const unread = result.results.filter((item) => item.kind === "unknown" || item.kind === "error");
      toast(`Imported ${result.saved} posting${result.saved === 1 ? "" : "s"} from ${list.length} file${list.length === 1 ? "" : "s"}.` + (unread.length ? ` ${unread.length} file(s) were not York postings.` : ""), unread.length ? "warn" : "good");
      reload();
    } catch (err) {
      toast(errorMessage(err), "bad");
    } finally {
      setBusy("");
    }
  }

  async function prepare() {
    setBusy("prepare");
    try {
      const result = await api<{ results: Array<{ ok: boolean; error?: string }> }>("/applications/batch", { method: "POST", body: JSON.stringify({ job_ids: selected, include_cover_letter: true }) });
      const ok = result.results.filter((item) => item.ok).length;
      toast(`Prepared ${ok} application${ok === 1 ? "" : "s"} with a tailored resume and cover letter. Review each before you submit.`, ok ? "good" : "warn");
      setSelected([]);
      reload();
    } catch (err) {
      toast(errorMessage(err), "bad");
    } finally {
      setBusy("");
    }
  }

  async function setPermission(value: boolean) {
    try {
      const result = await api<{ ai_permission: boolean }>("/jobs/york/settings", { method: "PUT", body: JSON.stringify({ ai_permission: value }) });
      if (data) setData({ ...data, ai_permission: result.ai_permission });
    } catch (err) {
      toast(errorMessage(err), "bad");
    }
  }

  return (
    <div>
      <PageHeader
        title="York co-op"
        description="Your Experience York postings, ranked against your profile and projects. Add them from your usual browser; ApplyPilot reads them on this computer."
      />
      {error && <Notice tone="bad" className="mb-4">{error}</Notice>}

      <Notice tone="neutral" className="mb-5" title={<span className="inline-flex items-center gap-1.5"><ShieldCheck className="h-4 w-4" /> Private by design</span>}>
        York&rsquo;s co-op terms say postings are only for students in the program and must not be shared. ApplyPilot keeps them on this computer, never mixes them with public job listings, and does not send them to Claude.
        Ranking, project choice, resume tailoring, and cover letters for these jobs are done here without AI. Experience York blocks software-controlled browsers, so ApplyPilot never opens it itself.
      </Notice>

      <div className="mb-6 grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader title={<span className="inline-flex items-center gap-1.5"><Bookmark className="h-4 w-4 text-accent" /> Save from Experience York</span>} description="One click per page, in the browser where you already sign in to York." />
          <ol className="list-decimal space-y-1.5 pl-5 text-[13px]">
            <li>
              Drag this to your bookmarks bar:{" "}
              {origin && (
                <Bookmarklet code={yorkBookmarklet(origin)} className="mx-1 inline-block cursor-grab rounded-md bg-accent px-2 py-0.5 font-medium text-accent-ink">
                  Save to ApplyPilot
                </Bookmarklet>
              )}
            </li>
            <li>Open Experience York, go to Co-op &amp; Internship Jobs, and open <strong>All Winter 2027 Co-op Jobs</strong>. Show as many postings per page as York allows.</li>
            <li>Click the bookmark. Every posting on that page is saved (title, employer, deadline). Repeat for each page of the list.</li>
            <li>Open the postings ranked highest below and click the bookmark on each, so ApplyPilot can read the requirements and instructions.</li>
          </ol>
          <p className="mt-2 text-[12px] text-muted">The bookmark only copies the page you are looking at, like copy and paste. It sends nothing to York and nothing leaves your computer.</p>
        </Card>
        <Card>
          <CardHeader title={<span className="inline-flex items-center gap-1.5"><FileUp className="h-4 w-4 text-accent" /> Or import saved pages</span>} description="Save postings or lists from York with File › Save Page As (HTML) or Print › Save as PDF, then add them all at once." />
          <div
            onDragOver={(event) => { event.preventDefault(); setDragging(true); }}
            onDragLeave={() => setDragging(false)}
            onDrop={(event) => { event.preventDefault(); setDragging(false); upload(event.dataTransfer.files); }}
            className={`flex flex-col items-center justify-center gap-2 rounded-lg border border-dashed p-6 text-center text-[13px] ${dragging ? "border-accent bg-accent-soft" : "border-line"}`}
          >
            <span className="text-muted">Drop .html, .pdf, or .txt files here</span>
            <input ref={input} type="file" multiple accept=".html,.htm,.pdf,.txt" className="hidden" onChange={(event) => event.target.files && upload(event.target.files)} />
            <Button size="sm" variant="secondary" loading={busy === "files"} onClick={() => input.current?.click()}>Choose files</Button>
          </div>
        </Card>
      </div>

      {!data ? (
        <LoadingBlock label="Loading York postings" />
      ) : data.total === 0 ? (
        <EmptyState icon={<GraduationCap className="h-5 w-5" />} title="No York postings yet">
          Use the bookmark on your Winter 2027 list, or import saved pages, and they appear here ranked for you.
        </EmptyState>
      ) : (
        <div className="space-y-6">
          <div className="sticky top-0 z-10 flex flex-wrap items-center justify-between gap-3 rounded-lg border border-line bg-surface p-3">
            <span className="text-[13px] text-muted">
              {data.total} saved · {data.counts.apply_first || 0} to apply first · {data.counts.needs_details || 0} need details · {selected.length} selected
            </span>
            <Button size="sm" icon={<Sparkles className="h-3.5 w-3.5" />} disabled={!selected.length} loading={busy === "prepare"} onClick={prepare}>
              Tailor resume and cover letter for {selected.length || "selected"}
            </Button>
          </div>
          {grouped.map((tier) => (
            <section key={tier.key}>
              <div className="mb-2 flex items-baseline gap-2">
                <h2 className="text-[15px] font-semibold">{tier.title}</h2>
                <span className="text-[12px] text-muted">{tier.items.length} · {tier.note}</span>
              </div>
              <div className="space-y-2">
                {tier.items.map((item) => (
                  <Card key={item.id} padded={false} className="p-3">
                    <div className="flex items-start gap-3">
                      <div className="pt-0.5">
                        <Checkbox
                          checked={selected.includes(item.id)}
                          onChange={(value) => setSelected(value ? [...selected, item.id] : selected.filter((id) => id !== item.id))}
                          label={<span className="sr-only">Select {item.title}</span>}
                        />
                      </div>
                      <div className="min-w-0 flex-1">
                        <div className="flex flex-wrap items-center gap-2">
                          <Link href={`/jobs/${item.id}`} className="text-[14px] font-medium hover:text-accent">{item.title}</Link>
                          <span className="text-[13px] text-muted">{item.company}{item.location ? ` · ${item.location}` : ""}</span>
                          {item.qualification !== null && <Badge tone={tier.tone}>{item.qualification}% match</Badge>}
                          {item.submit_on.includes("york") && <Badge tone="warn">Submit on York</Badge>}
                          {item.submit_on.includes("employer") && <Badge tone="accent">Employer site</Badge>}
                          {item.deadline && <span className="text-[12px] text-muted">Due {item.deadline}</span>}
                        </div>
                        <ul className="mt-1 space-y-0.5 text-[12.5px] text-muted">
                          {item.reasons.map((reason) => <li key={reason}>{reason}</li>)}
                        </ul>
                      </div>
                      {item.application_id && (
                        <Link href={`/applications/${item.application_id}`} className="shrink-0 text-[12.5px] text-accent hover:underline">Application</Link>
                      )}
                    </div>
                  </Card>
                ))}
              </div>
            </section>
          ))}
        </div>
      )}

      <Card className="mt-8">
        <Switch
          checked={Boolean(data?.ai_permission)}
          onChange={setPermission}
          label="York has given me permission to use an outside AI service (Claude) with co-op postings"
          description="Off by default. Turn it on only if York's co-op office confirms it in writing. When on, York postings are treated like other jobs: Claude may rewrite your resume, write cover letters, and draft form answers for them, within your AI spending limit."
        />
      </Card>
    </div>
  );
}
