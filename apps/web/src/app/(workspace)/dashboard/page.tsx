"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { ArrowRight, CheckCircle2, Circle, Radar, Sparkles } from "lucide-react";
import { DiscoveryPanel, JobRow, useDiscovery } from "@/components/jobs";
import { Button, Card, CardHeader, EmptyState, LinkButton, LoadingBlock, Notice, PageHeader, Stat } from "@/components/ui";
import { useApi } from "@/lib/hooks";
import type { Home, OriginalResume } from "@/lib/types";

const PROMPTS = [
  "Find data engineering internships in Toronto",
  "Find recent software engineering co-op opportunities",
  "Which jobs am I most qualified for?",
  "What do you need from me?",
];

export default function DashboardPage() {
  const router = useRouter();
  const { data: home, reload, error } = useApi<Home>("/home");
  const { data: resumes } = useApi<OriginalResume[]>("/resumes");
  const discovery = useDiscovery(() => reload());
  const [prompt, setPrompt] = useState("");

  if (!home) return error ? <Notice tone="bad">{error}</Notice> : <LoadingBlock label="Loading your workspace" />;

  const pending = home.checklist.filter((item) => !item.done);
  const stale = (resumes || []).some((item) => item.is_primary && !item.has_layout);
  const firstName = home.name.split(" ")[0];

  function ask(text: string) {
    router.push(`/assistant?q=${encodeURIComponent(text)}`);
  }

  return (
    <div>
      <PageHeader
        title={`Hi ${firstName}`}
        description="Here is where your job search stands."
        actions={
          <Button icon={<Radar className="h-4 w-4" />} loading={discovery.running} onClick={() => discovery.start(home.search_profile.id)}>
            {discovery.running ? "Searching…" : "Find new jobs"}
          </Button>
        }
      />
      {stale && (
        <Notice tone="warn" className="mb-4" title="Re-read your resume" action={<LinkButton href="/onboarding" size="sm" variant="secondary">Review</LinkButton>}>
          Your resume was read with the old parser, which missed projects and mixed up bullets. The new reader keeps your real layout and content.
        </Notice>
      )}
      {(discovery.running || discovery.status) && (
        <div className="mb-5">
          <DiscoveryPanel status={discovery.status} running={discovery.running} />
        </div>
      )}

      <div className="mb-6 grid grid-cols-2 gap-3 md:grid-cols-5">
        <Stat label="Matching jobs" value={home.matches_total} hint={`${home.new_this_week} new this week`} href="/jobs" tone="accent" />
        <Stat label="Questions for you" value={home.open_questions} hint="Skills to confirm" href="/questions" tone={home.open_questions ? "warn" : "neutral"} />
        <Stat label="Ready for review" value={home.pipeline.ready_for_review + home.pipeline.needs_answers} hint="Drafts waiting" href="/applications" />
        <Stat label="Submitted" value={home.pipeline.submitted} hint={`${home.pipeline.finish_on_site} to finish on site`} href="/applications" tone="good" />
        <Stat label="Interviews" value={home.pipeline.interviews + home.pipeline.offers} hint={home.pipeline.offers ? `${home.pipeline.offers} offer(s)` : "Recorded by you"} href="/applications" />
      </div>

      <div className="grid gap-6 lg:grid-cols-[1fr_340px]">
        <div className="min-w-0 space-y-6">
          <Card padded={false} className="p-5">
            <CardHeader
              title="Top matches"
              description={`${home.search_profile.name}: ${home.matches_total} jobs fit your saved search.`}
              actions={<LinkButton href="/jobs" size="sm" variant="ghost" icon={<ArrowRight className="h-3.5 w-3.5" />}>All jobs</LinkButton>}
            />
            {home.top_matches.length === 0 ? (
              <EmptyState icon={<Radar className="h-5 w-5" />} title="No matches yet" action={<Button loading={discovery.running} onClick={() => discovery.start(home.search_profile.id)}>Find new jobs</Button>}>
                Search employer career sites and Canadian job boards for roles that fit you.
              </EmptyState>
            ) : (
              <div className="space-y-3">
                {home.top_matches.map((job) => (
                  <JobRow key={job.id} job={job} compact />
                ))}
              </div>
            )}
          </Card>
        </div>

        <div className="space-y-6">
          <Card>
            <div className="mb-3 flex items-center gap-2">
              <Sparkles className="h-4 w-4 text-accent" />
              <h2 className="text-[15px] font-semibold">Ask the assistant</h2>
            </div>
            <form
              onSubmit={(event) => {
                event.preventDefault();
                if (prompt.trim()) ask(prompt.trim());
              }}
            >
              <textarea value={prompt} onChange={(event) => setPrompt(event.target.value)} placeholder="Find me junior backend roles in Toronto…" className="h-20 w-full resize-none rounded-lg border border-line bg-surface px-3 py-2 text-[13.5px] outline-none focus:border-accent" />
              <Button type="submit" size="sm" className="mt-2 w-full" disabled={!prompt.trim()}>Ask</Button>
            </form>
            <div className="mt-3 space-y-1">
              {PROMPTS.map((item) => (
                <button key={item} onClick={() => ask(item)} className="block w-full rounded-md px-2 py-1.5 text-left text-[12.5px] text-muted hover:bg-surface2 hover:text-ink">
                  {item}
                </button>
              ))}
            </div>
            {!home.ai_configured && <p className="mt-2 text-[12px] text-faint">Claude is not connected yet, so the assistant uses built-in rules. Connect it in Settings.</p>}
          </Card>

          {pending.length > 0 && (
            <Card>
              <h2 className="mb-3 text-[15px] font-semibold">Finish setting up</h2>
              <ul className="space-y-2">
                {home.checklist.map((item) => (
                  <li key={item.key}>
                    <Link href={item.href} className="flex items-center gap-2 text-[13.5px] hover:text-accent">
                      {item.done ? <CheckCircle2 className="h-4 w-4 text-success" /> : <Circle className="h-4 w-4 text-faint" />}
                      <span className={item.done ? "text-muted line-through" : ""}>{item.label}</span>
                    </Link>
                  </li>
                ))}
              </ul>
            </Card>
          )}

          <Card>
            <h2 className="mb-3 text-[15px] font-semibold">Pipeline</h2>
            <dl className="space-y-1.5 text-[13px]">
              {[
                ["Needs your answers", home.pipeline.needs_answers],
                ["Ready for review", home.pipeline.ready_for_review],
                ["Approved", home.pipeline.approved],
                ["Finish on employer site", home.pipeline.finish_on_site],
                ["Submitted", home.pipeline.submitted],
                ["Interviewing", home.pipeline.interviews],
                ["Offers", home.pipeline.offers],
                ["Closed", home.pipeline.closed],
              ].map(([label, value]) => (
                <div key={label as string} className="flex justify-between">
                  <dt className="text-muted">{label}</dt>
                  <dd className="font-medium">{value}</dd>
                </div>
              ))}
            </dl>
          </Card>
        </div>
      </div>
    </div>
  );
}
