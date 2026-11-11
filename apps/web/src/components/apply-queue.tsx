"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { AlertTriangle, CheckCircle2, CircleDashed, ExternalLink, Eye, FileText, Hand, Loader2, MonitorUp, RotateCcw, Send, ShieldCheck, Sparkles, X } from "lucide-react";
import { Badge, Button, Card, CardHeader, Checkbox, Input, Modal, Notice, Select, Textarea, useToast } from "@/components/ui";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/hooks";
import type { ApplyQuestion, ApplyRun, AutoApplySupport } from "@/lib/types";

const PLATFORM: Record<string, string> = { workday: "Workday", greenhouse: "Greenhouse", lever: "Lever", ashby: "Ashby", generic: "Employer site" };

const STATUS: Record<ApplyRun["status"], { label: string; tone: "neutral" | "accent" | "good" | "warn" | "bad" }> = {
  queued: { label: "Waiting", tone: "neutral" },
  running: { label: "Filling in", tone: "accent" },
  needs_you: { label: "Needs you", tone: "warn" },
  submitted: { label: "Submitted", tone: "good" },
  failed: { label: "Failed", tone: "bad" },
  cancelled: { label: "Cancelled", tone: "neutral" },
  handed_off: { label: "You're finishing it", tone: "neutral" },
  interrupted: { label: "Stopped", tone: "warn" },
};

const ATTENTION: Record<string, string> = {
  login: "Sign in needed",
  captcha: "CAPTCHA",
  verification: "Verification",
  questions: "Questions",
  review_answers: "Check Claude's answers",
  review: "Final review",
  blocked: "Site blocked automation",
  unconfirmed: "Not confirmed",
  error: "Check the page",
};

export function supportBadge(support?: AutoApplySupport) {
  if (!support) return null;
  if (support.level === "full") return <Badge tone="good">Automatic</Badge>;
  if (support.level === "assisted") return <Badge tone="accent">{support.platform === "workday" ? "Sign-in needed" : "Assisted"}</Badge>;
  return <Badge>Not supported</Badge>;
}

export function StartApplyModal({ open, onClose, rows, onStarted }: { open: boolean; onClose: () => void; rows: Array<{ id: string; title: string | null; company: string | null; autoapply?: AutoApplySupport }>; onStarted: () => void }) {
  const toast = useToast();
  const [busy, setBusy] = useState<"auto" | "review" | null>(null);
  const usable = rows.filter((row) => row.autoapply?.level !== "none");
  const needsSignIn = usable.some((row) => row.autoapply?.platform === "workday" || row.autoapply?.level === "assisted");
  const [account, setAccount] = useState<{ email: string; has_password: boolean; sign_in: boolean; create_accounts: boolean } | null>(null);
  const [prefs, setPrefs] = useState<Record<string, string> | null>(null);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [createAccounts, setCreateAccounts] = useState(true);
  const [decline, setDecline] = useState(false);
  const [consent, setConsent] = useState(false);

  useEffect(() => {
    if (!open) return;
    api<{ email: string; has_password: boolean; sign_in: boolean; create_accounts: boolean }>("/apply/account").then((data) => { setAccount(data); setEmail(data.email); setCreateAccounts(data.create_accounts || !data.has_password); }).catch(() => undefined);
    api<{ preferences: Array<{ key: string; value: string }> }>("/apply/answers").then((data) => setPrefs(Object.fromEntries(data.preferences.map((item) => [item.key, item.value])))).catch(() => undefined);
  }, [open]);

  async function start(mode: "auto" | "review") {
    setBusy(mode);
    try {
      if (password) {
        await api("/apply/account", { method: "PUT", body: JSON.stringify({ email, password, sign_in: true, create_accounts: createAccounts }) });
      }
      const choices: Record<string, string> = {};
      if (decline) choices.voluntary_disclosures = "decline";
      if (consent) choices.consent_privacy = "yes";
      if (Object.keys(choices).length) await api("/apply/answers", { method: "PUT", body: JSON.stringify({ values: choices }) });
      const result = await api<{ created: string[]; skipped: Array<{ title: string; reason: string }> }>("/apply/runs", {
        method: "POST",
        body: JSON.stringify({ application_ids: usable.map((row) => row.id), submit_mode: mode }),
      });
      if (result.created.length) toast(`ApplyPilot is working on ${result.created.length} application${result.created.length === 1 ? "" : "s"}. A Chrome window will open.`, "good");
      result.skipped.forEach((item) => toast(`${item.title}: ${item.reason}`, "bad"));
      onStarted();
      onClose();
    } catch (err) {
      toast(errorMessage(err), "bad");
    } finally {
      setBusy(null);
    }
  }

  return (
    <Modal
      open={open}
      onClose={onClose}
      wide
      title={`Apply to ${usable.length} job${usable.length === 1 ? "" : "s"} with ApplyPilot`}
      description="ApplyPilot opens each application in its own Chrome window, signs in, fills in every page, and stops for your final check before submitting (unless you choose to submit directly)."
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>Cancel</Button>
          <Button variant="secondary" icon={<Send className="h-4 w-4" />} disabled={!usable.length} loading={busy === "auto"} onClick={() => start("auto")}>Submit when nothing needs checking</Button>
          <Button icon={<Eye className="h-4 w-4" />} disabled={!usable.length} loading={busy === "review"} onClick={() => start("review")}>Fill in, then let me review</Button>
        </>
      }
    >
      <div className="space-y-3 text-[13px]">
        <div className="divide-y divide-line rounded-lg border border-line">
          {rows.map((row) => (
            <div key={row.id} className="flex items-start justify-between gap-3 px-3 py-2">
              <div className="min-w-0">
                <div className="truncate font-medium">{row.title}</div>
                <div className="text-[12px] text-muted">{row.company} · {row.autoapply?.note}</div>
              </div>
              {supportBadge(row.autoapply)}
            </div>
          ))}
        </div>
        {needsSignIn && account && !account.has_password && (
          <div className="rounded-lg border border-line p-3">
            <div className="mb-2 font-medium">Let ApplyPilot sign in for you</div>
            <div className="grid gap-2 sm:grid-cols-2">
              <Input label="Email you use on job sites" type="email" value={email} onChange={(event) => setEmail(event.target.value)} />
              <Input label="Job-site password" type="password" autoComplete="new-password" value={password} onChange={(event) => setPassword(event.target.value)} hint="Kept in your Mac's Keychain. Never sent to Claude." />
            </div>
            <div className="mt-2"><Checkbox checked={createAccounts} onChange={setCreateAccounts} label="Create an account with this email and password when a site needs one (accepts that site's account terms)" /></div>
            <p className="mt-1 text-[12px] text-muted">Leave the password empty to sign in yourself when asked. New accounts may still need you to click a link in a verification email.</p>
          </div>
        )}
        {prefs && (prefs.voluntary_disclosures !== "decline" || prefs.consent_privacy !== "yes") && (
          <div className="space-y-1.5 rounded-lg border border-line p-3">
            <div className="font-medium">So ApplyPilot doesn't stop to ask (optional)</div>
            {prefs.voluntary_disclosures !== "decline" && <Checkbox checked={decline} onChange={setDecline} label="Answer “I don't wish to answer” to voluntary questions (gender, ethnicity, veteran, disability)" />}
            {prefs.consent_privacy !== "yes" && <Checkbox checked={consent} onChange={setConsent} label="Accept an employer's candidate privacy notice when a form requires it" />}
            <p className="text-[12px] text-muted">Saved in Settings → Application autofill, where you can change them.</p>
          </div>
        )}
        <ul className="list-disc space-y-1 pl-5 text-muted">
          <li>It pauses when a site needs your sign-in, a CAPTCHA, a verification code, or an answer it doesn't know. It never tries to get around these.</li>
          <li>Claude answers the questions on each form from your resume, projects, profile, saved answers, and the job posting, and moves on to the next page by itself. Answers based on an assumption (like availability) are marked for you at the final review.</li>
          <li>Only facts nobody can infer (home address, date of birth, ID numbers, references) are asked, once, and remembered.</li>
          <li>The resume attached is the approved version tailored for that job. A cover letter is written only if the form requires one.</li>
          <li>An application counts as submitted only when the employer's confirmation page appears. Otherwise ApplyPilot asks you to check.</li>
        </ul>
      </div>
    </Modal>
  );
}

const SOURCE: Record<string, { label: string; tone: "neutral" | "accent" | "good" | "warn" }> = {
  profile: { label: "Profile", tone: "neutral" },
  saved: { label: "Saved answer", tone: "neutral" },
  your_answer: { label: "Your answer", tone: "good" },
  approved_answers: { label: "Approved answer", tone: "neutral" },
  approved_document: { label: "Approved document", tone: "good" },
  policy: { label: "Your setting", tone: "neutral" },
  claude: { label: "Drafted by Claude", tone: "accent" },
};

function AnswerInput({ question, value, onChange }: { question: ApplyQuestion; value: string; onChange: (value: string) => void }) {
  const hint = question.status === "drafted" ? undefined : question.remember ? "Remembered for future applications." : undefined;
  if (question.kind === "file") return <Notice tone="warn" title={question.label}>{question.problems?.[0]}</Notice>;
  if (question.kind === "checkbox_group") {
    const chosen = value.split("|").map((part) => part.trim()).filter(Boolean);
    return (
      <div>
        <div className="mb-1 text-[12.5px] font-medium">{question.label}</div>
        <div className="flex flex-wrap gap-x-4 gap-y-1">
          {question.options.map((option) => (
            <Checkbox key={option} label={option} checked={chosen.includes(option)} onChange={(on) => onChange((on ? [...chosen, option] : chosen.filter((item) => item !== option)).join(" | "))} />
          ))}
        </div>
      </div>
    );
  }
  if (question.options.length)
    return <Select label={question.label} value={value} onChange={(event) => onChange(event.target.value)} options={[{ value: "", label: "Choose…" }, ...question.options.map((option) => ({ value: option, label: option }))]} hint={hint} />;
  if (question.kind === "textarea" || value.length > 90) return <Textarea label={question.label} value={value} onChange={(event) => onChange(event.target.value)} hint={hint || "Used for this application. If you change it, ApplyPilot learns from your version."} />;
  return <Input label={question.label} value={value} onChange={(event) => onChange(event.target.value)} hint={hint} />;
}

function QuestionsForm({ run, onDone }: { run: ApplyRun; onDone: () => void }) {
  const toast = useToast();
  const [values, setValues] = useState<Record<string, string>>(() => Object.fromEntries(run.questions.map((q) => [q.key, q.draft || ""])));
  const [busy, setBusy] = useState(false);
  const drafted = run.questions.filter((q) => q.status === "drafted");
  const needed = run.questions.filter((q) => q.status !== "drafted");
  const missing = needed.filter((q) => q.kind !== "file" && q.required !== false && !(values[q.key] || "").trim()).length;

  async function submit() {
    setBusy(true);
    try {
      await api(`/apply/runs/${run.id}/continue`, { method: "POST", body: JSON.stringify({ answers: values }) });
      onDone();
    } catch (err) {
      toast(errorMessage(err), "bad");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mt-3 space-y-4">
      {drafted.length > 0 && (
        <div className="space-y-3">
          <div className="flex items-center gap-1.5 text-[12.5px] font-semibold"><Sparkles className="h-3.5 w-3.5 text-accent" /> Drafted by Claude: already typed into the form. Edit anything that isn't right.</div>
          {drafted.map((question) => (
            <div key={question.key} className="rounded-md border border-accent/20 bg-accent-soft/30 p-2.5">
              <AnswerInput question={question} value={values[question.key] || ""} onChange={(value) => setValues({ ...values, [question.key]: value })} />
              {question.basis && <div className="mt-1 text-[11.5px] text-muted">Based on: {question.basis}</div>}
            </div>
          ))}
        </div>
      )}
      {needed.length > 0 && (
        <div className="space-y-3">
          <div className="text-[12.5px] font-semibold">Needs your answer</div>
          {needed.map((question) => (
            <div key={question.key} className="rounded-md border border-line p-2.5">
              <AnswerInput question={question} value={values[question.key] || ""} onChange={(value) => setValues({ ...values, [question.key]: value })} />
              {question.draft && question.problems && question.problems.length > 0 && (
                <div className="mt-1 text-[11.5px] text-warn">Claude's suggestion is filled in above but was not typed into the form: {question.problems.join(" ")}</div>
              )}
            </div>
          ))}
        </div>
      )}
      <div className="flex flex-wrap items-center gap-2">
        <Button size="sm" loading={busy} onClick={submit}>
          {drafted.length ? "Approve answers and continue" : "Use these answers and continue"}
        </Button>
        <span className="text-[12px] text-muted">{missing ? `${missing} still empty. You can also fill them in the browser window.` : "Nothing is submitted until the final review."}</span>
      </div>
    </div>
  );
}

function FinalReview({ run, onChange }: { run: ApplyRun; onChange: () => void }) {
  const toast = useToast();
  const [editing, setEditing] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);

  async function save(key: string) {
    setBusy(true);
    try {
      await api(`/apply/runs/${run.id}/continue`, { method: "POST", body: JSON.stringify({ answers: { [key]: draft } }) });
      toast("Updating the form with your answer. ApplyPilot will remember it.", "good");
      setEditing(null);
      onChange();
    } catch (err) {
      toast(errorMessage(err), "bad");
    } finally {
      setBusy(false);
    }
  }

  const rows = run.filled.filter((entry) => entry.source !== "approved_document");
  const assumed = rows.filter((entry) => entry.basis?.startsWith("Assumed")).length;
  return (
    <div className="mt-3 space-y-3">
      {run.documents.length > 0 && (
        <div className="space-y-1.5">
          {run.documents.map((doc) => (
            <div key={doc.slot + doc.file} className="flex flex-wrap items-center gap-2 rounded-md bg-success-soft/50 px-2.5 py-1.5 text-[12.5px]">
              <FileText className="h-3.5 w-3.5 text-success" />
              <span className="font-medium">{doc.kind === "resume" ? "Resume" : "Cover letter"}:</span> {doc.file}
              {doc.kind === "resume" && doc.version_id && (
                <Link href={`/resume/versions/${doc.version_id}`} className="text-accent underline-offset-2 hover:underline" target="_blank">
                  tailored for this job{doc.title ? ` (${doc.title})` : ""}
                </Link>
              )}
            </div>
          ))}
        </div>
      )}
      {assumed > 0 && <Notice tone="warn">{assumed} answer{assumed === 1 ? " is" : "s are"} based on an assumption (marked below). Check {assumed === 1 ? "it" : "them"} before submitting.</Notice>}
      <div className="max-h-[28rem] overflow-y-auto rounded-md border border-line">
        <table className="w-full text-[12.5px]">
          <tbody>
            {rows.map((entry, index) => (
              <tr key={entry.key || index} className="border-b border-line/60 align-top last:border-0">
                <td className="w-2/5 px-2.5 py-1.5 text-muted">{entry.label}</td>
                <td className="px-2.5 py-1.5">
                  {editing === entry.key ? (
                    <div className="space-y-1.5">
                      {entry.kind === "textarea" || draft.length > 90 ? <Textarea value={draft} onChange={(event) => setDraft(event.target.value)} className="min-h-24" /> : <Input value={draft} onChange={(event) => setDraft(event.target.value)} />}
                      <div className="flex gap-1.5">
                        <Button size="sm" loading={busy} onClick={() => save(entry.key!)}>Update the form</Button>
                        <Button size="sm" variant="ghost" onClick={() => setEditing(null)}>Cancel</Button>
                      </div>
                    </div>
                  ) : (
                    <>
                      <div className="whitespace-pre-wrap">{entry.value}</div>
                      {entry.basis && entry.source === "claude" && <div className={`mt-0.5 text-[11.5px] ${entry.basis.startsWith("Assumed") ? "text-warn" : "text-muted"}`}>{entry.basis}</div>}
                    </>
                  )}
                </td>
                <td className="px-2.5 py-1.5 text-right">
                  <div className="flex flex-col items-end gap-1">
                    <Badge tone={entry.basis?.startsWith("Assumed") ? "warn" : SOURCE[entry.source]?.tone || "neutral"}>{entry.basis?.startsWith("Assumed") ? "Assumed" : SOURCE[entry.source]?.label || entry.source}</Badge>
                    {entry.key && editing !== entry.key && !["checkbox", "checkbox_group", "file"].includes(entry.kind || "") && (
                      <button className="text-[11.5px] text-accent hover:underline" onClick={() => { setEditing(entry.key!); setDraft(entry.value); }}>Edit</button>
                    )}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="text-[12px] text-muted">On multi-page forms, answers from earlier pages can be changed in the browser window (most sites show an Edit link on their review page).</p>
    </div>
  );
}

function RunCard({ run, onChange, compact }: { run: ApplyRun; onChange: () => void; compact?: boolean }) {
  const toast = useToast();
  const [busy, setBusy] = useState<string | null>(null);
  const status = STATUS[run.status];

  async function act(action: string, body?: object, message?: string) {
    setBusy(action);
    try {
      await api(`/apply/runs/${run.id}/${action}`, { method: "POST", body: body ? JSON.stringify(body) : undefined });
      if (message) toast(message, "good");
      onChange();
    } catch (err) {
      toast(errorMessage(err), "bad");
    } finally {
      setBusy(null);
    }
  }

  const icon =
    run.status === "submitted" ? <CheckCircle2 className="h-4 w-4 text-success" /> :
    run.status === "running" ? <Loader2 className="h-4 w-4 animate-spin text-accent" /> :
    run.status === "needs_you" ? <Hand className="h-4 w-4 text-warn" /> :
    run.status === "failed" || run.status === "interrupted" ? <AlertTriangle className="h-4 w-4 text-danger" /> :
    <CircleDashed className="h-4 w-4 text-muted" />;

  return (
    <div className="rounded-lg border border-line p-3 text-[13px]">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="flex min-w-0 items-start gap-2">
          <span className="mt-0.5">{icon}</span>
          <div className="min-w-0">
            <Link href={`/applications/${run.application_id}`} className="block truncate font-medium hover:text-accent">{run.title}</Link>
            <div className="text-[12px] text-muted">
              {run.company} · {PLATFORM[run.platform] || run.platform}
              {run.filled_count > 0 && ` · ${run.filled_count} field${run.filled_count === 1 ? "" : "s"} filled`}
              {run.submit_mode === "review" && " · stops for your review"}
            </div>
          </div>
        </div>
        <div className="flex items-center gap-1.5">
          {run.attention && run.status === "needs_you" && <Badge tone="warn">{ATTENTION[run.attention] || run.attention}</Badge>}
          <Badge tone={status.tone}>{status.label}</Badge>
        </div>
      </div>
      {run.message && <p className="mt-2 text-ink/85">{run.message}</p>}
      {run.status === "submitted" && run.confirmation_text && (
        <div className="mt-2 rounded bg-success-soft/60 px-2 py-1.5 text-[12.5px]">
          <span className="font-medium">Employer's page said:</span> “{run.confirmation_text.slice(0, 220)}”
          {run.has_screenshot && (
            <a className="ml-2 inline-flex items-center gap-1 text-accent underline-offset-2 hover:underline" href={`/api/v1/apply/runs/${run.id}/screenshot`} target="_blank" rel="noreferrer">
              Screenshot <ExternalLink className="h-3 w-3" />
            </a>
          )}
        </div>
      )}
      {run.status === "needs_you" && (run.attention === "questions" || run.attention === "review_answers") && run.questions.length > 0 && <QuestionsForm key={run.updated_at} run={run} onDone={onChange} />}
      {run.status === "needs_you" && run.attention === "review" && <FinalReview run={run} onChange={onChange} />}
      {!compact && run.events.length > 0 && run.status !== "submitted" && (
        <ul className="mt-2 space-y-0.5 text-[12px] text-muted">
          {run.events.slice(-3).map((event, index) => <li key={index}>· {event.message}</li>)}
        </ul>
      )}
      <div className="mt-2 flex flex-wrap gap-1.5">
        {run.status === "needs_you" && run.tab_open && (
          <Button size="sm" variant="secondary" icon={<MonitorUp className="h-3.5 w-3.5" />} loading={busy === "show"} onClick={() => act("show")}>Show browser window</Button>
        )}
        {run.status === "needs_you" && run.attention === "review" && (
          <Button size="sm" icon={<Send className="h-3.5 w-3.5" />} loading={busy === "submit-now"} onClick={() => act("submit-now")}>Submit now</Button>
        )}
        {run.status === "needs_you" && ["login", "verification", "blocked", "error", "captcha"].includes(run.attention || "") && (
          <Button size="sm" loading={busy === "continue"} onClick={() => act("continue", { answers: {} })}>Continue</Button>
        )}
        {(run.attention === "unconfirmed" || (run.status === "interrupted" && run.submit_clicked)) && run.application_status !== "submitted" && (
          <Button size="sm" icon={<ShieldCheck className="h-3.5 w-3.5" />} loading={busy === "confirm"} onClick={() => act("confirm", { note: "I saw the confirmation (page or email)." }, "Marked as submitted.")}>It was submitted</Button>
        )}
        {(run.status === "needs_you" || run.status === "queued" || run.status === "running") && (
          <>
            {run.status === "needs_you" && <Button size="sm" variant="ghost" icon={<Hand className="h-3.5 w-3.5" />} loading={busy === "handoff"} onClick={() => act("handoff", undefined, "It's yours to finish. Mark it submitted when done.")}>I'll finish it myself</Button>}
            <Button size="sm" variant="ghost" icon={<X className="h-3.5 w-3.5" />} loading={busy === "cancel"} onClick={() => act("cancel")}>Cancel</Button>
          </>
        )}
        {["failed", "cancelled", "interrupted"].includes(run.status) && run.application_status === "approved" && (
          <Button size="sm" variant="secondary" icon={<RotateCcw className="h-3.5 w-3.5" />} loading={busy === "retry"} onClick={() => act("retry", undefined, "Started again.")}>Try again</Button>
        )}
      </div>
    </div>
  );
}

/** Live list of browser-assisted applications. Polls while anything is in progress. */
export function ApplyQueue({ applicationId, onChange }: { applicationId?: string; onChange?: () => void }) {
  const [runs, setRuns] = useState<ApplyRun[] | null>(null);
  const [showDone, setShowDone] = useState(false);

  const load = useCallback(async () => {
    try {
      const data = await api<{ runs: ApplyRun[] }>("/apply/runs?scope=recent");
      setRuns(applicationId ? data.runs.filter((run) => run.application_id === applicationId) : data.runs);
    } catch {
      setRuns((current) => current || []);
    }
  }, [applicationId]);

  const active = useMemo(() => (runs || []).filter((run) => ["queued", "running", "needs_you"].includes(run.status)), [runs]);
  const finished = useMemo(() => (runs || []).filter((run) => !["queued", "running", "needs_you"].includes(run.status)), [runs]);
  // Results from the last 30 minutes stay in view so you see how each one ended.
  const recent = useMemo(() => finished.filter((run) => run.finished_at && Date.now() - new Date(run.finished_at).getTime() < 30 * 60 * 1000), [finished]);
  const older = finished.filter((run) => !recent.includes(run));

  useEffect(() => {
    load();
  }, [load]);
  useEffect(() => {
    if (!active.length) return;
    const timer = window.setInterval(load, 2500);
    return () => window.clearInterval(timer);
  }, [active.length, load]);
  const previous = useMemo(() => active.map((run) => run.id + run.status).join(), [active]);
  // Refresh the surrounding page (application statuses) when a run changes state.
  useEffect(() => {
    onChange?.();
  }, [previous, finished.length, onChange]);

  if (!runs || (!runs.length && !applicationId)) return null;
  if (applicationId) {
    const latest = runs[0];
    return latest ? <RunCard run={latest} onChange={load} /> : null;
  }
  const waiting = active.filter((run) => run.status === "needs_you").length;
  return (
    <Card className="mb-5">
      <CardHeader
        title="ApplyPilot is applying"
        description={active.length ? `${active.length} in progress${waiting ? `, ${waiting} waiting for you` : ""}. The Chrome window shows what it is doing.` : recent.length ? "Finished recently:" : "Nothing in progress."}
        actions={older.length > 0 && <Button size="sm" variant="ghost" onClick={() => setShowDone(!showDone)}>{showDone ? "Hide earlier" : `Show earlier (${older.length})`}</Button>}
      />
      {waiting > 0 && <Notice tone="warn" className="mb-3">Applications waiting for you keep their browser tab open. ApplyPilot carries on with the others in the meantime.</Notice>}
      <div className="space-y-2">
        {active.map((run) => <RunCard key={run.id} run={run} onChange={load} />)}
        {recent.map((run) => <RunCard key={run.id} run={run} onChange={load} compact />)}
        {showDone && older.map((run) => <RunCard key={run.id} run={run} onChange={load} compact />)}
      </div>
    </Card>
  );
}
