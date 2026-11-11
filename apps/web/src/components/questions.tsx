"use client";

import { useState } from "react";
import { Check, HelpCircle } from "lucide-react";
import { Badge, Button, Input, Select, useToast } from "@/components/ui";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/hooks";
import type { Profile, Question } from "@/lib/types";
import { cn } from "@/lib/utils";

export type QuestionDraft = {
  choice: "" | "yes" | "learning" | "no" | "unsure" | "skip";
  where: string;
  context: string;
  proficiency: string;
  months: string;
};

const CHOICES: Array<{ value: QuestionDraft["choice"]; label: string }> = [
  { value: "yes", label: "Yes, I've used it" },
  { value: "learning", label: "I'm learning it" },
  { value: "no", label: "No, I haven't" },
  { value: "unsure", label: "Not sure" },
];

export function emptyDraft(): QuestionDraft {
  return { choice: "", where: "", context: "", proficiency: "intermediate", months: "" };
}

export function QuestionCard({ question, draft, onChange, profile, showJob }: { question: Question; draft: QuestionDraft; onChange: (draft: QuestionDraft) => void; profile: Profile | null; showJob?: boolean }) {
  const places = [
    ...(profile?.projects || []).map((item) => ({ value: `project:${item.id}`, label: `Project: ${item.name}` })),
    ...(profile?.experience || []).map((item) => ({ value: `experience:${item.id}`, label: `${item.title} at ${item.employer}` })),
    { value: "other", label: "Somewhere else (describe below)" },
  ];
  return (
    <div className="rounded-xl border border-line bg-surface p-4 shadow-card">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="flex items-start gap-2.5">
          <span className="mt-0.5 rounded-md bg-warn-soft p-1 text-warn">
            <HelpCircle className="h-4 w-4" />
          </span>
          <div>
            <div className="text-[15px] font-semibold">{question.display_name}</div>
            <p className="mt-0.5 text-[13px] text-muted">{question.prompt}</p>
            {showJob && question.job && (
              <p className="mt-1 text-[12px] text-faint">
                For {question.job.title} at {question.job.company}
              </p>
            )}
          </div>
        </div>
        <Badge tone={question.priority === "mandatory" ? "warn" : "neutral"}>{question.priority === "mandatory" ? "Required by the job" : "Preferred"}</Badge>
      </div>
      <div className="mt-3 flex flex-wrap gap-1.5">
        {CHOICES.map((choice) => (
          <button
            key={choice.value}
            type="button"
            onClick={() => onChange({ ...draft, choice: choice.value })}
            className={cn(
              "inline-flex items-center gap-1 rounded-lg border px-3 py-1.5 text-[13px] transition",
              draft.choice === choice.value ? "border-accent bg-accent-soft font-medium text-accent" : "border-line text-muted hover:text-ink",
            )}
          >
            {draft.choice === choice.value && <Check className="h-3.5 w-3.5" />}
            {choice.label}
          </button>
        ))}
      </div>
      {draft.choice === "yes" && (
        <div className="mt-3 grid gap-3 rounded-lg bg-surface2 p-3 sm:grid-cols-2">
          <Select
            label="Where did you use it?"
            value={draft.where}
            onChange={(event) => onChange({ ...draft, where: event.target.value })}
            options={[{ value: "", label: "Choose one (optional)" }, ...places]}
          />
          <Select
            label="How comfortable are you?"
            value={draft.proficiency}
            onChange={(event) => onChange({ ...draft, proficiency: event.target.value })}
            options={[
              { value: "beginner", label: "Beginner: used it a little" },
              { value: "intermediate", label: "Intermediate: used it on real work" },
              { value: "advanced", label: "Advanced: could teach it" },
            ]}
          />
          <Input
            wrapperClassName="sm:col-span-2"
            label="What did you do with it?"
            hint="Optional. A short note helps the resume wording, for example “Containerized the booking API for deployment.”"
            value={draft.context}
            onChange={(event) => onChange({ ...draft, context: event.target.value })}
          />
          {question.min_years ? (
            <Input label={`Months of use (the job asks for ${question.min_years}+ years)`} type="number" min={0} value={draft.months} onChange={(event) => onChange({ ...draft, months: event.target.value })} />
          ) : null}
        </div>
      )}
      {draft.choice === "no" && <p className="mt-2 text-[12.5px] text-muted">Saved as a gap for this job. It will not appear on your resume, and ApplyPilot will not ask again.</p>}
      {draft.choice === "learning" && <p className="mt-2 text-[12.5px] text-muted">Saved as learning. It stays off your resume until you confirm it.</p>}
    </div>
  );
}

export function draftPayload(question: Question, draft: QuestionDraft, profile: Profile | null) {
  const [kind, id] = draft.where.split(":");
  let context = draft.context.trim();
  if (!context && kind === "project") {
    const project = profile?.projects.find((item) => item.id === id);
    if (project) context = `Used in the project ${project.name}.`;
  } else if (!context && kind === "experience") {
    const role = profile?.experience.find((item) => item.id === id);
    if (role) context = `Used as ${role.title} at ${role.employer}.`;
  } else if (context && kind === "project") {
    const project = profile?.projects.find((item) => item.id === id);
    if (project) context = `${project.name}: ${context}`;
  } else if (context && kind === "experience") {
    const role = profile?.experience.find((item) => item.id === id);
    if (role) context = `${role.employer}: ${context}`;
  }
  return {
    request_id: question.id,
    normalized_name: question.normalized_name,
    choice: draft.choice || "skip",
    context: draft.choice === "yes" ? context || null : null,
    setting: kind === "project" ? "project" : kind === "experience" ? "work" : null,
    proficiency: draft.choice === "yes" ? draft.proficiency : draft.choice === "learning" ? "learning" : null,
    duration_months: draft.months ? Number(draft.months) : null,
  };
}

/** A self-contained block that answers every open question for one job. */
export function QuestionList({ questions, profile, jobId, onDone }: { questions: Question[]; profile: Profile | null; jobId?: string; onDone?: (result: { application?: { id: string; status: string } | null }) => void }) {
  const toast = useToast();
  const [drafts, setDrafts] = useState<Record<string, QuestionDraft>>({});
  const [pending, setPending] = useState(false);
  const answered = questions.filter((question) => (drafts[question.id] || emptyDraft()).choice);

  async function save() {
    setPending(true);
    try {
      const result = await api<{ application?: { id: string; status: string } | null }>("/qualifications/answers", {
        method: "POST",
        body: JSON.stringify({
          job_id: jobId || null,
          answers: answered.map((question) => draftPayload(question, drafts[question.id] || emptyDraft(), profile)),
        }),
      });
      toast(`Saved ${answered.length} answer${answered.length === 1 ? "" : "s"}. ApplyPilot will remember them.`, "good");
      setDrafts({});
      onDone?.(result);
    } catch (err) {
      toast(errorMessage(err), "bad");
    } finally {
      setPending(false);
    }
  }

  return (
    <div className="space-y-3">
      {questions.map((question) => (
        <QuestionCard key={question.id} question={question} profile={profile} draft={drafts[question.id] || emptyDraft()} onChange={(draft) => setDrafts((current) => ({ ...current, [question.id]: draft }))} showJob={!jobId} />
      ))}
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="text-[12.5px] text-muted">
          {answered.length} of {questions.length} answered. Unanswered questions stay open.
        </span>
        <Button onClick={save} loading={pending} disabled={!answered.length}>
          Save answers
        </Button>
      </div>
    </div>
  );
}
