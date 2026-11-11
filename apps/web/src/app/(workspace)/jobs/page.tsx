"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useMemo, useState } from "react";
import { Briefcase, ExternalLink, Plus, Radar, RotateCcw, Search, Send, Sparkles } from "lucide-react";
import { DiscoveryPanel, ImportJobModal, JobRow, useDiscovery } from "@/components/jobs";
import { PortalCapture } from "@/components/portal-capture";
import { Badge, Button, Card, ChipGroup, EmptyState, ErrorState, Input, LoadingBlock, Notice, PageHeader, Select, Switch, useToast } from "@/components/ui";
import { api } from "@/lib/api";
import { errorMessage, useApi } from "@/lib/hooks";
import type { Health, JobCard, JobPage, ProfileOptions, SearchProfile } from "@/lib/types";

type Filters = {
  families: string[];
  levels: string[];
  scopes: string[];
  posted: string;
  q: string;
  sort: string;
  saved: boolean;
  samples: boolean;
};

const PRIMARY_FAMILIES = ["software", "backend", "full_stack", "data_engineering", "data_science", "data_analytics", "ml_ai", "cloud_devops"];

function fromProfile(profile: SearchProfile): Filters {
  return {
    families: profile.role_families,
    levels: profile.levels,
    scopes: profile.location_scopes,
    posted: profile.posted_within_days ? String(profile.posted_within_days) : "0",
    q: "",
    sort: "relevance",
    saved: false,
    samples: false,
  };
}

function JobsView() {
  const router = useRouter();
  const params = useSearchParams();
  const toast = useToast();
  const { data: options, error: optionsError, reload: reloadOptions } = useApi<ProfileOptions>("/search-profiles/options");
  const { data: profiles, error: profilesError, reload: reloadProfiles } = useApi<SearchProfile[]>("/search-profiles");
  const { data: health } = useApi<Health>("/health");
  const { data: sources } = useApi<{ external_searches: Array<{ platform: string; url: string; note: string; kind: string }> }>("/jobs/sources");
  const [profileId, setProfileId] = useState<string>("");
  const [filters, setFilters] = useState<Filters | null>(null);
  const [page, setPage] = useState<JobPage | null>(null);
  const [items, setItems] = useState<JobCard[]>([]);
  const [pageNumber, setPageNumber] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [selected, setSelected] = useState<string[]>([]);
  const [importOpen, setImportOpen] = useState(false);
  const [moreRoles, setMoreRoles] = useState(false);
  const [preparing, setPreparing] = useState(false);
  const [query, setQuery] = useState("");

  const profile = useMemo(() => profiles?.find((item) => item.id === profileId) || profiles?.find((item) => item.is_default) || null, [profiles, profileId]);

  useEffect(() => {
    if (profile && (!filters || profile.id !== profileId)) {
      setProfileId(profile.id);
      setFilters(fromProfile(profile));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [profile]);

  const load = useCallback(
    async (next: Filters, number = 1) => {
      setLoading(true);
      const search = new URLSearchParams({
        families: next.families.join(","),
        levels: next.levels.join(","),
        scopes: next.scopes.join(","),
        posted_within_days: next.posted,
        q: next.q,
        sort: next.sort,
        saved: String(next.saved),
        include_samples: String(next.samples),
        page_size: "25",
        page_number: String(number),
      });
      try {
        const result = await api<JobPage>(`/jobs?${search.toString()}`);
        setPage(result);
        setItems((current) => (number === 1 ? result.items : [...current, ...result.items]));
        setPageNumber(number);
        setError("");
      } catch (err) {
        setError(errorMessage(err));
      } finally {
        setLoading(false);
      }
    },
    [],
  );

  useEffect(() => {
    if (filters) load(filters, 1);
  }, [filters, load]);

  const reloadQuietly = useCallback(() => {
    if (filters) load(filters, 1);
  }, [filters, load]);

  const discovery = useDiscovery(() => {
    if (filters) load(filters, 1);
    toast("Job search finished. Results are updated.", "good");
  });

  useEffect(() => {
    if (params.get("discover") === "1" && profile && !discovery.running) {
      discovery.start(profile.id).catch((err) => setError(errorMessage(err)));
      router.replace("/jobs");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [params, profile]);

  function update(patch: Partial<Filters>) {
    if (!filters) return;
    setSelected([]);
    setFilters({ ...filters, ...patch });
  }

  const dirty = useMemo(() => {
    if (!filters || !profile) return false;
    const base = fromProfile(profile);
    return (
      base.families.join() !== filters.families.join() ||
      base.levels.join() !== filters.levels.join() ||
      base.scopes.join() !== filters.scopes.join() ||
      base.posted !== filters.posted
    );
  }, [filters, profile]);

  async function saveFiltersToProfile() {
    if (!filters || !profile) return;
    await api(`/search-profiles/${profile.id}`, {
      method: "PUT",
      body: JSON.stringify({ role_families: filters.families, levels: filters.levels, location_scopes: filters.scopes, posted_within_days: Number(filters.posted) || null }),
    });
    await reloadProfiles();
    toast(`Saved to “${profile.name}”. Future searches use these settings.`, "good");
  }

  async function toggleSave(job: JobCard) {
    await api(`/jobs/${job.id}/save`, { method: job.saved ? "DELETE" : "POST" });
    setItems((current) => current.map((item) => (item.id === job.id ? { ...item, saved: !job.saved } : item)));
  }

  async function dismiss(job: JobCard) {
    await api(`/jobs/${job.id}/dismiss`, { method: "POST" });
    setItems((current) => current.filter((item) => item.id !== job.id));
    toast(
      <span>
        Hidden {job.title}.{" "}
        <button className="font-medium text-accent" onClick={async () => { await api(`/jobs/${job.id}/dismiss`, { method: "DELETE" }); if (filters) load(filters, 1); }}>
          Undo
        </button>
      </span>,
    );
  }

  async function prepareSelected() {
    setPreparing(true);
    try {
      const result = await api<{ results: Array<{ ok: boolean; error?: string }>; open_questions: number }>("/applications/batch", { method: "POST", body: JSON.stringify({ job_ids: selected }) });
      const ok = result.results.filter((item) => item.ok).length;
      toast(`Prepared ${ok} draft${ok === 1 ? "" : "s"}. Nothing was submitted.${result.open_questions ? ` ${result.open_questions} question(s) need your answer.` : ""}`, "good");
      router.push(result.open_questions ? "/questions" : "/applications");
    } catch (err) {
      toast(errorMessage(err), "bad");
    } finally {
      setPreparing(false);
    }
  }

  function askAssistant() {
    try {
      sessionStorage.setItem("assistant-context", JSON.stringify({ selected_job_ids: selected }));
    } catch {
      /* ignore */
    }
    router.push("/assistant?context=selection");
  }

  const startupError = optionsError || profilesError;
  if (startupError) return <ErrorState message={startupError} onRetry={() => { reloadOptions(); reloadProfiles(); }} />;
  if (!options || !profiles || !filters) return <LoadingBlock label="Loading jobs" />;

  const familyOptions = options.role_families.filter((item) => item.value !== "technology_general" && (moreRoles || PRIMARY_FAMILIES.includes(item.value) || filters.families.includes(item.value)));
  const levelOptions = options.levels;
  const scopeOptions = options.location_scopes;
  const hidden = page?.hidden;
  const hiddenLevels = hidden ? Object.entries(hidden.by_level).filter(([, count]) => count > 0) : [];
  const hiddenScopes = hidden ? Object.entries(hidden.by_scope).filter(([, count]) => count > 0) : [];

  return (
    <div>
      <PageHeader
        title="Jobs"
        description="Co-op, internship, new-grad, and junior roles from employer career sites, Canadian job boards, and remote boards, ranked for your search."
        actions={
          <>
            {profiles.length > 1 && (
              <Select
                aria-label="Saved search"
                value={profileId}
                onChange={(event) => {
                  const next = profiles.find((item) => item.id === event.target.value);
                  if (next) {
                    setProfileId(next.id);
                    setFilters(fromProfile(next));
                  }
                }}
                options={profiles.map((item) => ({ value: item.id, label: item.name }))}
                wrapperClassName="w-48"
              />
            )}
            <Button variant="secondary" icon={<Plus className="h-4 w-4" />} onClick={() => setImportOpen(true)}>
              Add a job
            </Button>
            <Button icon={<Radar className="h-4 w-4" />} loading={discovery.running} onClick={() => discovery.start(profileId).catch((err) => setError(errorMessage(err)))}>
              {discovery.running ? "Searching…" : "Find new jobs"}
            </Button>
          </>
        }
      />
      <div className="mb-5 space-y-3">
        <DiscoveryPanel status={discovery.status} running={discovery.running} />
        <PortalCapture onSaved={reloadQuietly} />
      </div>
      {error && <Notice tone="bad" className="mb-4">{error}</Notice>}

      <div className="grid gap-6 lg:grid-cols-[264px_1fr]">
        <aside className="space-y-5 lg:sticky lg:top-6 lg:self-start">
          <form
            onSubmit={(event) => {
              event.preventDefault();
              update({ q: query });
            }}
            className="relative"
          >
            <Search className="pointer-events-none absolute left-2.5 top-2.5 h-4 w-4 text-faint" />
            <Input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Keyword, company, or tool" className="pl-8" />
          </form>
          <FilterGroup title="Role">
            <ChipGroup size="sm" options={familyOptions} value={filters.families} onChange={(value) => update({ families: value })} />
            <button className="mt-1.5 text-[12px] text-muted hover:text-ink" onClick={() => setMoreRoles((value) => !value)}>
              {moreRoles ? "Fewer roles" : "More roles (frontend, mobile, QA, security, IT)"}
            </button>
          </FilterGroup>
          <FilterGroup title="Level">
            <ChipGroup size="sm" options={levelOptions} value={filters.levels} onChange={(value) => update({ levels: value })} />
          </FilterGroup>
          <FilterGroup title="Location">
            <ChipGroup size="sm" options={scopeOptions} value={filters.scopes} onChange={(value) => update({ scopes: value })} />
          </FilterGroup>
          <div className="grid grid-cols-2 gap-2">
            <Select
              label="Posted"
              value={filters.posted}
              onChange={(event) => update({ posted: event.target.value })}
              options={[{ value: "0", label: "Any time" }, ...options.posted_within_days.map((days) => ({ value: String(days), label: days === 1 ? "Last 24 hours" : `Last ${days} days` }))]}
            />
            <Select
              label="Sort"
              value={filters.sort}
              onChange={(event) => update({ sort: event.target.value })}
              options={[
                { value: "relevance", label: "Best match" },
                { value: "newest", label: "Newest" },
                { value: "match", label: "Skills match" },
              ]}
            />
          </div>
          <div className="space-y-3">
            <Switch checked={filters.saved} onChange={(value) => update({ saved: value })} label="Saved jobs only" />
            {health?.demo_mode && <Switch checked={filters.samples} onChange={(value) => update({ samples: value })} label="Show practice listings" description="Sample data for trying the app. Never real postings." />}
          </div>
          {dirty && (
            <div className="flex gap-2">
              <Button size="sm" variant="subtle" onClick={saveFiltersToProfile}>Save to my search</Button>
              <Button size="sm" variant="ghost" icon={<RotateCcw className="h-3.5 w-3.5" />} onClick={() => profile && setFilters(fromProfile(profile))}>
                Reset
              </Button>
            </div>
          )}
          {sources?.external_searches && (
            <Card padded={false} className="p-4">
              <h3 className="text-[13px] font-semibold">Search elsewhere</h3>
              <p className="mt-0.5 text-[12px] text-muted">These sites do not allow automated reading. Open a saved search, then add postings you like.</p>
              <div className="mt-2 space-y-1">
                {sources.external_searches.slice(0, 9).map((item) => (
                  <a key={item.platform} href={item.url} target="_blank" rel="noreferrer" title={item.note} className="flex items-center justify-between rounded-md px-1.5 py-1 text-[12.5px] hover:bg-surface2">
                    <span className="truncate">{item.platform}</span>
                    <ExternalLink className="h-3 w-3 shrink-0 text-faint" />
                  </a>
                ))}
              </div>
            </Card>
          )}
        </aside>

        <section className="min-w-0">
          <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
            <div className="text-[13.5px] text-muted">
              {loading && !items.length ? "Loading…" : <><span className="font-semibold text-ink">{page?.total ?? 0}</span> jobs match{filters.q ? ` “${filters.q}”` : ""}</>}
              {filters.q && (
                <button className="ml-2 text-accent" onClick={() => { setQuery(""); update({ q: "" }); }}>
                  Clear keyword
                </button>
              )}
            </div>
          </div>
          {hidden && hidden.total > 0 && (
            <div className="mb-3 flex flex-wrap items-center gap-1.5 text-[12.5px] text-muted">
              <span>Hidden by your filters:</span>
              {hiddenLevels.map(([level, count]) => (
                <button key={level} onClick={() => update({ levels: [...filters.levels, level] })} className="rounded-md border border-dashed border-line px-1.5 py-0.5 hover:border-accent hover:text-accent" title="Show these">
                  {count} {options.levels.find((item) => item.value === level)?.label.toLowerCase() || level}
                </button>
              ))}
              {hiddenScopes.map(([scope, count]) => (
                <button key={scope} onClick={() => update({ scopes: [...filters.scopes, scope] })} className="rounded-md border border-dashed border-line px-1.5 py-0.5 hover:border-accent hover:text-accent" title="Show these">
                  {count} {options.location_scopes.find((item) => item.value === scope)?.label.toLowerCase() || scope}
                </button>
              ))}
              {hidden.older > 0 && (
                <button onClick={() => update({ posted: "0" })} className="rounded-md border border-dashed border-line px-1.5 py-0.5 hover:border-accent hover:text-accent">
                  {hidden.older} older
                </button>
              )}
              {hidden.other_roles > 0 && <span className="px-1">{hidden.other_roles} other roles</span>}
            </div>
          )}
          {selected.length > 0 && (
            <div className="sticky top-14 z-10 mb-3 flex flex-wrap items-center justify-between gap-2 rounded-xl border border-accent/30 bg-accent-soft px-4 py-2.5 lg:top-4">
              <span className="text-[13.5px] font-medium text-accent">{selected.length} selected</span>
              <div className="flex flex-wrap gap-2">
                <Button size="sm" variant="secondary" icon={<Sparkles className="h-3.5 w-3.5" />} onClick={askAssistant}>
                  Ask the assistant
                </Button>
                <Button size="sm" icon={<Send className="h-3.5 w-3.5" />} loading={preparing} onClick={prepareSelected}>
                  Prepare {selected.length} application{selected.length === 1 ? "" : "s"}
                </Button>
                <Button size="sm" variant="ghost" onClick={() => setSelected([])}>Clear</Button>
              </div>
            </div>
          )}
          {!loading && items.length === 0 ? (
            <EmptyState
              icon={<Briefcase className="h-5 w-5" />}
              title={page && page.hidden.total > 0 ? "No jobs match these filters" : "No jobs yet"}
              action={
                <Button icon={<Radar className="h-4 w-4" />} loading={discovery.running} onClick={() => discovery.start(profileId)}>
                  Find new jobs
                </Button>
              }
            >
              {page && page.hidden.total > 0 ? "Try widening the level or location filters, or run a new search." : "Run a search across employer career sites and Canadian job boards. It takes about a minute."}
            </EmptyState>
          ) : (
            <div className="space-y-3">
              {items.map((job) => (
                <JobRow
                  key={job.id}
                  job={job}
                  selected={selected.includes(job.id)}
                  onSelect={(value) => setSelected((current) => (value ? [...current, job.id] : current.filter((id) => id !== job.id)))}
                  onSave={toggleSave}
                  onDismiss={dismiss}
                />
              ))}
              {page && items.length < page.total && (
                <div className="flex justify-center pt-2">
                  <Button variant="secondary" loading={loading} onClick={() => load(filters, pageNumber + 1)}>
                    Show more ({page.total - items.length} left)
                  </Button>
                </div>
              )}
            </div>
          )}
          <p className="mt-6 text-[12px] text-muted">
            Match is how well a role fits your saved search (role, level, location, freshness) plus how many required skills are already on your profile. It is not an ATS score or a hiring probability.{" "}
            <Badge>Practice listing</Badge> marks sample data.
          </p>
        </section>
      </div>
      <ImportJobModal open={importOpen} onClose={() => setImportOpen(false)} onImported={(id) => router.push(`/jobs/${id}`)} />
    </div>
  );
}

function FilterGroup({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="mb-1.5 text-[12px] font-semibold uppercase tracking-wide text-faint">{title}</div>
      {children}
    </div>
  );
}

export default function JobsPage() {
  return (
    <Suspense fallback={<LoadingBlock label="Loading jobs" />}>
      <JobsView />
    </Suspense>
  );
}
