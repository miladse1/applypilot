"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useState } from "react";
import { AlertTriangle, Check, FileUp, RefreshCw, X } from "lucide-react";
import { SearchSetup } from "@/components/search-fields";
import { Badge, Button, Card, CardHeader, Checkbox, Input, LoadingBlock, Notice, PageHeader, TagInput, Textarea, useToast } from "@/components/ui";
import { api } from "@/lib/api";
import { errorMessage, useApi } from "@/lib/hooks";
import type { Extraction, OriginalResume } from "@/lib/types";
import { cn } from "@/lib/utils";

type Step = "upload" | "review" | "search" | "done";

function monthValue(value: string | null) {
  return value ? value.slice(0, 7) : "";
}
function fromMonth(value: string) {
  return value ? `${value}-01` : null;
}

function Onboarding() {
  const router = useRouter();
  const params = useSearchParams();
  const toast = useToast();
  const { data: resumes, reload: reloadResumes } = useApi<OriginalResume[]>("/resumes");
  const [step, setStep] = useState<Step>("upload");
  const [resume, setResume] = useState<OriginalResume | null>(null);
  const [extraction, setExtraction] = useState<Extraction | null>(null);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [dragging, setDragging] = useState(false);

  const openReview = useCallback((row: OriginalResume) => {
    setResume(row);
    setExtraction(row.extraction);
    setStep("review");
  }, []);

  useEffect(() => {
    const id = params.get("resume");
    if (id && resumes) {
      const row = resumes.find((item) => item.id === id);
      if (row) openReview(row);
    }
    if (params.get("step") === "search") setStep("search");
  }, [params, resumes, openReview]);

  async function upload(file: File) {
    setBusy("upload");
    setError("");
    const form = new FormData();
    form.append("file", file);
    try {
      const created = await api<OriginalResume>("/resumes", { method: "POST", body: form });
      openReview(created);
      await reloadResumes();
    } catch (err) {
      setError(errorMessage(err, "Upload failed"));
    } finally {
      setBusy("");
    }
  }

  async function reparse(row: OriginalResume) {
    setBusy(`reparse-${row.id}`);
    try {
      const updated = await api<OriginalResume>(`/resumes/${row.id}/reparse`, { method: "POST" });
      openReview(updated);
      toast("Read your resume again with the improved parser. Check it below.", "good");
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy("");
    }
  }

  async function saveReview() {
    if (!resume || !extraction) return;
    setBusy("save");
    setError("");
    try {
      await api(`/resumes/${resume.id}/extraction`, { method: "PATCH", body: JSON.stringify({ extraction }) });
      await api(`/resumes/${resume.id}/approve`, { method: "POST" });
      const contact = extraction.contact;
      await api("/profile", {
        method: "PATCH",
        body: JSON.stringify({
          full_name: contact.full_name || undefined,
          phone: contact.phone || null,
          location: contact.location || null,
          linkedin_url: contact.linkedin_url || null,
          github_url: contact.github_url || null,
          portfolio_url: (contact.portfolio_url as string) || null,
        }),
      });
      toast("Saved to your profile.", "good");
      setStep("search");
      window.scrollTo({ top: 0 });
    } catch (err) {
      setError(errorMessage(err, "Could not save"));
    } finally {
      setBusy("");
    }
  }

  return (
    <div>
      <PageHeader title="Set up ApplyPilot" description="Upload your resume, check what was read, and tell ApplyPilot what jobs you want. You can change any of this later." />
      <ol className="mb-6 flex flex-wrap gap-2 text-[13px]">
        {(["upload", "review", "search"] as const).map((key, index) => {
          const order = ["upload", "review", "search", "done"];
          const done = order.indexOf(step) > index;
          return (
            <li key={key} className={cn("flex items-center gap-2 rounded-full border px-3 py-1", step === key ? "border-accent bg-accent-soft font-medium text-accent" : done ? "border-success/30 text-success" : "border-line text-muted")}>
              {done ? <Check className="h-3.5 w-3.5" /> : <span>{index + 1}</span>}
              {key === "upload" ? "Upload resume" : key === "review" ? "Review" : "Job search"}
            </li>
          );
        })}
      </ol>
      {error && <Notice tone="bad" className="mb-4">{error}</Notice>}

      {step === "upload" && (
        <div className="space-y-4">
          <label
            onDragOver={(event) => {
              event.preventDefault();
              setDragging(true);
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={(event) => {
              event.preventDefault();
              setDragging(false);
              const file = event.dataTransfer.files?.[0];
              if (file) upload(file);
            }}
            className={cn("flex cursor-pointer flex-col items-center justify-center rounded-xl border-2 border-dashed bg-surface px-6 py-14 text-center transition", dragging ? "border-accent bg-accent-soft" : "border-line hover:border-faint")}
          >
            <FileUp className="mb-3 h-8 w-8 text-accent" />
            <div className="text-[15px] font-semibold">{busy === "upload" ? "Reading your resume…" : "Drop your resume here or click to choose"}</div>
            <div className="mt-1 text-[13px] text-muted">PDF or DOCX, up to 8 MB. Your original file is kept unchanged.</div>
            <input type="file" accept=".pdf,.docx" className="hidden" onChange={(event) => event.target.files?.[0] && upload(event.target.files[0])} />
          </label>
          {resumes && resumes.length > 0 && (
            <Card>
              <CardHeader title="Your uploaded resumes" description="Review one again, or re-read it with ApplyPilot's improved parser." />
              <div className="divide-y divide-line">
                {resumes.map((row) => (
                  <div key={row.id} className="flex flex-wrap items-center justify-between gap-2 py-2.5">
                    <div>
                      <div className="text-[13.5px] font-medium">{row.filename}</div>
                      <div className="text-[12px] text-muted">
                        {row.approved_at ? "Saved to profile" : "Not reviewed"} · {new Date(row.created_at || "").toLocaleDateString()}
                        {!row.has_layout && " · read with the old parser"}
                      </div>
                    </div>
                    <div className="flex gap-2">
                      {row.is_primary && <Badge tone="accent">Main resume</Badge>}
                      <Button size="sm" variant="secondary" icon={<RefreshCw className="h-3.5 w-3.5" />} loading={busy === `reparse-${row.id}`} onClick={() => reparse(row)}>
                        Re-read
                      </Button>
                      <Button size="sm" onClick={() => openReview(row)}>Review</Button>
                    </div>
                  </div>
                ))}
              </div>
            </Card>
          )}
        </div>
      )}

      {step === "review" && extraction && resume && (
        <Review
          extraction={extraction}
          onChange={setExtraction}
          resume={resume}
          busy={busy}
          onSave={saveReview}
          onReparse={() => reparse(resume)}
          onBack={() => setStep("upload")}
        />
      )}

      {step === "search" && <SearchSetup onDone={() => router.push("/jobs?discover=1")} onSkip={() => router.push("/dashboard")} />}
    </div>
  );
}

function Review({ extraction, onChange, resume, busy, onSave, onReparse, onBack }: { extraction: Extraction; onChange: (value: Extraction) => void; resume: OriginalResume; busy: string; onSave: () => void; onReparse: () => void; onBack: () => void }) {
  const contact = extraction.contact;
  const setContact = (key: string, value: string) => onChange({ ...extraction, contact: { ...contact, [key]: value } });
  const fromSkillsList = extraction.skills.filter((skill) => skill.found_in === "skills_section" && !skill.needs_review);
  const flagged = extraction.skills.filter((skill) => skill.needs_review);
  const elsewhere = extraction.skills.filter((skill) => skill.found_in !== "skills_section" && !skill.needs_review);
  const groups = new Map<string, typeof fromSkillsList>();
  for (const skill of fromSkillsList) {
    const label = skill.group || "Skills";
    groups.set(label, [...(groups.get(label) || []), skill]);
  }
  function removeSkill(name: string) {
    onChange({ ...extraction, skills: extraction.skills.filter((skill) => skill.name !== name) });
  }
  function addSkill(names: string[]) {
    const existing = new Set(extraction.skills.map((skill) => skill.name.toLowerCase()));
    const added = names.filter((name) => !existing.has(name.toLowerCase())).map((name) => ({ name, normalized_name: name.toLowerCase(), category: "other", group: "Added by you", needs_review: false, found_in: "skills_section", accepted: true }));
    onChange({ ...extraction, skills: [...extraction.skills, ...added] });
  }
  function patchList<K extends "experience" | "education" | "projects">(key: K, index: number, patch: Partial<Extraction[K][number]>) {
    const rows = [...extraction[key]] as Extraction[K];
    rows[index] = { ...rows[index], ...patch };
    onChange({ ...extraction, [key]: rows });
  }
  const placeholders = (contact.placeholders as string[] | undefined) || [];

  return (
    <div className="space-y-5">
      <Notice tone="accent" title={`Read from ${resume.filename}`} action={<Button size="sm" variant="ghost" icon={<RefreshCw className="h-3.5 w-3.5" />} loading={busy.startsWith("reparse")} onClick={onReparse}>Read again</Button>}>
        Correct anything that looks wrong. ApplyPilot only uses facts from your resume and from answers you give later. It will not ask about skills now.
      </Notice>
      {extraction.warnings.filter((warning) => !warning.includes("placeholder")).map((warning) => (
        <Notice key={warning} tone="neutral">{warning}</Notice>
      ))}

      <Card>
        <CardHeader title="Contact" />
        {placeholders.length > 0 && (
          <Notice tone="warn" className="mb-3" title="Your resume has placeholder text">
            {placeholders.join(", ")} appear on your resume. Add the real links below. Tailored resumes use these links instead of the placeholders.
          </Notice>
        )}
        <div className="grid gap-3 sm:grid-cols-2">
          <Input label="Full name" value={(contact.full_name as string) || ""} onChange={(event) => setContact("full_name", event.target.value)} />
          <Input label="Email" value={(contact.email as string) || ""} onChange={(event) => setContact("email", event.target.value)} />
          <Input label="Phone" value={(contact.phone as string) || ""} onChange={(event) => setContact("phone", event.target.value)} />
          <Input label="City" value={(contact.location as string) || ""} onChange={(event) => setContact("location", event.target.value)} placeholder="Toronto, ON" />
          <Input label="LinkedIn" value={(contact.linkedin_url as string) || ""} onChange={(event) => setContact("linkedin_url", event.target.value)} placeholder="linkedin.com/in/…" />
          <Input label="GitHub" value={(contact.github_url as string) || ""} onChange={(event) => setContact("github_url", event.target.value)} placeholder="github.com/…" />
          <Input label="Portfolio" value={(contact.portfolio_url as string) || ""} onChange={(event) => setContact("portfolio_url", event.target.value)} wrapperClassName="sm:col-span-2" />
        </div>
      </Card>

      <Card>
        <CardHeader title="Summary" />
        <Textarea value={extraction.summary} onChange={(event) => onChange({ ...extraction, summary: event.target.value })} />
      </Card>

      <Card>
        <CardHeader title="Skills" description="Grouped the way they appear on your resume. Remove anything that was misread." />
        <div className="space-y-3">
          {[...groups.entries()].map(([label, skills]) => (
            <div key={label}>
              <div className="mb-1.5 text-[12.5px] font-medium text-muted">{label}</div>
              <div className="flex flex-wrap gap-1.5">
                {skills.map((skill) => (
                  <span key={skill.name} className="inline-flex items-center gap-1 rounded-md border border-line bg-surface2 px-2 py-1 text-[13px]">
                    {skill.original || skill.name}
                    <button onClick={() => removeSkill(skill.name)} className="text-faint hover:text-danger" aria-label={`Remove ${skill.name}`}>
                      <X className="h-3 w-3" />
                    </button>
                  </span>
                ))}
              </div>
            </div>
          ))}
          {elsewhere.length > 0 && (
            <div>
              <div className="mb-1.5 text-[12.5px] font-medium text-muted">Also used in your experience or projects</div>
              <div className="flex flex-wrap gap-1.5">
                {elsewhere.map((skill) => (
                  <span key={skill.name} className="inline-flex items-center gap-1 rounded-md border border-line px-2 py-1 text-[13px]">
                    {skill.name}
                    <button onClick={() => removeSkill(skill.name)} className="text-faint hover:text-danger" aria-label={`Remove ${skill.name}`}>
                      <X className="h-3 w-3" />
                    </button>
                  </span>
                ))}
              </div>
            </div>
          )}
          {flagged.length > 0 && (
            <div className="rounded-lg border border-warn/30 bg-warn-soft p-3">
              <div className="mb-1.5 flex items-center gap-1.5 text-[12.5px] font-medium text-warn">
                <AlertTriangle className="h-3.5 w-3.5" /> These look like reading mistakes. Include any that are real skills.
              </div>
              {flagged.map((skill) => (
                <Checkbox
                  key={skill.name}
                  className="mr-4"
                  checked={Boolean(skill.accepted)}
                  onChange={(value) => onChange({ ...extraction, skills: extraction.skills.map((item) => (item.name === skill.name ? { ...item, accepted: value } : item)) })}
                  label={skill.name}
                />
              ))}
            </div>
          )}
          <TagInput label="Add a skill" value={[]} onChange={addSkill} placeholder="Type a skill and press Enter" />
        </div>
      </Card>

      <Card>
        <CardHeader title="Experience" description={`${extraction.experience.length} role${extraction.experience.length === 1 ? "" : "s"} found.`} />
        <div className="space-y-4">
          {extraction.experience.map((role, index) => (
            <div key={index} className={cn("rounded-lg border p-3", role.rejected ? "border-line opacity-50" : role.needs_review ? "border-warn/40" : "border-line")}>
              <div className="grid gap-3 sm:grid-cols-2">
                <Input label="Title" value={role.title} onChange={(event) => patchList("experience", index, { title: event.target.value })} />
                <Input label="Employer" value={role.employer} onChange={(event) => patchList("experience", index, { employer: event.target.value })} />
                <Input label="Location" value={role.location || ""} onChange={(event) => patchList("experience", index, { location: event.target.value })} />
                <div className="grid grid-cols-2 gap-2">
                  <Input label="Start" type="month" value={monthValue(role.start_date)} onChange={(event) => patchList("experience", index, { start_date: fromMonth(event.target.value) })} />
                  <Input label="End" type="month" disabled={role.is_current} value={monthValue(role.end_date)} onChange={(event) => patchList("experience", index, { end_date: fromMonth(event.target.value) })} />
                </div>
              </div>
              <div className="mt-2 flex flex-wrap items-center justify-between gap-2">
                <Checkbox checked={role.is_current} onChange={(value) => patchList("experience", index, { is_current: value, end_date: value ? null : role.end_date })} label="I currently work here" />
                <Button size="sm" variant="ghost" onClick={() => patchList("experience", index, { rejected: !role.rejected })}>
                  {role.rejected ? "Include this role" : "Not a real role, leave it out"}
                </Button>
              </div>
              <ul className="mt-2 list-disc space-y-1 pl-5 text-[13px] text-ink/85">
                {role.responsibilities.map((bullet) => (
                  <li key={bullet}>{bullet}</li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      </Card>

      <Card>
        <CardHeader title="Education" />
        <div className="space-y-4">
          {extraction.education.map((school, index) => (
            <div key={index} className="grid gap-3 rounded-lg border border-line p-3 sm:grid-cols-2">
              <Input label="School" value={school.institution} onChange={(event) => patchList("education", index, { institution: event.target.value })} />
              <Input label="Degree" value={school.degree || ""} onChange={(event) => patchList("education", index, { degree: event.target.value })} />
              <Input label="Program" value={school.program || ""} onChange={(event) => patchList("education", index, { program: event.target.value })} />
              <Input label="Graduation (expected)" type="month" value={monthValue(school.graduation_date)} onChange={(event) => patchList("education", index, { graduation_date: fromMonth(event.target.value) })} hint="Used to show you are a current student." />
              <Textarea label="Coursework" value={school.coursework || ""} onChange={(event) => patchList("education", index, { coursework: event.target.value })} wrapperClassName="sm:col-span-2" className="min-h-[60px]" />
            </div>
          ))}
        </div>
      </Card>

      <Card>
        <CardHeader title="Projects" description={`${extraction.projects.length} project${extraction.projects.length === 1 ? "" : "s"} found.`} />
        <div className="space-y-4">
          {extraction.projects.map((project, index) => (
            <div key={index} className={cn("rounded-lg border border-line p-3", project.rejected && "opacity-50")}>
              <div className="flex flex-wrap items-end justify-between gap-2">
                <Input label="Project" value={project.name} onChange={(event) => patchList("projects", index, { name: event.target.value })} wrapperClassName="flex-1 min-w-[220px]" />
                <Button size="sm" variant="ghost" onClick={() => patchList("projects", index, { rejected: !project.rejected })}>
                  {project.rejected ? "Include" : "Leave out"}
                </Button>
              </div>
              {project.technologies.length > 0 && (
                <div className="mt-2 flex flex-wrap gap-1">
                  {project.technologies.map((tech) => (
                    <Badge key={tech}>{tech}</Badge>
                  ))}
                </div>
              )}
              <ul className="mt-2 list-disc space-y-1 pl-5 text-[13px] text-ink/85">
                {project.bullets.map((bullet) => (
                  <li key={bullet}>{bullet}</li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      </Card>

      {extraction.certifications.length > 0 && (
        <Card>
          <CardHeader title="Certifications" />
          <ul className="space-y-1 text-[13.5px]">
            {extraction.certifications.map((cert) => (
              <li key={cert.name}>
                {cert.name}
                {cert.issuer ? ` · ${cert.issuer}` : ""}
              </li>
            ))}
          </ul>
        </Card>
      )}

      <div className="sticky bottom-4 flex flex-wrap items-center justify-between gap-2 rounded-xl border border-line bg-surface/95 px-4 py-3 shadow-pop backdrop-blur">
        <Button variant="ghost" onClick={onBack}>Back</Button>
        <Button onClick={onSave} loading={busy === "save"}>Looks right, save to my profile</Button>
      </div>
    </div>
  );
}

export default function OnboardingPage() {
  return (
    <Suspense fallback={<LoadingBlock />}>
      <Onboarding />
    </Suspense>
  );
}
