"use client";

import { useEffect, useMemo, useState } from "react";
import { Building2, Globe, Plus, Star, Trash2 } from "lucide-react";
import { SearchFields } from "@/components/search-fields";
import { Badge, Button, Card, CardHeader, ErrorState, Input, LoadingBlock, Notice, PageHeader, Switch, Tabs, useToast } from "@/components/ui";
import { api } from "@/lib/api";
import { errorMessage, useApi } from "@/lib/hooks";
import type { ProfileOptions, SearchProfile } from "@/lib/types";
import { cn } from "@/lib/utils";

type Sources = {
  boards: Array<{ key: string; source_key: string; label: string; description: string; enabled: boolean; configured: boolean; needs_key: boolean }>;
  employers: Array<{ key: string; name: string; ats: string; source_key: string; enabled: boolean; custom: boolean; country: string | null; tags: string[]; careers_url: string }>;
  external_searches: Array<{ platform: string; url: string; note: string; kind: string }>;
};

const ATS_LABEL: Record<string, string> = { workday: "Workday", greenhouse: "Greenhouse", lever: "Lever", ashby: "Ashby", successfactors: "SuccessFactors", amazon: "Amazon Jobs", ibm: "IBM Careers", jibe: "Careers API" };

export default function SearchesPage() {
  const toast = useToast();
  const { data: options, error: optionsError } = useApi<ProfileOptions>("/search-profiles/options");
  const { data: profiles, reload, error: profilesError } = useApi<SearchProfile[]>("/search-profiles");
  const { data: sources, reload: reloadSources, setData: setSources } = useApi<Sources>("/jobs/sources");
  const [tab, setTab] = useState("searches");
  const [activeId, setActiveId] = useState<string>("");
  const [draft, setDraft] = useState<SearchProfile | null>(null);
  const [saving, setSaving] = useState(false);
  const [newUrl, setNewUrl] = useState("");
  const [newName, setNewName] = useState("");
  const [adding, setAdding] = useState(false);
  const [filter, setFilter] = useState("");

  useEffect(() => {
    if (profiles && !draft) {
      const first = profiles.find((item) => item.is_default) || profiles[0];
      setActiveId(first.id);
      setDraft(first);
    }
  }, [profiles, draft]);

  const employers = useMemo(() => (sources?.employers || []).filter((item) => item.name.toLowerCase().includes(filter.toLowerCase())), [sources, filter]);

  if (optionsError || profilesError) return <ErrorState message={optionsError || profilesError} onRetry={() => window.location.reload()} />;
  if (!options || !profiles || !draft) return <LoadingBlock />;

  function select(profile: SearchProfile) {
    setActiveId(profile.id);
    setDraft(profile);
  }

  async function save() {
    if (!draft) return;
    setSaving(true);
    try {
      await api(`/search-profiles/${draft.id}`, { method: "PUT", body: JSON.stringify(draft) });
      toast("Search saved.", "good");
      await reload();
    } catch (err) {
      toast(errorMessage(err), "bad");
    } finally {
      setSaving(false);
    }
  }

  async function create() {
    const created = await api<SearchProfile>("/search-profiles", { method: "POST", body: JSON.stringify({ name: `Search ${profiles!.length + 1}` }) });
    await reload();
    select(created);
  }

  async function toggleSource(sourceKey: string, enabled: boolean) {
    await api("/jobs/sources", { method: "PUT", body: JSON.stringify({ overrides: { [sourceKey]: enabled } }) });
    setSources((current) =>
      current
        ? {
            ...current,
            employers: current.employers.map((item) => (item.source_key === sourceKey ? { ...item, enabled } : item)),
            boards: current.boards.map((item) => (item.source_key === sourceKey ? { ...item, enabled } : item)),
          }
        : current,
    );
  }

  async function addEmployer() {
    setAdding(true);
    try {
      const employer = await api<{ name: string }>("/jobs/sources/employers", { method: "POST", body: JSON.stringify({ url: newUrl, name: newName || null }) });
      toast(`Now monitoring ${employer.name}.`, "good");
      setNewUrl("");
      setNewName("");
      await reloadSources();
    } catch (err) {
      toast(errorMessage(err), "bad");
    } finally {
      setAdding(false);
    }
  }

  return (
    <div>
      <PageHeader title="Job searches" description="Save several searches (for example a software co-op search and a data new-grad search) and choose which sources ApplyPilot reads." />
      <Tabs items={[{ value: "searches", label: "Saved searches", count: profiles.length }, { value: "sources", label: "Sources", count: sources ? sources.employers.filter((item) => item.enabled).length + sources.boards.filter((item) => item.enabled).length : undefined }]} value={tab} onChange={setTab} className="mb-5" />

      {tab === "searches" && (
        <div className="grid gap-6 lg:grid-cols-[240px_1fr]">
          <div className="space-y-2">
            {profiles.map((profile) => (
              <button key={profile.id} onClick={() => select(profile)} className={cn("w-full rounded-lg border px-3 py-2.5 text-left transition", profile.id === activeId ? "border-accent bg-accent-soft" : "border-line bg-surface hover:border-faint")}>
                <div className="flex items-center justify-between gap-2">
                  <span className="truncate text-[13.5px] font-medium">{profile.name}</span>
                  {profile.is_default && <Badge tone="accent">Default</Badge>}
                </div>
                <div className="mt-0.5 truncate text-[12px] text-muted">{profile.role_families.length} fields · {profile.levels.length} levels · {profile.city}</div>
              </button>
            ))}
            <Button variant="secondary" className="w-full" icon={<Plus className="h-4 w-4" />} onClick={create}>
              New search
            </Button>
          </div>
          <Card>
            <CardHeader
              title={<Input value={draft.name} onChange={(event) => setDraft({ ...draft, name: event.target.value })} className="h-8 text-[15px] font-semibold" />}
              actions={
                <>
                  {!draft.is_default && (
                    <Button size="sm" variant="ghost" icon={<Star className="h-3.5 w-3.5" />} onClick={async () => { await api(`/search-profiles/${draft.id}/default`, { method: "POST" }); await reload(); setDraft({ ...draft, is_default: true }); toast("Now your default search.", "good"); }}>
                      Make default
                    </Button>
                  )}
                  {profiles.length > 1 && (
                    <Button size="sm" variant="ghost" icon={<Trash2 className="h-3.5 w-3.5" />} onClick={async () => { if (!confirm("Delete this search?")) return; await api(`/search-profiles/${draft.id}`, { method: "DELETE" }); setDraft(null); await reload(); }}>
                      Delete
                    </Button>
                  )}
                </>
              }
            />
            <SearchFields draft={draft} options={options} onChange={setDraft} />
            <div className="mt-6 flex justify-end">
              <Button onClick={save} loading={saving}>Save search</Button>
            </div>
          </Card>
        </div>
      )}

      {tab === "sources" && sources && (
        <div className="space-y-6">
          <Card>
            <CardHeader title="Job boards" description="Canadian and remote boards searched with your saved search." />
            <div className="divide-y divide-line">
              {sources.boards.map((board) => (
                <div key={board.key} className="flex items-center justify-between gap-3 py-3">
                  <div className="flex items-center gap-3">
                    <Globe className="h-4 w-4 text-faint" />
                    <div>
                      <div className="text-[13.5px] font-medium">{board.label}</div>
                      <div className="text-[12px] text-muted">{board.description}</div>
                    </div>
                  </div>
                  {board.needs_key ? <Badge tone="warn">Needs an API key (see Settings)</Badge> : <Switch checked={board.enabled} onChange={(value) => toggleSource(board.source_key, value)} />}
                </div>
              ))}
            </div>
          </Card>

          <Card>
            <CardHeader title="Employers monitored directly" description="Postings read straight from each company's own careers site, so they are current and link to the real application." actions={<Input placeholder="Filter employers" value={filter} onChange={(event) => setFilter(event.target.value)} wrapperClassName="w-56" />} />
            <div className="grid gap-x-6 sm:grid-cols-2">
              {employers.map((employer) => (
                <div key={employer.source_key} className="flex items-center justify-between gap-3 border-b border-line py-2.5">
                  <div className="flex min-w-0 items-center gap-2.5">
                    <Building2 className="h-4 w-4 shrink-0 text-faint" />
                    <div className="min-w-0">
                      <div className="flex items-center gap-1.5 truncate text-[13.5px] font-medium">
                        {employer.name}
                        {employer.custom && <Badge tone="accent">Added by you</Badge>}
                      </div>
                      <div className="text-[12px] text-muted">{ATS_LABEL[employer.ats] || employer.ats}{employer.country === "canada" ? " · Canadian employer" : ""}</div>
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    {employer.custom && (
                      <button className="text-faint hover:text-danger" aria-label={`Remove ${employer.name}`} onClick={async () => { await api(`/jobs/sources/employers/${employer.key}`, { method: "DELETE" }); await reloadSources(); }}>
                        <Trash2 className="h-3.5 w-3.5" />
                      </button>
                    )}
                    <Switch checked={employer.enabled} onChange={(value) => toggleSource(employer.source_key, value)} />
                  </div>
                </div>
              ))}
            </div>
            <div className="mt-5 rounded-lg bg-surface2 p-4">
              <div className="mb-2 text-[13.5px] font-medium">Add an employer</div>
              <p className="mb-3 text-[12.5px] text-muted">Paste the careers page of any company that uses Workday, Greenhouse, Lever, or Ashby, for example https://company.wd3.myworkdayjobs.com/Careers or https://jobs.lever.co/company.</p>
              <div className="grid gap-2 sm:grid-cols-[1fr_200px_auto]">
                <Input placeholder="Careers page URL" value={newUrl} onChange={(event) => setNewUrl(event.target.value)} />
                <Input placeholder="Company name (optional)" value={newName} onChange={(event) => setNewName(event.target.value)} />
                <Button onClick={addEmployer} loading={adding} disabled={!newUrl}>Add</Button>
              </div>
            </div>
          </Card>

          <Card>
            <CardHeader title="Sites ApplyPilot cannot read" description="LinkedIn, Indeed, Glassdoor, and university portals prohibit automated access. Use these saved searches, then add postings with the import button." />
            <div className="grid gap-2 sm:grid-cols-2">
              {sources.external_searches.map((item) => (
                <a key={item.platform} href={item.url} target="_blank" rel="noreferrer" className="rounded-lg border border-line p-3 hover:border-accent/40">
                  <div className="text-[13.5px] font-medium">{item.platform}</div>
                  <div className="mt-0.5 text-[12px] text-muted">{item.note}</div>
                </a>
              ))}
            </div>
            <Notice tone="neutral" className="mt-4">Listing access never includes permission to submit applications. ApplyPilot prepares drafts and you submit them.</Notice>
          </Card>
        </div>
      )}
    </div>
  );
}
