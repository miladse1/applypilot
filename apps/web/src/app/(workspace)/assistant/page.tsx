"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useRef, useState } from "react";
import { ArrowUp, FileText, HelpCircle, MessageSquarePlus, Send, SlidersHorizontal, Sparkles, Trash2, X } from "lucide-react";
import { DiscoveryPanel, JobRow, useDiscovery } from "@/components/jobs";
import { usd } from "@/components/ai-usage";
import { Badge, Button, Notice, RichText, useToast } from "@/components/ui";
import { api } from "@/lib/api";
import { errorMessage, useApi } from "@/lib/hooks";
import { applicationStatusLabel } from "@/lib/labels";
import type { Application, ChatBlock, ChatMessage, Health, JobCard, JobPage } from "@/lib/types";
import { cn } from "@/lib/utils";

const SUGGESTIONS = [
  "Find me data engineering internships in Toronto",
  "Find recent software engineering co-op opportunities",
  "Which jobs am I most qualified for?",
  "Prepare applications for my top 3 matches",
  "Tailor my resume for this job",
  "What do you need from me?",
];

type Conversation = { id: string; title: string; updated_at: string | null };
type Context = { job_id?: string; selected_job_ids?: string[] };

function JobsBlock({ ids }: { ids: string[] }) {
  const [jobs, setJobs] = useState<JobCard[] | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    api<JobPage>(`/jobs?ids=${ids.join(",")}`).then((page) => setJobs(page.items)).catch(() => setFailed(true));
  }, [ids]);
  if (failed) return <div className="text-[12px] text-danger">These jobs could not be loaded. Open the Jobs page instead.</div>;
  if (!jobs) return <div className="text-[12px] text-muted">Loading jobs…</div>;
  return (
    <div className="space-y-2">
      {jobs.map((job) => (
        <JobRow key={job.id} job={job} compact />
      ))}
    </div>
  );
}

function ApplicationsBlock({ ids }: { ids: string[] }) {
  const [rows, setRows] = useState<Application[] | null>(null);
  useEffect(() => {
    api<Application[]>("/applications").then((all) => setRows(all.filter((row) => ids.includes(row.id)))).catch(() => setRows([]));
  }, [ids]);
  if (!rows) return null;
  return (
    <div className="divide-y divide-line overflow-hidden rounded-lg border border-line bg-surface">
      {rows.map((row) => (
        <Link key={row.id} href={`/applications/${row.id}`} className="flex items-center justify-between gap-2 px-3 py-2 text-[13px] hover:bg-surface2">
          <span className="truncate">
            <span className="font-medium">{row.title}</span> <span className="text-muted">at {row.company}</span>
          </span>
          <Badge tone={row.status === "awaiting_skill_verification" ? "warn" : "accent"}>{applicationStatusLabel(row.status)}</Badge>
        </Link>
      ))}
    </div>
  );
}

function DiscoveryBlock({ taskId }: { taskId: string }) {
  const discovery = useDiscovery();
  const { follow } = discovery;
  useEffect(() => {
    follow(taskId);
  }, [taskId, follow]);
  return <DiscoveryPanel status={discovery.status} running={discovery.running} />;
}

function Blocks({ blocks }: { blocks: ChatBlock[] }) {
  return (
    <div className="mt-3 space-y-3">
      {blocks.map((block, index) => {
        if (block.type === "jobs") return <JobsBlock key={index} ids={block.ids} />;
        if (block.type === "applications") return <ApplicationsBlock key={index} ids={block.ids} />;
        if (block.type === "discovery") return <DiscoveryBlock key={index} taskId={block.task_id} />;
        if (block.type === "resume")
          return (
            <Link key={index} href={`/resume/versions/${block.version_id}`} className="flex items-center gap-2 rounded-lg border border-line bg-surface px-3 py-2 text-[13px] hover:border-accent/40">
              <FileText className="h-4 w-4 text-accent" /> Review the tailored resume: <span className="font-medium">{block.title}</span>
            </Link>
          );
        if (block.type === "questions")
          return (
            <Link key={index} href="/questions" className="flex items-center gap-2 rounded-lg border border-warn/30 bg-warn-soft px-3 py-2 text-[13px] text-warn">
              <HelpCircle className="h-4 w-4" /> {block.count} skill question{block.count === 1 ? "" : "s"} waiting for you
            </Link>
          );
        if (block.type === "search_profile")
          return (
            <Link key={index} href="/searches" className="flex items-center gap-2 rounded-lg border border-line bg-surface px-3 py-2 text-[13px]">
              <SlidersHorizontal className="h-4 w-4 text-accent" /> Your saved job search was updated
            </Link>
          );
        return null;
      })}
    </div>
  );
}

function AssistantView() {
  const params = useSearchParams();
  const router = useRouter();
  const toast = useToast();
  const { data: health } = useApi<Health>("/health");
  const { data: conversations, reload: reloadConversations } = useApi<Conversation[]>("/assistant/conversations");
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [pending, setPending] = useState(false);
  const [context, setContext] = useState<Context | null>(null);
  const bottom = useRef<HTMLDivElement>(null);
  const sentInitial = useRef(false);

  useEffect(() => {
    if (params.get("context")) {
      try {
        const raw = sessionStorage.getItem("assistant-context");
        if (raw) setContext(JSON.parse(raw));
      } catch {
        /* ignore */
      }
    }
  }, [params]);

  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages, pending]);

  const send = useCallback(
    async (text: string) => {
      const message = text.trim();
      if (!message || pending) return;
      setInput("");
      setMessages((current) => [...current, { role: "user", text: message, blocks: [] }]);
      setPending(true);
      try {
        const result = await api<{ conversation_id: string; reply: ChatMessage; usage?: ChatMessage["usage"] }>("/assistant/chat", {
          method: "POST",
          body: JSON.stringify({ message, conversation_id: conversationId, context }),
        });
        setConversationId(result.conversation_id);
        setMessages((current) => [...current, { ...result.reply, usage: result.usage }]);
        reloadConversations();
      } catch (err) {
        toast(errorMessage(err), "bad");
        setMessages((current) => [...current, { role: "assistant", text: "Something went wrong. Try again.", blocks: [] }]);
      } finally {
        setPending(false);
      }
    },
    [conversationId, context, pending, reloadConversations, toast],
  );

  useEffect(() => {
    const q = params.get("q");
    if (q && !sentInitial.current) {
      sentInitial.current = true;
      router.replace("/assistant");
      send(q);
    }
  }, [params, router, send]);

  async function open(id: string) {
    const data = await api<{ messages: ChatMessage[] }>(`/assistant/conversations/${id}`);
    setConversationId(id);
    setMessages(data.messages);
  }

  async function remove(id: string) {
    await api(`/assistant/conversations/${id}`, { method: "DELETE" });
    if (id === conversationId) {
      setConversationId(null);
      setMessages([]);
    }
    reloadConversations();
  }

  return (
    <div className="-my-2 grid h-[calc(100vh-5rem)] gap-5 lg:h-[calc(100vh-4rem)] lg:grid-cols-[220px_1fr]">
      <aside className="hidden min-h-0 flex-col lg:flex">
        <Button variant="secondary" icon={<MessageSquarePlus className="h-4 w-4" />} onClick={() => { setConversationId(null); setMessages([]); }}>
          New chat
        </Button>
        <div className="mt-3 min-h-0 flex-1 space-y-0.5 overflow-y-auto scrollbar-thin">
          {(conversations || []).map((item) => (
            <div key={item.id} className={cn("group flex items-center rounded-md", item.id === conversationId ? "bg-surface2" : "hover:bg-surface2/60")}>
              <button onClick={() => open(item.id)} className="min-w-0 flex-1 truncate px-2 py-1.5 text-left text-[13px]">
                {item.title}
              </button>
              <button onClick={() => remove(item.id)} className="hidden p-1.5 text-faint hover:text-danger group-hover:block" aria-label="Delete conversation">
                <Trash2 className="h-3.5 w-3.5" />
              </button>
            </div>
          ))}
        </div>
      </aside>

      <section className="flex min-h-0 flex-col rounded-xl border border-line bg-surface shadow-card">
        <div className="flex items-center justify-between border-b border-line px-5 py-3">
          <div className="flex items-center gap-2">
            <Sparkles className="h-4 w-4 text-accent" />
            <span className="font-semibold">Assistant</span>
            {health && (health.integrations.ai ? <Badge tone="accent">Claude {health.integrations.ai_model ? `· ${health.integrations.ai_model}` : ""}</Badge> : <Badge>Built-in rules</Badge>)}
          </div>
          <span className="hidden text-[12px] text-muted sm:block">Prepares drafts for your review. Never submits on its own.</span>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-5 scrollbar-thin">
          {health && !health.integrations.ai && messages.length === 0 && (
            <Notice tone="neutral" className="mb-4" title="Claude is not connected">
              The assistant still handles common requests with built-in rules. For natural conversation and AI resume rewriting, add an Anthropic API key (see Settings).
            </Notice>
          )}
          {messages.length === 0 ? (
            <div className="mx-auto max-w-xl pt-6 text-center">
              <div className="mx-auto mb-3 flex h-10 w-10 items-center justify-center rounded-full bg-accent-soft text-accent">
                <Sparkles className="h-5 w-5" />
              </div>
              <h2 className="text-[17px] font-semibold">What should we work on?</h2>
              <p className="mt-1 text-[13px] text-muted">I can search for jobs, rank your matches, tailor your resume, and prepare applications for you to approve.</p>
              <div className="mt-5 grid gap-2 sm:grid-cols-2">
                {SUGGESTIONS.map((item) => (
                  <button key={item} onClick={() => send(item)} className="rounded-lg border border-line px-3 py-2 text-left text-[13px] text-muted transition hover:border-accent/40 hover:text-ink">
                    {item}
                  </button>
                ))}
              </div>
            </div>
          ) : (
            <div className="mx-auto max-w-3xl space-y-5">
              {messages.map((message, index) => (
                <div key={index} className={cn("flex", message.role === "user" ? "justify-end" : "justify-start")}>
                  <div className={cn("max-w-[92%] text-[13.5px]", message.role === "user" ? "rounded-2xl rounded-br-md bg-accent px-3.5 py-2 text-accent-ink" : "w-full")}>
                    {message.role === "assistant" ? (
                      <>
                        <RichText text={message.text} />
                        {message.blocks?.length > 0 && <Blocks blocks={message.blocks} />}
                        {message.usage && (
                          <div className="mt-1.5 text-[11.5px] text-faint">
                            {usd(message.usage.cost_usd)} · {message.usage.requests} request{message.usage.requests === 1 ? "" : "s"}
                          </div>
                        )}
                      </>
                    ) : (
                      message.text
                    )}
                  </div>
                </div>
              ))}
              {pending && (
                <div className="flex items-center gap-2 text-[13px] text-muted">
                  <span className="flex gap-1">
                    <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-accent [animation-delay:-0.2s]" />
                    <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-accent [animation-delay:-0.1s]" />
                    <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-accent" />
                  </span>
                  Working on it…
                </div>
              )}
              <div ref={bottom} />
            </div>
          )}
        </div>

        <div className="border-t border-line p-3">
          {context && (context.job_id || context.selected_job_ids?.length) && (
            <div className="mb-2 flex items-center gap-2 text-[12px]">
              <Badge tone="accent">{context.job_id ? "About the job you were viewing" : `${context.selected_job_ids?.length} selected job(s)`}</Badge>
              <button onClick={() => setContext(null)} className="text-muted hover:text-ink" aria-label="Remove context">
                <X className="h-3.5 w-3.5" />
              </button>
            </div>
          )}
          <form
            onSubmit={(event) => {
              event.preventDefault();
              send(input);
            }}
            className="flex items-end gap-2"
          >
            <textarea
              value={input}
              onChange={(event) => setInput(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && !event.shiftKey) {
                  event.preventDefault();
                  send(input);
                }
              }}
              rows={1}
              placeholder="Ask anything about your job search…"
              className="max-h-40 min-h-[40px] flex-1 resize-none rounded-lg border border-line bg-surface px-3 py-2.5 text-[13.5px] outline-none focus:border-accent"
            />
            <Button type="submit" className="h-10 w-10 p-0" disabled={!input.trim() || pending} aria-label="Send">
              {pending ? <Send className="h-4 w-4" /> : <ArrowUp className="h-4 w-4" />}
            </Button>
          </form>
        </div>
      </section>
    </div>
  );
}

export default function AssistantPage() {
  return (
    <Suspense fallback={null}>
      <AssistantView />
    </Suspense>
  );
}
