"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { ArrowLeft, Check, CheckCircle2, ClipboardCopy, Download, ExternalLink, FileText, RefreshCw, Send, ShieldCheck, Sparkles } from "lucide-react";
import { ApplyQueue, StartApplyModal, supportBadge } from "@/components/apply-queue";
import { PdfFrame } from "@/components/pdf-frame";
import { QuestionList } from "@/components/questions";
import { Badge, Button, Card, CardHeader, Checkbox, Input, LinkButton, LoadingBlock, Modal, Notice, Select, Textarea, useToast } from "@/components/ui";
import { api } from "@/lib/api";
import { fullDate } from "@/lib/format";
import { errorMessage, useApi } from "@/lib/hooks";
import { applicationStatusLabel, STAGE_TONE } from "@/lib/labels";
import type { Answer, Application, Health, Profile } from "@/lib/types";
import { cn } from "@/lib/utils";

type History = { events: Array<{ from: string | null; to: string; note: string; at: string }>; attempts: Array<{ method: string; status: string; is_live: boolean; confirmation_id: string | null; error: string | null }> };

const TONES = [
  { value: "professional", label: "Professional" },
  { value: "internship-focused", label: "Student / co-op" },
  { value: "entry-level", label: "New graduate" },
  { value: "enthusiastic", label: "Enthusiastic" },
  { value: "concise", label: "Concise" },
];

function copy(text: string, toast: (message: string, tone?: "good") => void, label = "Copied") {
  navigator.clipboard?.writeText(text).then(() => toast(label, "good"));
}

export default function ApplicationPage() {
  const params = useParams<{ id: string }>();
  const toast = useToast();
  const { data: app, setData: setApp, reload, error } = useApi<Application>(`/applications/${params.id}`);
  const { data: profile } = useApi<Profile>("/profile");
  const { data: health } = useApi<Health>("/health");
  const { data: history, reload: reloadHistory } = useApi<History>(`/applications/${params.id}/history`);
  const [letter, setLetter] = useState("");
  const [tone, setTone] = useState("professional");
  const [answers, setAnswers] = useState<Answer[]>([]);
  const [busy, setBusy] = useState("");
  const [ackUnverified, setAckUnverified] = useState(false);
  const [ackGaps, setAckGaps] = useState(false);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [confirmNote, setConfirmNote] = useState("Submitted on the employer's site.");
  const [autoApply, setAutoApply] = useState(false);
  const [interviewAt, setInterviewAt] = useState("");

  useEffect(() => {
    if (app) {
      setLetter(app.cover_letter || "");
      setAnswers(app.answers || []);
      if (app.cover_letter_tone) setTone(app.cover_letter_tone);
    }
  }, [app]);

  if (!app) return error ? <Notice tone="bad">{error}</Notice> : <LoadingBlock label="Loading application" />;

  const refresh = async () => {
    await reload();
    await reloadHistory();
  };

  async function run(key: string, action: () => Promise<unknown>, success?: string) {
    setBusy(key);
    try {
      await action();
      if (success) toast(success, "good");
      await refresh();
    } catch (err) {
      toast(errorMessage(err), "bad");
    } finally {
      setBusy("");
    }
  }

  const resumeUrl = app.resume_version_id ? `/api/v1/resume-versions/${app.resume_version_id}/download?format=pdf&inline=true` : null;
  const sensitiveMissing = answers.filter((item) => item.sensitive && !item.answer && !item.deferred && !["criminal_history", "disability", "demographics"].includes(item.key));
  const editable = ["preparing", "awaiting_skill_verification", "awaiting_review", "approved", "failed"].includes(app.status);
  const submittedStates = ["submitted", "interview", "offer", "rejected"];
  const steps = [
    { key: "questions", label: "Questions", done: app.open_questions === 0 },
    { key: "resume", label: "Resume", done: Boolean(app.resume_version_id) },
    { key: "letter", label: "Cover letter (only if asked)", done: true },
    { key: "answers", label: "Answers", done: sensitiveMissing.length === 0 },
    { key: "approve", label: "Approve", done: app.approval_valid || submittedStates.includes(app.status) },
    { key: "apply", label: "Apply", done: submittedStates.includes(app.status) },
  ];

  return (
    <div>
      <Link href="/applications" className="mb-4 inline-flex items-center gap-1 text-[13px] text-muted hover:text-ink">
        <ArrowLeft className="h-4 w-4" /> Applications
      </Link>
      <header className="mb-5 flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="text-[13.5px] text-muted">{app.company}</div>
          <h1 className="text-[22px] font-semibold tracking-tight">{app.title}</h1>
          <div className="mt-2 flex flex-wrap gap-1.5">
            <Badge tone={STAGE_TONE[app.status] || "neutral"}>{applicationStatusLabel(app.status)}</Badge>
            {app.submission_label && <Badge tone={app.submission_label.startsWith("Simulated") ? "warn" : "good"}>{app.submission_label}</Badge>}
            {app.is_sample && <Badge tone="warn">Practice listing</Badge>}
            {!app.posting_active && <Badge tone="warn">Posting closed</Badge>}
          </div>
        </div>
        <div className="flex gap-2">
          <LinkButton href={`/jobs/${app.job_posting_id}`} variant="secondary">View job</LinkButton>
          {app.application_url && (
            <LinkButton href={app.application_url} external icon={<ExternalLink className="h-4 w-4" />}>
              Employer page
            </LinkButton>
          )}
        </div>
      </header>

      <ol className="mb-6 grid grid-cols-3 gap-2 sm:grid-cols-6">
        {steps.map((step, index) => (
          <li key={step.key} className={cn("rounded-lg border px-3 py-2 text-[12.5px]", step.done ? "border-success/30 bg-success-soft text-success" : "border-line bg-surface text-muted")}>
            <span className="mr-1 font-semibold">{step.done ? <Check className="inline h-3.5 w-3.5" /> : `${index + 1}.`}</span>
            {step.label}
          </li>
        ))}
      </ol>

      <div className="space-y-6">
        {app.open_questions > 0 && app.questions && (
          <Card>
            <CardHeader title="1. Answer a few questions" description="This job asks for skills your resume does not mention. Your answers are saved to your profile, and the resume below is rebuilt with what you confirm." />
            <QuestionList questions={app.questions} profile={profile} jobId={app.job_posting_id} onDone={refresh} />
          </Card>
        )}

        <Card>
          <CardHeader
            title="2. Tailored resume"
            description={app.resume?.generation?.note || "Built from your own resume and confirmed facts."}
            actions={
              app.resume_version_id && (
                <>
                  <LinkButton href={`/resume/versions/${app.resume_version_id}`} size="sm" variant="secondary" icon={<FileText className="h-3.5 w-3.5" />}>
                    Review changes
                  </LinkButton>
                  <LinkButton href={`/api/v1/resume-versions/${app.resume_version_id}/download?format=pdf`} size="sm" variant="secondary" external icon={<Download className="h-3.5 w-3.5" />}>
                    PDF
                  </LinkButton>
                  <LinkButton href={`/api/v1/resume-versions/${app.resume_version_id}/download?format=docx`} size="sm" variant="secondary" external icon={<Download className="h-3.5 w-3.5" />}>
                    DOCX
                  </LinkButton>
                  {editable && (
                    <Button
                      size="sm"
                      variant="ghost"
                      icon={<RefreshCw className="h-3.5 w-3.5" />}
                      loading={busy === "regen"}
                      onClick={() =>
                        run("regen", async () => {
                          await api(`/resume-versions/${app.resume_version_id}/regenerate`, { method: "POST" });
                        }, "Built a fresh tailored version.")
                      }
                    >
                      Regenerate
                    </Button>
                  )}
                </>
              )
            }
          />
          {app.resume?.keywords && (
            <div className="mb-3 flex flex-wrap items-center gap-1.5 text-[12.5px]">
              <span className="text-muted">Job keywords covered:</span>
              {app.resume.keywords.covered.map((item) => (
                <span key={item} className="rounded bg-success-soft px-1.5 py-px text-success">{item}</span>
              ))}
              {app.resume.keywords.missing.length > 0 && <span className="ml-2 text-muted">Not covered:</span>}
              {app.resume.keywords.missing.map((item) => (
                <span key={item} className="rounded bg-surface2 px-1.5 py-px text-muted">{item}</span>
              ))}
            </div>
          )}
          {resumeUrl ? (
            <PdfFrame key={app.resume_version_id} src={resumeUrl} title="Tailored resume" className="h-[720px] rounded-lg border border-line" />
          ) : (
            <Notice>No resume is attached yet.</Notice>
          )}
        </Card>

        <Card>
          <CardHeader
            title="3. Cover letter (optional)"
            description={letter ? "Written from your most relevant experience. Edit freely; changes after approval need a new approval." : "Not written yet, to save AI credit. When ApplyPilot applies for you, it writes one only if the employer's form asks for it. You can also write one now."}
            actions={
              editable && (
                <>
                  <Select aria-label="Tone" value={tone} onChange={(event) => setTone(event.target.value)} options={TONES} wrapperClassName="w-44" />
                  <Button
                    size="sm"
                    variant="secondary"
                    icon={<RefreshCw className="h-3.5 w-3.5" />}
                    loading={busy === "letter-regen"}
                    onClick={() =>
                      run("letter-regen", async () => {
                        const result = await api<Application & { letter_generation?: { note: string } }>(`/applications/${app.id}/cover-letter`, { method: "POST", body: JSON.stringify({ tone }) });
                        setApp(result);
                        if (result.letter_generation?.note) toast(result.letter_generation.note);
                      })
                    }
                  >
                    Rewrite
                  </Button>
                </>
              )
            }
          />
          <Textarea value={letter} onChange={(event) => setLetter(event.target.value)} className="min-h-72 font-[inherit]" disabled={!editable} />
          <div className="mt-3 flex justify-end gap-2">
            <Button size="sm" variant="ghost" icon={<ClipboardCopy className="h-3.5 w-3.5" />} onClick={() => copy(letter, toast, "Cover letter copied")}>
              Copy
            </Button>
            {editable && letter !== (app.cover_letter || "") && (
              <Button size="sm" loading={busy === "letter"} onClick={() => run("letter", () => api(`/applications/${app.id}`, { method: "PATCH", body: JSON.stringify({ cover_letter: letter }) }), "Cover letter saved.")}>
                Save letter
              </Button>
            )}
          </div>
        </Card>

        <Card>
          <CardHeader title="4. Application answers" description="Drafted from your profile for common questions. Work authorization and other personal answers are never guessed: you type them once and ApplyPilot remembers them for next time." />
          <div className="space-y-4">
            {answers.map((answer, index) => {
              const optional = ["criminal_history", "disability", "demographics"].includes(answer.key);
              return (
                <div key={answer.key}>
                  <div className="mb-1 flex flex-wrap items-center gap-2 text-[13px] font-medium">
                    {answer.prompt}
                    {answer.sensitive && !optional && <Badge tone={answer.answer ? "good" : "warn"}>{answer.answer ? (answer.from_saved ? "From your saved answer" : "Answered by you") : "You answer this"}</Badge>}
                    {optional && <Badge>Optional, never filled in for you</Badge>}
                  </div>
                  {optional ? null : (
                    <div className="flex gap-2">
                      <Textarea
                        value={answer.answer || ""}
                        disabled={!editable}
                        onChange={(event) => setAnswers((current) => current.map((item, position) => (position === index ? { ...item, answer: event.target.value } : item)))}
                        className="min-h-[52px]"
                        wrapperClassName="flex-1"
                      />
                      <button className="self-start rounded-md p-2 text-muted hover:bg-surface2 hover:text-ink" title="Copy" onClick={() => copy(answer.answer || "", toast)}>
                        <ClipboardCopy className="h-4 w-4" />
                      </button>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
          {editable && (
            <div className="mt-4 flex justify-end">
              <Button loading={busy === "answers"} onClick={() => run("answers", () => api(`/applications/${app.id}`, { method: "PATCH", body: JSON.stringify({ answers }) }), "Answers saved.")}>
                Save answers
              </Button>
            </div>
          )}
        </Card>

        <Card>
          <CardHeader title="5. Approve" description="Approval locks this exact resume, cover letter, and set of answers. Any later edit asks you to approve again." />
          {app.approval_valid ? (
            <Notice tone="good" title="Approved">This draft is approved. Continue to step 6 to apply.</Notice>
          ) : submittedStates.includes(app.status) ? (
            <Notice tone="good">This application was already sent.</Notice>
          ) : (
            <div className="space-y-3">
              {app.open_questions > 0 && <Checkbox checked={ackUnverified} onChange={setAckUnverified} label={`Continue even though ${app.open_questions} question(s) are unanswered`} />}
              <Checkbox checked={ackGaps} onChange={setAckGaps} label="I reviewed the resume and letter, and everything in them is accurate" />
              <div>
                <Button
                  icon={<ShieldCheck className="h-4 w-4" />}
                  disabled={!ackGaps || (app.open_questions > 0 && !ackUnverified) || app.status === "withdrawn"}
                  loading={busy === "approve"}
                  onClick={() =>
                    run("approve", () => api(`/applications/${app.id}/approve`, { method: "POST", body: JSON.stringify({ acknowledge_unverified: true, acknowledge_gaps: true }) }), "Approved. You can apply now.")
                  }
                >
                  Approve this draft
                </Button>
              </div>
            </div>
          )}
        </Card>

        <Card>
          <CardHeader
            title="6. Apply"
            description={app.autoapply && app.autoapply.level !== "none" ? app.autoapply.note : app.apply_guide?.submission_note}
            actions={supportBadge(app.autoapply)}
          />
          {app.submit_on && app.submit_on.length > 0 && (
            <div className="mb-3 rounded-lg border border-line p-3">
              <div className="mb-2 text-[13px] font-medium">This posting is submitted in {app.submit_on.length} places</div>
              <div className="space-y-2.5">
                {app.submit_on.map((channel) => (
                  <div key={channel.key} className="flex flex-wrap items-start justify-between gap-2 text-[13px]">
                    <div className="min-w-0">
                      <div className="flex items-center gap-1.5">
                        {channel.done ? <CheckCircle2 className="h-4 w-4 text-success" /> : <span className="inline-block h-4 w-4 rounded-full border border-line" />}
                        <span className="font-medium">{channel.name}</span>
                        {channel.deadline && <span className="text-[12px] text-muted">· due {channel.deadline}</span>}
                        {channel.url && (
                          <a href={channel.url} target="_blank" rel="noreferrer" className="text-accent hover:underline" aria-label={`Open ${channel.name}`}>
                            <ExternalLink className="h-3.5 w-3.5" />
                          </a>
                        )}
                      </div>
                      <p className="pl-[22px] text-[12px] text-muted">{channel.how}{channel.documents ? ` Documents: ${channel.documents}.` : ""}</p>
                    </div>
                    {channel.key !== "employer" && (
                      <Button
                        size="sm"
                        variant={channel.done ? "ghost" : "secondary"}
                        loading={busy === `portal-${channel.key}`}
                        onClick={async () => {
                          setBusy(`portal-${channel.key}`);
                          try {
                            setApp(await api<Application>(`/applications/${app.id}/portal-submitted`, { method: "POST", body: JSON.stringify({ done: !channel.done }) }));
                          } catch (err) {
                            toast(errorMessage(err), "bad");
                          } finally {
                            setBusy("");
                          }
                        }}
                      >
                        {channel.done ? "Undo" : "I submitted it there"}
                      </Button>
                    )}
                  </div>
                ))}
              </div>
              {app.resume_version_id && (
                <a href={`/api/v1/resume-versions/${app.resume_version_id}/download?format=pdf`} className="mt-2 inline-flex items-center gap-1 text-[12.5px] text-accent hover:underline">
                  <Download className="h-3.5 w-3.5" /> Tailored resume PDF for the portal
                </a>
              )}
            </div>
          )}
          <div className="mb-3"><ApplyQueue applicationId={app.id} onChange={reload} /></div>
          {app.status === "approved" || app.status === "failed" ? (
            <div className="space-y-3">
              {sensitiveMissing.length > 0 && <Notice tone="warn">{sensitiveMissing.length} personal answer(s) are blank. ApplyPilot will ask you if a form needs them.</Notice>}
              <div className="flex flex-wrap gap-2">
                {app.status === "approved" && app.approval_valid && !app.is_sample && app.autoapply?.level !== "none" && (
                  <Button icon={<Sparkles className="h-4 w-4" />} onClick={() => setAutoApply(true)}>
                    Let ApplyPilot apply
                  </Button>
                )}
                <Button
                  variant={app.status === "approved" && app.autoapply?.level !== "none" && !app.is_sample ? "secondary" : "primary"}
                  icon={<Send className="h-4 w-4" />}
                  loading={busy === "handoff"}
                  onClick={() =>
                    run("handoff", async () => {
                      await api(`/applications/${app.id}/submit`, { method: "POST", body: JSON.stringify({ method: "manual", defer_sensitive: true }) });
                      if (app.application_url) window.open(app.application_url, "_blank", "noreferrer");
                    })
                  }
                >
                  Start applying on the employer site
                </Button>
                {health?.demo_mode && (
                  <Button
                    variant="ghost"
                    loading={busy === "simulate"}
                    onClick={() =>
                      run("simulate", () => api(`/applications/${app.id}/submit`, { method: "POST", body: JSON.stringify({ method: "simulated", defer_sensitive: true }) }), "Recorded a simulated submission. Nothing was sent to the employer.")
                    }
                  >
                    Record a practice submission
                  </Button>
                )}
              </div>
            </div>
          ) : app.status === "manual_action_required" ? (
            <div className="space-y-4">
              <ol className="list-decimal space-y-1 pl-5 text-[13.5px]">
                {(app.apply_guide?.steps || []).map((step) => (
                  <li key={step}>{step}</li>
                ))}
              </ol>
              <div className="flex flex-wrap gap-2">
                {app.application_url && (
                  <LinkButton href={app.application_url} external icon={<ExternalLink className="h-4 w-4" />}>
                    Open application page
                  </LinkButton>
                )}
                {app.resume_version_id && (
                  <LinkButton href={`/api/v1/resume-versions/${app.resume_version_id}/download?format=pdf`} external variant="secondary" icon={<Download className="h-4 w-4" />}>
                    Resume PDF
                  </LinkButton>
                )}
                <Button variant="secondary" icon={<ClipboardCopy className="h-4 w-4" />} onClick={() => copy(letter, toast, "Cover letter copied")}>
                  Copy cover letter
                </Button>
                <Button icon={<CheckCircle2 className="h-4 w-4" />} onClick={() => setConfirmOpen(true)}>
                  I submitted it
                </Button>
              </div>
            </div>
          ) : submittedStates.includes(app.status) ? (
            <div className="space-y-3">
              <Notice tone={app.submission_method === "simulated" ? "warn" : "good"} title={app.submission_label || "Submitted"}>
                {app.submission_method === "simulated" ? "This was a practice record. No employer received it." : `Recorded ${fullDate(app.updated_at)}. Confirmation: ${app.confirmation_id}.`}
              </Notice>
              <div className="flex flex-wrap items-end gap-2">
                <Input label="Interview date (optional)" type="datetime-local" value={interviewAt} onChange={(event) => setInterviewAt(event.target.value)} wrapperClassName="w-60" />
                {["interview", "offer", "rejected", "withdrawn"].map((status) => (
                  <Button
                    key={status}
                    size="sm"
                    variant={status === "interview" || status === "offer" ? "secondary" : "ghost"}
                    disabled={app.status === status}
                    onClick={() =>
                      run(status, () => api(`/applications/${app.id}/status`, { method: "POST", body: JSON.stringify({ status, note: "Updated by you", interview_at: status === "interview" && interviewAt ? new Date(interviewAt).toISOString() : null }) }), `Marked as ${applicationStatusLabel(status).toLowerCase()}.`)
                    }
                  >
                    {status === "interview" ? "Got an interview" : status === "offer" ? "Got an offer" : status === "rejected" ? "Rejected" : "Withdrew"}
                  </Button>
                ))}
              </div>
              {app.interview_at && <p className="text-[13px] text-muted">Interview: {new Date(app.interview_at).toLocaleString()}</p>}
            </div>
          ) : (
            <p className="text-[13px] text-muted">Approve the draft first.</p>
          )}
        </Card>

        {history && history.events.length > 0 && (
          <Card>
            <CardHeader title="History" />
            <ol className="space-y-2 border-l border-line pl-4 text-[13px]">
              {history.events.map((event, index) => (
                <li key={index} className="relative">
                  <span className="absolute -left-[21px] top-1.5 h-2 w-2 rounded-full bg-accent" />
                  <span className="font-medium">{applicationStatusLabel(event.to)}</span>
                  <span className="text-muted"> · {new Date(event.at).toLocaleString()}</span>
                  {event.note && <div className="text-muted">{event.note}</div>}
                </li>
              ))}
            </ol>
          </Card>
        )}

        {editable && app.status !== "withdrawn" && (
          <div className="flex justify-end">
            <Button variant="ghost" onClick={() => run("withdraw", () => api(`/applications/${app.id}/reject`, { method: "POST" }), "Draft discarded.")}>
              Discard this draft
            </Button>
          </div>
        )}
      </div>

      <Modal
        open={confirmOpen}
        onClose={() => setConfirmOpen(false)}
        title="Confirm you submitted it"
        description="ApplyPilot records this as submitted by you. It does not check the employer's site."
        footer={
          <>
            <Button variant="secondary" onClick={() => setConfirmOpen(false)}>Cancel</Button>
            <Button
              disabled={confirmNote.trim().length < 3}
              loading={busy === "confirm"}
              onClick={() =>
                run("confirm", async () => {
                  await api(`/applications/${app.id}/confirm-manual`, { method: "POST", body: JSON.stringify({ note: confirmNote }) });
                  setConfirmOpen(false);
                }, "Marked as submitted.")
              }
            >
              Mark as submitted
            </Button>
          </>
        }
      >
        <Textarea label="Note" hint="For example the confirmation email or reference number." value={confirmNote} onChange={(event) => setConfirmNote(event.target.value)} />
      </Modal>
      {autoApply && <StartApplyModal open onClose={() => setAutoApply(false)} rows={[app]} onStarted={reload} />}
    </div>
  );
}
