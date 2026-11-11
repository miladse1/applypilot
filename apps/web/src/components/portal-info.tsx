"use client";

import { useState } from "react";
import { ExternalLink } from "lucide-react";
import { Badge, Button, Card, Input, useToast } from "@/components/ui";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/hooks";
import type { PortalInfo } from "@/lib/types";

const CHANNEL: Record<string, string> = {
  york: "Experience York",
  employer: "Employer's website",
  linkedin: "LinkedIn Easy Apply",
};

/** Where a posting saved from Experience York or LinkedIn came from, and where to apply. */
export function PortalInfoCard({ jobId, portals, onChanged }: { jobId: string; portals: PortalInfo[]; onChanged: () => void }) {
  const toast = useToast();
  const needsLink = portals.some((item) => item.channels.includes("employer") && !item.employer_url);
  const [link, setLink] = useState("");
  const [saving, setSaving] = useState(false);

  async function save() {
    setSaving(true);
    try {
      await api(`/jobs/${jobId}/employer-link`, { method: "PUT", body: JSON.stringify({ url: link }) });
      toast("Saved. ApplyPilot will fill the employer's form at this link.", "good");
      setLink("");
      onChanged();
    } catch (err) {
      toast(errorMessage(err), "bad");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Card>
      <h3 className="mb-3 text-[13px] font-semibold">Where to apply</h3>
      <div className="space-y-3 text-[13px]">
        {portals.map((item) => (
          <div key={`${item.portal}-${item.external_id}`} className="space-y-1.5">
            <a href={item.url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-accent hover:underline">
              Original posting on {item.name} <ExternalLink className="h-3 w-3" />
            </a>
            <div className="flex flex-wrap gap-1">
              {item.channels.map((channel) => <Badge key={channel} tone={channel === "employer" ? "accent" : "warn"}>{CHANNEL[channel]}</Badge>)}
            </div>
            {item.channels.length > 1 && <p className="text-[12px] text-muted">This one is submitted in both places. The application page tracks each.</p>}
            {item.application_method && <div className="text-[12px] text-muted">How to apply: {item.application_method}</div>}
            {item.deadline && <div className="text-[12px] text-muted">Deadline: {item.deadline}</div>}
            {item.documents && <div className="text-[12px] text-muted">Documents: {item.documents}</div>}
            {item.employer_url && (
              <a href={item.employer_url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-[12px] text-accent hover:underline">
                Employer application page <ExternalLink className="h-3 w-3" />
              </a>
            )}
          </div>
        ))}
        {needsLink && (
          <div className="space-y-1.5 border-t border-line pt-3">
            <Input label="Employer application link" placeholder="https://…" value={link} onChange={(event) => setLink(event.target.value)} hint="Paste it if you have it, so ApplyPilot can fill the employer's form." />
            <Button size="sm" variant="secondary" disabled={link.trim().length < 8} loading={saving} onClick={save}>Save link</Button>
          </div>
        )}
      </div>
    </Card>
  );
}
