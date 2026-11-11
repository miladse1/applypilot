"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { CheckCircle2, ShieldCheck } from "lucide-react";
import { Button, Card, LoadingBlock, Notice } from "@/components/ui";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/hooks";

type Result = { kind: string; message: string; saved: Array<{ id: string; title: string; company: string; state: string }> };

type Payload = { url?: string; html?: string };

function sourceHost(url: string | undefined): string {
  try {
    return url ? new URL(url).host : "an unknown page";
  } catch {
    return "an unknown page";
  }
}

/**
 * Opened by the Save to ApplyPilot bookmark with the page in the address fragment (never sent
 * to a server but this one). Any website can open this address, so nothing is saved until the
 * user confirms with a click.
 */
export default function YorkImportPage() {
  const [payload, setPayload] = useState<Payload | null>(null);
  const [saving, setSaving] = useState(false);
  const [result, setResult] = useState<Result | null>(null);
  const [error, setError] = useState("");
  const started = useRef(false);

  useEffect(() => {
    if (started.current) return;
    started.current = true;
    try {
      const received = JSON.parse(decodeURIComponent(window.location.hash.slice(1))) as Payload;
      if (!received || typeof received.html !== "string") throw new Error("empty");
      setPayload(received);
    } catch {
      setError("Nothing was received. Use the Save to ApplyPilot bookmark on an Experience York page.");
      return;
    }
    window.history.replaceState(null, "", window.location.pathname); // a refresh does not import again
  }, []);

  function save() {
    if (!payload || saving) return;
    setSaving(true);
    api<Result>("/jobs/york/import", { method: "POST", body: JSON.stringify({ html: payload.html, url: payload.url }) })
      .then((value) => {
        setResult(value);
        if (value.kind !== "unknown" && window.opener) setTimeout(() => window.close(), 2500);
      })
      .catch((err) => setError(errorMessage(err)))
      .finally(() => setSaving(false));
  }

  if (error) return <Notice tone="bad">{error}</Notice>;
  if (!payload) return <LoadingBlock label="Reading the page" />;
  if (!result) {
    return (
      <div className="mx-auto max-w-xl">
        <Card>
          <div className="space-y-3">
            <div className="text-[15px] font-semibold">Save this page to ApplyPilot?</div>
            <p className="text-[13px] text-muted">
              Received from <span className="font-medium text-ink">{sourceHost(payload.url)}</span>. Save it only if you just clicked the Save to ApplyPilot bookmark on Experience York.
            </p>
            <div className="flex gap-2">
              <Button size="sm" onClick={save} loading={saving}>Save</Button>
              <Button size="sm" variant="ghost" onClick={() => window.close()}>Cancel</Button>
            </div>
          </div>
        </Card>
      </div>
    );
  }
  return (
    <div className="mx-auto max-w-xl">
      <Card>
        {result.kind === "unknown" ? (
          <Notice tone="warn">{result.message} Open a posting, or the list of postings, then click the bookmark again.</Notice>
        ) : (
          <div className="space-y-3">
            <div className="flex items-center gap-2 text-[15px] font-semibold">
              <CheckCircle2 className="h-5 w-5 text-success" /> {result.message}
            </div>
            <ul className="max-h-64 overflow-y-auto text-[13px] text-muted">
              {result.saved.slice(0, 50).map((item) => (
                <li key={item.id}>{item.title} · {item.company}</li>
              ))}
            </ul>
            <p className="flex items-start gap-1.5 text-[12px] text-muted">
              <ShieldCheck className="mt-0.5 h-3.5 w-3.5 shrink-0" /> Kept on this computer and not sent to Claude. This tab closes by itself.
            </p>
          </div>
        )}
        <div className="mt-4 flex gap-2">
          <Link href="/york" className="text-[13px] text-accent hover:underline">See your ranked York postings</Link>
          <Button size="sm" variant="ghost" onClick={() => window.close()}>Close</Button>
        </div>
      </Card>
    </div>
  );
}
