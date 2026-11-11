"use client";

import { useEffect, useRef, useState } from "react";
import { CheckCircle2, MessageSquare, RotateCcw, Send, ShieldAlert } from "lucide-react";
import { Button, Card, CardHeader, Textarea, useToast } from "@/components/ui";
import { api } from "@/lib/api";
import { stripMarkup } from "@/lib/format";
import { errorMessage } from "@/lib/hooks";
import type { ResumeChatMessage, ResumeVersion } from "@/lib/types";

const SUGGESTIONS = [
  "What would you improve for this job?",
  "Why did you choose these projects?",
  "Improve the technical descriptions.",
  "Shorten my work experience section.",
  "Emphasize my Python and SQL work.",
];

const OP_LABEL: Record<string, string> = {
  rewrite: "Reworded",
  hide: "Hid",
  show: "Restored",
  add_project: "Added project",
  remove_project: "Removed project",
  move: "Moved",
  set_skills: "Skills line",
};

function Message({ item }: { item: ResumeChatMessage }) {
  if (item.role === "user") {
    return <div className="ml-8 self-end rounded-lg bg-accent-soft px-3 py-2 text-[13px] whitespace-pre-wrap">{item.text}</div>;
  }
  return (
    <div className="mr-4 space-y-2 rounded-lg bg-surface2 px-3 py-2 text-[13px]">
      <div className="whitespace-pre-wrap">{item.text}</div>
      {(item.applied || []).length > 0 && (
        <ul className="space-y-1 border-t border-line pt-2 text-[12px]">
          {(item.applied || []).map((edit, index) => (
            <li key={index} className="flex gap-1.5">
              <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-success" />
              <span>
                <span className="font-medium">{OP_LABEL[edit.op] || edit.op}</span>
                {edit.entry && <span className="text-muted"> · {stripMarkup(edit.entry)}</span>}
                {edit.after && edit.op !== "move" && <span className="block text-muted">{stripMarkup(edit.after)}</span>}
              </span>
            </li>
          ))}
        </ul>
      )}
      {(item.blocked || []).length > 0 && (
        <ul className="space-y-1 border-t border-line pt-2 text-[12px]">
          {(item.blocked || []).map((edit, index) => (
            <li key={index} className="flex gap-1.5 text-warn">
              <ShieldAlert className="mt-0.5 h-3.5 w-3.5 shrink-0" />
              <span>Not applied: {(edit.problems || []).join(" ")}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function ResumeChat({ version, onUpdated }: { version: ResumeVersion; onUpdated: (next: ResumeVersion, changed: boolean) => void }) {
  const toast = useToast();
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState<"" | "send" | "undo">("");
  const [pending, setPending] = useState("");
  const list = useRef<HTMLDivElement>(null);
  const chat = version.content?.chat || [];

  useEffect(() => {
    list.current?.scrollTo({ top: list.current.scrollHeight });
  }, [chat.length, pending]);

  async function send(text: string) {
    const value = text.trim();
    if (!value || busy) return;
    setBusy("send");
    setPending(value);
    setMessage("");
    try {
      const next = await api<ResumeVersion>(`/resume-versions/${version.id}/chat`, { method: "POST", body: JSON.stringify({ message: value }) });
      onUpdated(next, Boolean(next.turn?.applied?.length));
    } catch (err) {
      setMessage(value);
      toast(errorMessage(err), "bad");
    } finally {
      setBusy("");
      setPending("");
    }
  }

  async function undo() {
    setBusy("undo");
    try {
      const next = await api<ResumeVersion>(`/resume-versions/${version.id}/undo`, { method: "POST" });
      onUpdated(next, true);
      toast("Undid the last change.", "good");
    } catch (err) {
      toast(errorMessage(err), "bad");
    } finally {
      setBusy("");
    }
  }

  return (
    <Card>
      <CardHeader
        title={
          <span className="inline-flex items-center gap-1.5">
            <MessageSquare className="h-4 w-4 text-accent" /> Ask Claude about this resume
          </span>
        }
        description={
          version.private_job
            ? "This job is a private York posting, so Claude sees only your resume and your messages, not the posting. Tell it what the job needs. Every change is checked and kept to your layout. About 3¢ per message."
            : "Ask for advice or for changes. Every change is checked against your resume and profile, kept to your layout and page count, and shown in the PDF. About 3¢ per message."
        }
        actions={version.can_undo ? <Button size="sm" variant="ghost" icon={<RotateCcw className="h-3.5 w-3.5" />} loading={busy === "undo"} onClick={undo}>Undo</Button> : undefined}
      />
      <div ref={list} className="flex max-h-[420px] flex-col gap-2 overflow-y-auto">
        {chat.length === 0 && !pending && (
          <div className="flex flex-wrap gap-1.5">
            {SUGGESTIONS.map((item) => (
              <button key={item} onClick={() => send(item)} className="rounded-full border border-line px-2.5 py-1 text-[12px] text-muted hover:border-accent hover:text-ink">
                {item}
              </button>
            ))}
          </div>
        )}
        {chat.map((item, index) => <Message key={`${item.at}-${index}`} item={item} />)}
        {pending && (
          <>
            <Message item={{ role: "user", text: pending, at: "" }} />
            <div className="mr-4 rounded-lg bg-surface2 px-3 py-2 text-[13px] text-muted">Claude is working on it…</div>
          </>
        )}
      </div>
      <form
        className="mt-3 space-y-2"
        onSubmit={(event) => {
          event.preventDefault();
          send(message);
        }}
      >
        <Textarea
          value={message}
          onChange={(event) => setMessage(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey) {
              event.preventDefault();
              send(message);
            }
          }}
          placeholder="For example: rewrite my second retail bullet to show customer service"
          className="min-h-20"
        />
        <div className="flex justify-end">
          <Button type="submit" size="sm" icon={<Send className="h-3.5 w-3.5" />} loading={busy === "send"} disabled={!message.trim()}>
            Send
          </Button>
        </div>
      </form>
    </Card>
  );
}
