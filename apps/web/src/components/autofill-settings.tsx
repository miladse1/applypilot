"use client";

import { useEffect, useState } from "react";
import { PenLine, Trash2 } from "lucide-react";
import { Button, Card, CardHeader, ErrorState, Input, LoadingBlock, Select, useToast } from "@/components/ui";
import { api } from "@/lib/api";
import { errorMessage, useApi } from "@/lib/hooks";

type Saved = {
  preferences: Array<{ key: string; description: string; value: string }>;
  questions: Array<{ key: string; question: string; value: string }>;
};

const CHOICES: Record<string, Array<{ value: string; label: string }>> = {
  voluntary_disclosures: [{ value: "", label: "Ask me each time" }, { value: "decline", label: "Always choose “I don't wish to answer”" }],
  consent_privacy: [{ value: "", label: "Ask me first" }, { value: "yes", label: "Accept when a form requires it" }],
  age_18: [{ value: "", label: "Not set" }, { value: "Yes", label: "Yes" }, { value: "No", label: "No" }],
  work_authorization: [{ value: "", label: "Not set" }, { value: "Yes", label: "Yes" }, { value: "No", label: "No" }],
  sponsorship: [{ value: "", label: "Not set" }, { value: "No", label: "No" }, { value: "Yes", label: "Yes" }],
  relocation: [{ value: "", label: "Not set" }, { value: "Yes", label: "Yes" }, { value: "No", label: "No" }],
};

const LABELS: Record<string, string> = {
  voluntary_disclosures: "Voluntary questions",
  consent_privacy: "Candidate privacy notices",
  how_heard: "How did you hear about us?",
  location: "Where you live",
  country: "Country",
  address_line1: "Street address",
  postal_code: "Postal code",
  age_18: "18 or older",
  work_authorization: "Authorized to work in the job's country",
  sponsorship: "Need sponsorship",
  start_date: "Start date",
  relocation: "Willing to relocate",
  salary: "Salary expectation",
};

export function AutofillSettings() {
  const toast = useToast();
  const { data, error, reload, setData } = useApi<Saved>("/apply/answers");
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const [editing, setEditing] = useState<string | null>(null);
  const [answer, setAnswer] = useState("");

  useEffect(() => {
    if (data) setDraft(Object.fromEntries(data.preferences.map((item) => [item.key, item.value])));
  }, [data]);

  async function save(values: Record<string, string>, message = "Saved.") {
    setSaving(true);
    try {
      setData(await api<Saved>("/apply/answers", { method: "PUT", body: JSON.stringify({ values }) }));
      toast(message, "good");
    } catch (err) {
      toast(errorMessage(err), "bad");
    } finally {
      setSaving(false);
    }
  }

  if (error) return <ErrorState message={error} onRetry={reload} />;
  if (!data) return <LoadingBlock label="Loading saved answers" />;
  const changed = data.preferences.some((item) => (draft[item.key] ?? "") !== item.value);

  return (
    <Card>
      <CardHeader
        title="Application autofill"
        description="What ApplyPilot may put into employer forms besides your profile. Set these once so it pauses less. Anything you answer while it runs can be remembered here too."
      />
      <div className="grid gap-3 sm:grid-cols-2">
        {data.preferences.map((item) =>
          CHOICES[item.key] ? (
            <Select key={item.key} label={LABELS[item.key] || item.key} value={draft[item.key] ?? ""} options={CHOICES[item.key]} onChange={(event) => setDraft({ ...draft, [item.key]: event.target.value })} hint={item.description} />
          ) : (
            <Input key={item.key} label={LABELS[item.key] || item.key} value={draft[item.key] ?? ""} onChange={(event) => setDraft({ ...draft, [item.key]: event.target.value })} hint={item.description} />
          ),
        )}
      </div>
      <div className="mt-3">
        <Button size="sm" disabled={!changed} loading={saving} onClick={() => save(draft)}>Save</Button>
      </div>
      {data.questions.length > 0 && (
        <div className="mt-6">
          <h3 className="mb-0.5 text-[13px] font-semibold">Remembered answers ({data.questions.length})</h3>
          <p className="mb-2 text-[12px] text-muted">Answers you confirmed on earlier forms. ApplyPilot reuses them when a form asks the same thing, even in other words, and only asks you again when nothing fits.</p>
          <div className="divide-y divide-line rounded-lg border border-line text-[13px]">
            {data.questions.map((item) => (
              <div key={item.key} className="flex items-center justify-between gap-3 px-3 py-2">
                <div className="min-w-0 flex-1">
                  <div className="truncate first-letter:uppercase">{item.question}</div>
                  {editing === item.key ? (
                    <form
                      className="mt-1 flex gap-2"
                      onSubmit={(event) => {
                        event.preventDefault();
                        save({ [item.key]: answer }, "Updated.").then(() => setEditing(null));
                      }}
                    >
                      <Input aria-label="Answer" value={answer} onChange={(event) => setAnswer(event.target.value)} wrapperClassName="flex-1" className="h-8" autoFocus />
                      <Button size="sm" type="submit" loading={saving} disabled={!answer.trim()}>Save</Button>
                      <Button size="sm" variant="ghost" type="button" onClick={() => setEditing(null)}>Cancel</Button>
                    </form>
                  ) : (
                    <div className="truncate text-[12px] text-muted">{item.value}</div>
                  )}
                </div>
                {editing !== item.key && (
                  <div className="flex shrink-0">
                    <Button size="sm" variant="ghost" icon={<PenLine className="h-3.5 w-3.5" />} onClick={() => { setEditing(item.key); setAnswer(item.value); }} aria-label="Edit this answer" />
                    <Button size="sm" variant="ghost" icon={<Trash2 className="h-3.5 w-3.5" />} onClick={() => save({ [item.key]: "" }, "Forgotten.")} aria-label="Forget this answer" />
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </Card>
  );
}
