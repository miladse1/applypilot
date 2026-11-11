"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { BarChart3, Pencil, Plus, Trash2, X } from "lucide-react";
import { Badge, Button, Card, CardHeader, Input, LoadingBlock, Modal, Notice, PageHeader, Select, TagInput, Textarea, useToast } from "@/components/ui";
import { api } from "@/lib/api";
import { dateLabel } from "@/lib/format";
import { errorMessage, useApi } from "@/lib/hooks";
import type { Profile, ProfileSkill } from "@/lib/types";

type Role = Profile["experience"][number];
type ProjectRow = Profile["projects"][number];
type School = Profile["education"][number];

const STATUS_GROUPS: Array<{ status: string; title: string; description: string }> = [
  { status: "confirmed", title: "Skills you have", description: "Used for matching and on tailored resumes." },
  { status: "in_progress", title: "Learning", description: "Kept off your resume until you confirm them." },
  { status: "not_possessed", title: "You said you don't have", description: "ApplyPilot will not ask about these again." },
];

export default function ProfilePage() {
  const toast = useToast();
  const { data: profile, reload, error } = useApi<Profile>("/profile");
  const { data: catalog } = useApi<Array<{ name: string }>>("/profile/skill-catalog");
  const { data: authorization, reload: reloadAuth } = useApi<{ canada?: string; us?: string }>("/profile/work-authorization");
  const [contact, setContact] = useState<Partial<Profile>>({});
  const [auth, setAuth] = useState<{ canada?: string; us?: string }>({});
  const [newSkills, setNewSkills] = useState<string[]>([]);
  const [newStatus, setNewStatus] = useState("confirmed");
  const [role, setRole] = useState<Role | null>(null);
  const [project, setProject] = useState<ProjectRow | null>(null);
  const [school, setSchool] = useState<School | null>(null);

  useEffect(() => {
    if (profile) setContact({ full_name: profile.full_name, phone: profile.phone, location: profile.location, linkedin_url: profile.linkedin_url, github_url: profile.github_url, portfolio_url: profile.portfolio_url, headline: profile.headline, summary: profile.summary });
  }, [profile]);
  useEffect(() => {
    if (authorization) setAuth(authorization);
  }, [authorization]);

  const skillsByStatus = useMemo(() => {
    const map: Record<string, ProfileSkill[]> = {};
    for (const skill of profile?.skills || []) {
      const key = ["confirmed", "in_progress", "not_possessed"].includes(skill.confirmation_status) ? skill.confirmation_status : "other";
      (map[key] ||= []).push(skill);
    }
    return map;
  }, [profile]);

  if (!profile) return error ? <Notice tone="bad">{error}</Notice> : <LoadingBlock label="Loading profile" />;

  async function act(action: () => Promise<unknown>, message: string) {
    try {
      await action();
      toast(message, "good");
      await reload();
    } catch (err) {
      toast(errorMessage(err), "bad");
    }
  }

  async function addSkills() {
    for (const name of newSkills) {
      await api("/profile/skills", { method: "POST", body: JSON.stringify({ name, confirmation_status: newStatus }) });
    }
    setNewSkills([]);
    toast("Skills saved.", "good");
    await reload();
  }

  return (
    <div>
      <PageHeader
        title="Professional profile"
        description="Everything ApplyPilot knows about you. Tailored resumes and answers use only what is here."
        actions={
          <Link href="/career" className="inline-flex items-center gap-1.5 text-[13px] text-accent hover:underline">
            <BarChart3 className="h-4 w-4" /> Skill gaps across your jobs
          </Link>
        }
      />
      <div className="space-y-6">
        <Card>
          <CardHeader title="Contact and links" description="These replace any placeholders on your resume." />
          <div className="grid gap-3 sm:grid-cols-2">
            <Input label="Full name" value={contact.full_name || ""} onChange={(event) => setContact({ ...contact, full_name: event.target.value })} />
            <Input label="Phone" value={contact.phone || ""} onChange={(event) => setContact({ ...contact, phone: event.target.value })} />
            <Input label="City" value={contact.location || ""} onChange={(event) => setContact({ ...contact, location: event.target.value })} placeholder="Toronto, ON" />
            <Input label="LinkedIn" value={contact.linkedin_url || ""} onChange={(event) => setContact({ ...contact, linkedin_url: event.target.value })} placeholder="linkedin.com/in/…" />
            <Input label="GitHub" value={contact.github_url || ""} onChange={(event) => setContact({ ...contact, github_url: event.target.value })} placeholder="github.com/…" />
            <Input label="Portfolio" value={contact.portfolio_url || ""} onChange={(event) => setContact({ ...contact, portfolio_url: event.target.value })} />
            <Textarea label="Summary" value={contact.summary || ""} onChange={(event) => setContact({ ...contact, summary: event.target.value })} wrapperClassName="sm:col-span-2" />
          </div>
          <div className="mt-3 flex justify-end">
            <Button onClick={() => act(() => api("/profile", { method: "PATCH", body: JSON.stringify(contact) }), "Profile saved.")}>Save</Button>
          </div>
        </Card>

        <Card>
          <CardHeader title="Work authorization" description="Asked by most applications. ApplyPilot never guesses these; it uses your answers and filters out roles you cannot take." />
          <div className="grid gap-3 sm:grid-cols-2">
            <Select
              label="In Canada"
              value={auth.canada || ""}
              onChange={(event) => setAuth({ ...auth, canada: event.target.value })}
              options={[
                { value: "", label: "Not set" },
                { value: "citizen", label: "Canadian citizen" },
                { value: "permanent_resident", label: "Permanent resident" },
                { value: "work_permit", label: "Open work permit" },
                { value: "study_permit", label: "Study permit (co-op work permit)" },
                { value: "none", label: "Not authorized" },
              ]}
            />
            <Select
              label="In the United States"
              value={auth.us || ""}
              onChange={(event) => setAuth({ ...auth, us: event.target.value })}
              options={[
                { value: "", label: "Not set" },
                { value: "authorized", label: "Authorized to work" },
                { value: "needs_sponsorship", label: "Would need sponsorship" },
                { value: "not_authorized", label: "Not authorized" },
              ]}
            />
          </div>
          <p className="mt-2 text-[12px] text-muted">US-only remote roles are hidden unless you are authorized to work in the US.</p>
          <div className="mt-3 flex justify-end">
            <Button variant="secondary" onClick={async () => { await api("/profile/work-authorization", { method: "PUT", body: JSON.stringify(auth) }); await reloadAuth(); toast("Work authorization saved.", "good"); }}>
              Save
            </Button>
          </div>
        </Card>

        <Card>
          <CardHeader title="Skills" description="Skills come from your resume or from questions you answered while applying." />
          <div className="space-y-5">
            {STATUS_GROUPS.map((group) => {
              const rows = skillsByStatus[group.status] || [];
              if (!rows.length) return null;
              return (
                <div key={group.status}>
                  <div className="mb-1.5 text-[13px] font-semibold">
                    {group.title} <span className="font-normal text-muted">· {group.description}</span>
                  </div>
                  <div className="flex flex-wrap gap-1.5">
                    {rows.map((skill) => (
                      <span key={skill.id} title={skill.context || (skill.source === "resume_extracted" ? "From your resume" : "Confirmed by you")} className="inline-flex items-center gap-1 rounded-md border border-line bg-surface2 px-2 py-1 text-[13px]">
                        {skill.name}
                        {skill.source !== "resume_extracted" && <span className="text-[10.5px] text-accent">you</span>}
                        <button onClick={() => act(() => api(`/profile/skills/${skill.id}`, { method: "DELETE" }), `Removed ${skill.name}.`)} className="text-faint hover:text-danger" aria-label={`Remove ${skill.name}`}>
                          <X className="h-3 w-3" />
                        </button>
                      </span>
                    ))}
                  </div>
                </div>
              );
            })}
            <div className="grid gap-3 border-t border-line pt-4 sm:grid-cols-[1fr_200px_auto] sm:items-end">
              <TagInput label="Add skills" value={newSkills} onChange={setNewSkills} suggestions={(catalog || []).map((item) => item.name)} />
              <Select
                label="Status"
                value={newStatus}
                onChange={(event) => setNewStatus(event.target.value)}
                options={[
                  { value: "confirmed", label: "I have this" },
                  { value: "in_progress", label: "I'm learning it" },
                  { value: "not_possessed", label: "I don't have it" },
                ]}
              />
              <Button onClick={addSkills} disabled={!newSkills.length}>Add</Button>
            </div>
          </div>
        </Card>

        <Card>
          <CardHeader title="Experience" actions={<Button size="sm" variant="secondary" icon={<Plus className="h-3.5 w-3.5" />} onClick={() => setRole({ id: "", employer: "", title: "", location: "", start_date: null, end_date: null, is_current: false, responsibilities: [], technologies: [], source: "user_reported" })}>Add</Button>} />
          <div className="divide-y divide-line">
            {profile.experience.map((item) => (
              <div key={item.id} className="py-3">
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <div>
                    <div className="text-[14px] font-medium">{item.title} · {item.employer}</div>
                    <div className="text-[12.5px] text-muted">{[item.location, [dateLabel(item.start_date), item.is_current ? "Present" : dateLabel(item.end_date)].filter(Boolean).join(" – ")].filter(Boolean).join(" · ")}</div>
                  </div>
                  <div className="flex gap-1">
                    <Button size="sm" variant="ghost" icon={<Pencil className="h-3.5 w-3.5" />} onClick={() => setRole(item)} />
                    <Button size="sm" variant="ghost" icon={<Trash2 className="h-3.5 w-3.5" />} onClick={() => confirm("Remove this role from your profile?") && act(() => api(`/profile/experience/${item.id}`, { method: "DELETE" }), "Role removed.")} />
                  </div>
                </div>
                <ul className="mt-1.5 list-disc space-y-0.5 pl-5 text-[13px] text-ink/85">
                  {item.responsibilities.map((bullet) => <li key={bullet}>{bullet}</li>)}
                </ul>
              </div>
            ))}
            {profile.experience.length === 0 && <p className="py-2 text-[13px] text-muted">No roles yet.</p>}
          </div>
        </Card>

        <Card>
          <CardHeader title="Projects" actions={<Button size="sm" variant="secondary" icon={<Plus className="h-3.5 w-3.5" />} onClick={() => setProject({ id: "", name: "", description: "", technologies: [], responsibilities: "", results: "", url: null, source: "user_reported" })}>Add</Button>} />
          <div className="divide-y divide-line">
            {profile.projects.map((item) => (
              <div key={item.id} className="py-3">
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <div>
                    <div className="text-[14px] font-medium">{item.name}</div>
                    <div className="mt-1 flex flex-wrap gap-1">{item.technologies.map((tech) => <Badge key={tech}>{tech}</Badge>)}</div>
                  </div>
                  <div className="flex gap-1">
                    <Button size="sm" variant="ghost" icon={<Pencil className="h-3.5 w-3.5" />} onClick={() => setProject(item)} />
                    <Button size="sm" variant="ghost" icon={<Trash2 className="h-3.5 w-3.5" />} onClick={() => confirm("Remove this project?") && act(() => api(`/profile/projects/${item.id}`, { method: "DELETE" }), "Project removed.")} />
                  </div>
                </div>
                <ul className="mt-1.5 list-disc space-y-0.5 pl-5 text-[13px] text-ink/85">
                  {(item.responsibilities || item.description).split("\n").filter(Boolean).map((bullet) => <li key={bullet}>{bullet}</li>)}
                </ul>
              </div>
            ))}
          </div>
        </Card>

        <Card>
          <CardHeader title="Education" actions={<Button size="sm" variant="secondary" icon={<Plus className="h-3.5 w-3.5" />} onClick={() => setSchool({ id: "", institution: "", degree: "", program: "", graduation_date: null, coursework: "", achievements: "", source: "user_reported" })}>Add</Button>} />
          <div className="divide-y divide-line">
            {profile.education.map((item) => (
              <div key={item.id} className="flex flex-wrap items-start justify-between gap-2 py-3">
                <div>
                  <div className="text-[14px] font-medium">{item.institution}</div>
                  <div className="text-[13px] text-muted">{[item.degree, item.program].filter(Boolean).join(", ")}{item.graduation_date ? ` · ${dateLabel(item.graduation_date)}` : " · Graduation date not set"}</div>
                  {item.coursework && <div className="mt-1 text-[12.5px] text-muted">Coursework: {item.coursework}</div>}
                </div>
                <div className="flex gap-1">
                  <Button size="sm" variant="ghost" icon={<Pencil className="h-3.5 w-3.5" />} onClick={() => setSchool(item)} />
                  <Button size="sm" variant="ghost" icon={<Trash2 className="h-3.5 w-3.5" />} onClick={() => confirm("Remove this school?") && act(() => api(`/profile/education/${item.id}`, { method: "DELETE" }), "Removed.")} />
                </div>
              </div>
            ))}
          </div>
        </Card>
      </div>

      {role && <RoleEditor role={role} onClose={() => setRole(null)} onSaved={() => { setRole(null); reload(); }} />}
      {project && <ProjectEditor project={project} onClose={() => setProject(null)} onSaved={() => { setProject(null); reload(); }} />}
      {school && <SchoolEditor school={school} onClose={() => setSchool(null)} onSaved={() => { setSchool(null); reload(); }} />}
    </div>
  );
}

function useSave(onSaved: () => void) {
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  return {
    busy,
    async save(path: string, method: string, body: unknown) {
      setBusy(true);
      try {
        await api(path, { method, body: JSON.stringify(body) });
        toast("Saved.", "good");
        onSaved();
      } catch (err) {
        toast(errorMessage(err), "bad");
      } finally {
        setBusy(false);
      }
    },
  };
}

function RoleEditor({ role, onClose, onSaved }: { role: Role; onClose: () => void; onSaved: () => void }) {
  const [draft, setDraft] = useState({ ...role, bullets: role.responsibilities.join("\n") });
  const { busy, save } = useSave(onSaved);
  const body = { employer: draft.employer, title: draft.title, location: draft.location, start_date: draft.start_date, end_date: draft.is_current ? null : draft.end_date, is_current: draft.is_current, responsibilities: draft.bullets.split("\n").map((line) => line.trim()).filter(Boolean), technologies: draft.technologies };
  return (
    <Modal open onClose={onClose} title={role.id ? "Edit role" : "Add a role"} wide footer={<><Button variant="secondary" onClick={onClose}>Cancel</Button><Button loading={busy} disabled={!draft.title || !draft.employer} onClick={() => save(role.id ? `/profile/experience/${role.id}` : "/profile/experience", role.id ? "PUT" : "POST", body)}>Save</Button></>}>
      <div className="grid gap-3 sm:grid-cols-2">
        <Input label="Title" value={draft.title} onChange={(event) => setDraft({ ...draft, title: event.target.value })} />
        <Input label="Employer" value={draft.employer} onChange={(event) => setDraft({ ...draft, employer: event.target.value })} />
        <Input label="Location" value={draft.location || ""} onChange={(event) => setDraft({ ...draft, location: event.target.value })} />
        <div className="grid grid-cols-2 gap-2">
          <Input label="Start" type="month" value={(draft.start_date || "").slice(0, 7)} onChange={(event) => setDraft({ ...draft, start_date: event.target.value ? `${event.target.value}-01` : null })} />
          <Input label="End" type="month" disabled={draft.is_current} value={(draft.end_date || "").slice(0, 7)} onChange={(event) => setDraft({ ...draft, end_date: event.target.value ? `${event.target.value}-01` : null })} />
        </div>
        <label className="flex items-center gap-2 text-[13px] sm:col-span-2">
          <input type="checkbox" checked={draft.is_current} onChange={(event) => setDraft({ ...draft, is_current: event.target.checked })} /> I currently work here
        </label>
        <Textarea label="Bullets (one per line)" value={draft.bullets} onChange={(event) => setDraft({ ...draft, bullets: event.target.value })} wrapperClassName="sm:col-span-2" className="min-h-40" />
      </div>
    </Modal>
  );
}

function ProjectEditor({ project, onClose, onSaved }: { project: ProjectRow; onClose: () => void; onSaved: () => void }) {
  const [draft, setDraft] = useState({ ...project, bullets: (project.responsibilities || project.description || "").split("\n").filter(Boolean).join("\n") });
  const { busy, save } = useSave(onSaved);
  const bullets = draft.bullets.split("\n").map((line) => line.trim()).filter(Boolean);
  const body = { name: draft.name, description: bullets.join(" "), technologies: draft.technologies, responsibilities: bullets.join("\n"), results: draft.results || "", url: draft.url };
  return (
    <Modal open onClose={onClose} title={project.id ? "Edit project" : "Add a project"} wide footer={<><Button variant="secondary" onClick={onClose}>Cancel</Button><Button loading={busy} disabled={!draft.name} onClick={() => save(project.id ? `/profile/projects/${project.id}` : "/profile/projects", project.id ? "PUT" : "POST", body)}>Save</Button></>}>
      <div className="space-y-3">
        <Input label="Name" value={draft.name} onChange={(event) => setDraft({ ...draft, name: event.target.value })} />
        <TagInput label="Technologies" value={draft.technologies} onChange={(value) => setDraft({ ...draft, technologies: value })} />
        <Input label="Link" value={draft.url || ""} onChange={(event) => setDraft({ ...draft, url: event.target.value })} />
        <Textarea label="Bullets (one per line)" value={draft.bullets} onChange={(event) => setDraft({ ...draft, bullets: event.target.value })} className="min-h-40" />
      </div>
    </Modal>
  );
}

function SchoolEditor({ school, onClose, onSaved }: { school: School; onClose: () => void; onSaved: () => void }) {
  const [draft, setDraft] = useState(school);
  const { busy, save } = useSave(onSaved);
  const body = { institution: draft.institution, degree: draft.degree, program: draft.program, graduation_date: draft.graduation_date, coursework: draft.coursework, achievements: draft.achievements };
  return (
    <Modal open onClose={onClose} title={school.id ? "Edit education" : "Add education"} footer={<><Button variant="secondary" onClick={onClose}>Cancel</Button><Button loading={busy} disabled={!draft.institution} onClick={() => save(school.id ? `/profile/education/${school.id}` : "/profile/education", school.id ? "PUT" : "POST", body)}>Save</Button></>}>
      <div className="space-y-3">
        <Input label="School" value={draft.institution} onChange={(event) => setDraft({ ...draft, institution: event.target.value })} />
        <Input label="Degree" value={draft.degree || ""} onChange={(event) => setDraft({ ...draft, degree: event.target.value })} />
        <Input label="Program" value={draft.program || ""} onChange={(event) => setDraft({ ...draft, program: event.target.value })} />
        <Input label="Graduation (expected)" type="month" value={(draft.graduation_date || "").slice(0, 7)} onChange={(event) => setDraft({ ...draft, graduation_date: event.target.value ? `${event.target.value}-01` : null })} />
        <Textarea label="Coursework" value={draft.coursework || ""} onChange={(event) => setDraft({ ...draft, coursework: event.target.value })} />
      </div>
    </Modal>
  );
}
