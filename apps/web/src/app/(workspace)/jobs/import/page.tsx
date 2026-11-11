"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { ImportJobModal } from "@/components/jobs";
import { LoadingBlock } from "@/components/ui";

type Payload = { url?: string; title?: string; text?: string; ld?: string };

function fromJsonLd(raw: string | undefined): Partial<{ title: string; company: string; description: string }> {
  if (!raw) return {};
  for (const chunk of raw.split("\n")) {
    try {
      const data = JSON.parse(chunk);
      const items = Array.isArray(data) ? data : [data, ...(data["@graph"] || [])];
      const posting = items.find((item: { "@type"?: string | string[] }) => item && (item["@type"] === "JobPosting" || (Array.isArray(item["@type"]) && item["@type"].includes("JobPosting"))));
      if (posting) {
        // The description is HTML written by a third-party page. DOMParser builds an inert
        // document: no scripts run and no images or event handlers load (unlike innerHTML on
        // an element of this page, where <img onerror> would run inside ApplyPilot).
        const parsed = new DOMParser().parseFromString(String(posting.description || ""), "text/html");
        return { title: posting.title, company: typeof posting.hiringOrganization === "object" ? posting.hiringOrganization?.name : posting.hiringOrganization, description: parsed.body.textContent || "" };
      }
    } catch {
      /* not JSON */
    }
  }
  return {};
}

export default function ImportFromBookmarklet() {
  const router = useRouter();
  const [initial, setInitial] = useState<{ url?: string; title?: string; company?: string; description?: string } | null>(null);

  useEffect(() => {
    let payload: Payload = {};
    try {
      payload = JSON.parse(decodeURIComponent(window.location.hash.slice(1)));
    } catch {
      /* opened directly */
    }
    const structured = fromJsonLd(payload.ld);
    const title = structured.title || (payload.title || "").split(/\s[|–-]\s/)[0];
    setInitial({ url: payload.url, title, company: structured.company, description: structured.description || payload.text });
  }, []);

  if (!initial) return <LoadingBlock />;
  return <ImportJobModal open initial={initial} onClose={() => router.push("/jobs")} onImported={(id) => router.push(`/jobs/${id}`)} />;
}
