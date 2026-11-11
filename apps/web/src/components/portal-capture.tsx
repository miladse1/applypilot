"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { GraduationCap, Linkedin, ListChecks, Square } from "lucide-react";
import { Badge, Button, Card, useToast } from "@/components/ui";
import { api } from "@/lib/api";
import { errorMessage, useApi } from "@/lib/hooks";
import type { CaptureStatus } from "@/lib/types";

const PHASE: Record<string, string> = {
  opening: "Opening",
  sign_in: "Waiting for you to sign in",
  find_list: "Finding the posting list",
  reading: "Reading postings",
  watching: "Saving postings you open",
};

/** Experience York and LinkedIn, through the ApplyPilot browser window. */
export function PortalCapture({ onSaved }: { onSaved?: () => void }) {
  const toast = useToast();
  const { data: status, setData, reload } = useApi<CaptureStatus>("/jobs/capture");
  const term = "";
  const [busy, setBusy] = useState("");
  const seen = useRef(0);

  const active = Boolean(status?.active);
  useEffect(() => {
    if (!active && busy !== "start") return;
    const timer = setInterval(() => reload(), 2500);
    return () => clearInterval(timer);
  }, [active, busy, reload]);

  useEffect(() => {
    const count = status?.saved_count || 0;
    if (count > seen.current) onSaved?.();
    seen.current = count;
  }, [status?.saved_count, onSaved]);

  async function call(path: string, body: Record<string, unknown>, label: string) {
    setBusy(label);
    try {
      await api(path, { method: "POST", body: JSON.stringify(body) });
      setTimeout(() => reload(), 1200);
    } catch (err) {
      toast(errorMessage(err), "bad");
    } finally {
      setTimeout(() => setBusy(""), 1500);
    }
  }

  async function stop() {
    await call("/jobs/capture/stop", {}, "stop");
    setData({ active: false });
  }

  return (
    <Card padded={false} className="p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="text-[13px] font-semibold">Experience York and LinkedIn</h3>
          <p className="mt-0.5 max-w-2xl text-[12.5px] text-muted">
            York co-op postings are added from your usual browser and kept private on the <Link href="/york" className="text-accent hover:underline">York co-op page</Link>. For LinkedIn, sign in yourself in the ApplyPilot window and each job you open is saved with its original link.
          </p>
        </div>
        {!active && (
          <div className="flex flex-wrap items-end gap-2">
            <Link href="/york" className="inline-flex h-8 items-center gap-1.5 rounded-md border border-line px-2.5 text-[12.5px] font-medium hover:bg-surface2">
              <GraduationCap className="h-3.5 w-3.5" /> York co-op postings
            </Link>
            <Button size="sm" variant="secondary" icon={<Linkedin className="h-3.5 w-3.5" />} loading={busy === "linkedin"} onClick={() => call("/jobs/capture/start", { portal: "linkedin" }, "linkedin")}>
              Open LinkedIn Jobs
            </Button>
          </div>
        )}
      </div>
      {status && (status.active || status.message) && (
        <div className="mt-3 rounded-lg border border-line p-3 text-[12.5px]">
          <div className="mb-1 flex flex-wrap items-center gap-2">
            <span className="font-medium">{status.portal_name}</span>
            {status.phase && <Badge tone={status.phase === "sign_in" ? "warn" : status.active ? "accent" : "neutral"}>{status.active ? PHASE[status.phase] || status.phase : "Stopped"}</Badge>}
            <span className="text-muted">
              {status.saved_count || 0} saved{status.skipped ? ` · ${status.skipped} not software, data, or AI` : ""}{status.already ? ` · ${status.already} already saved` : ""}
            </span>
          </div>
          {status.message && <p className="text-muted">{status.message}</p>}
          {(status.saved || []).length > 0 && (
            <div className="mt-2 flex flex-wrap gap-1.5">
              {(status.saved || []).slice(-8).map((item) => (
                <Link key={item.id} href={`/jobs/${item.id}`} className="rounded-md bg-surface2 px-2 py-0.5 hover:text-accent">
                  {item.title} · {item.company}
                </Link>
              ))}
            </div>
          )}
          {status.active && (
            <div className="mt-2 flex gap-2">
              {status.portal === "york" && status.phase !== "reading" && (
                <Button size="sm" variant="secondary" icon={<ListChecks className="h-3.5 w-3.5" />} loading={busy === "read"} onClick={() => call("/jobs/capture/read-list", { portal: "york", term }, "read")}>
                  Read the list
                </Button>
              )}
              <Button size="sm" variant="ghost" icon={<Square className="h-3.5 w-3.5" />} loading={busy === "stop"} onClick={stop}>
                Stop
              </Button>
            </div>
          )}
        </div>
      )}
    </Card>
  );
}
