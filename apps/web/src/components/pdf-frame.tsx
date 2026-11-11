"use client";

import { useEffect, useState } from "react";
import { ErrorState, Spinner } from "@/components/ui";
import { cn } from "@/lib/utils";

/** Loads a PDF first and shows it only when the server really returned a PDF; otherwise shows the error. */
export function PdfFrame({ src, title, className }: { src: string; title: string; className?: string }) {
  const [url, setUrl] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let objectUrl: string | null = null;
    let cancelled = false;
    setUrl(null);
    setError("");
    fetch(src, { credentials: "include", cache: "no-store" })
      .then(async (response) => {
        const type = response.headers.get("content-type") || "";
        if (!response.ok || !type.includes("pdf")) {
          let message = `The preview could not be loaded (HTTP ${response.status}).`;
          try {
            const body = await response.json();
            message = body?.detail?.message || body?.detail || message;
          } catch {
            /* not JSON */
          }
          throw new Error(typeof message === "string" ? message : "The preview could not be loaded.");
        }
        objectUrl = URL.createObjectURL(await response.blob());
        if (!cancelled) setUrl(objectUrl);
      })
      .catch((err: Error) => !cancelled && setError(err.message));
    return () => {
      cancelled = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [src, attempt]);

  if (error) return <div className="p-4"><ErrorState message={error} onRetry={() => setAttempt((value) => value + 1)} /></div>;
  if (!url) {
    return (
      <div className={cn("flex items-center justify-center gap-2 bg-surface2 text-[13px] text-muted", className)}>
        <Spinner /> Loading preview…
      </div>
    );
  }
  return <iframe src={`${url}#toolbar=1&navpanes=0&view=FitH`} title={title} className={cn("w-full bg-white", className)} />;
}
