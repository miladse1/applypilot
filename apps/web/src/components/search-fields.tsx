"use client";

import { useEffect, useState } from "react";
import { Button, Card, CardHeader, ChipGroup, ErrorState, LoadingBlock, Select, TagInput, useToast } from "@/components/ui";
import { api } from "@/lib/api";
import { errorMessage, useApi } from "@/lib/hooks";
import type { ProfileOptions, SearchProfile } from "@/lib/types";

export function SearchSetup({ onDone, onSkip, profileId }: { onDone: () => void; onSkip?: () => void; profileId?: string }) {
  const toast = useToast();
  const { data: options, error: optionsError } = useApi<ProfileOptions>("/search-profiles/options");
  const { data: profiles, error: profilesError } = useApi<SearchProfile[]>("/search-profiles");
  const [draft, setDraft] = useState<SearchProfile | null>(null);
  const [saving, setSaving] = useState(false);
  useEffect(() => {
    if (profiles && !draft) setDraft(profiles.find((item) => item.id === profileId) || profiles.find((item) => item.is_default) || profiles[0]);
  }, [profiles, draft, profileId]);
  if (optionsError || profilesError) return <ErrorState message={optionsError || profilesError} onRetry={() => window.location.reload()} />;
  if (!options || !draft) return <LoadingBlock />;

  async function save() {
    if (!draft) return;
    setSaving(true);
    try {
      await api(`/search-profiles/${draft.id}`, { method: "PUT", body: JSON.stringify(draft) });
      toast("Job search saved.", "good");
      onDone();
    } catch (err) {
      toast(errorMessage(err), "bad");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Card>
      <CardHeader title="What jobs do you want?" description="ApplyPilot searches employer career sites and Canadian job boards with these settings and ranks results by fit." />
      <SearchFields draft={draft} options={options} onChange={setDraft} />
      <div className="mt-6 flex flex-wrap justify-end gap-2">
        {onSkip && <Button variant="ghost" onClick={onSkip}>Skip for now</Button>}
        <Button onClick={save} loading={saving}>Save and find jobs</Button>
      </div>
    </Card>
  );
}

export function SearchFields({ draft, options, onChange }: { draft: SearchProfile; options: ProfileOptions; onChange: (value: SearchProfile) => void }) {
  return (
    <div className="space-y-5">
      <div>
        <div className="mb-1.5 text-[13px] font-medium">Fields</div>
        <ChipGroup options={options.role_families.filter((item) => item.value !== "technology_general")} value={draft.role_families} onChange={(value) => onChange({ ...draft, role_families: value })} />
      </div>
      <div>
        <div className="mb-1.5 text-[13px] font-medium">Levels</div>
        <ChipGroup options={options.levels} value={draft.levels} onChange={(value) => onChange({ ...draft, levels: value })} />
        <p className="mt-1 text-[12px] text-muted">“Level not stated” covers postings that do not say; ApplyPilot checks their years of experience.</p>
      </div>
      <div>
        <div className="mb-1.5 text-[13px] font-medium">Locations</div>
        <ChipGroup options={options.location_scopes.filter((item) => item.value !== "unknown")} value={draft.location_scopes} onChange={(value) => onChange({ ...draft, location_scopes: value })} />
      </div>
      <div className="grid gap-3 sm:grid-cols-3">
        <Select label="Home city" value={draft.city} onChange={(event) => onChange({ ...draft, city: event.target.value })} options={[...new Set([draft.city, ...options.cities])].map((city) => ({ value: city, label: city }))} />
        <Select
          label="Posted within"
          value={String(draft.posted_within_days || 0)}
          onChange={(event) => onChange({ ...draft, posted_within_days: Number(event.target.value) || null })}
          options={[{ value: "0", label: "Any time" }, ...options.posted_within_days.map((days) => ({ value: String(days), label: days === 1 ? "Last 24 hours" : `Last ${days} days` }))]}
        />
        <Select
          label="Refresh automatically"
          value={draft.auto_refresh ? String(draft.refresh_hours) : "0"}
          onChange={(event) => onChange({ ...draft, auto_refresh: event.target.value !== "0", refresh_hours: Number(event.target.value) || draft.refresh_hours })}
          options={[
            { value: "0", label: "Off" },
            { value: "12", label: "Twice a day" },
            { value: "24", label: "Daily" },
          ]}
        />
      </div>
      <TagInput label="Job titles to search for (optional)" hint="Extra titles to query on job boards, for example “Data Engineer Intern”." value={draft.custom_titles} onChange={(value) => onChange({ ...draft, custom_titles: value })} />
      <div className="grid gap-3 sm:grid-cols-2">
        <TagInput label="Exclude companies" value={draft.exclude_companies} onChange={(value) => onChange({ ...draft, exclude_companies: value })} />
        <TagInput label="Exclude keywords" hint="For example “French required” or “clearance”." value={draft.exclude_keywords} onChange={(value) => onChange({ ...draft, exclude_keywords: value })} />
      </div>
    </div>
  );
}

