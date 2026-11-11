"use client";

import Link from "next/link";
import { useMemo } from "react";
import { CheckCircle2 } from "lucide-react";
import { QuestionList } from "@/components/questions";
import { EmptyState, LinkButton, LoadingBlock, Notice, PageHeader } from "@/components/ui";
import { useApi } from "@/lib/hooks";
import type { Profile, Question } from "@/lib/types";

export default function QuestionsPage() {
  const { data: questions, reload, error } = useApi<Question[]>("/qualifications/open");
  const { data: profile } = useApi<Profile>("/profile");

  const groups = useMemo(() => {
    const map = new Map<string, { title: string; company: string; questions: Question[] }>();
    for (const question of questions || []) {
      const key = question.job_posting_id || "general";
      if (!map.has(key)) map.set(key, { title: question.job?.title || "General", company: question.job?.company || "", questions: [] });
      map.get(key)!.questions.push(question);
    }
    return [...map.entries()];
  }, [questions]);

  return (
    <div>
      <PageHeader
        title="Skill questions"
        description="When a job you are applying to asks for something your resume does not mention, ApplyPilot asks here instead of assuming you lack it. Answers are remembered, so you will not be asked about the same skill again."
      />
      {error && <Notice tone="bad">{error}</Notice>}
      {!questions ? (
        <LoadingBlock label="Loading questions" />
      ) : questions.length === 0 ? (
        <EmptyState icon={<CheckCircle2 className="h-5 w-5" />} title="No open questions" action={<LinkButton href="/jobs">Browse jobs</LinkButton>}>
          Questions appear when you prepare an application for a job that needs a skill your profile does not list yet.
        </EmptyState>
      ) : (
        <div className="space-y-8">
          {groups.map(([jobId, group]) => (
            <section key={jobId}>
              <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
                <h2 className="text-[15px] font-semibold">
                  {group.title}
                  {group.company && <span className="font-normal text-muted"> at {group.company}</span>}
                </h2>
                {jobId !== "general" && (
                  <Link href={`/jobs/${jobId}`} className="text-[12.5px] text-accent hover:underline">
                    View job
                  </Link>
                )}
              </div>
              <QuestionList questions={group.questions} profile={profile} jobId={jobId !== "general" ? jobId : undefined} onDone={() => reload()} />
            </section>
          ))}
        </div>
      )}
    </div>
  );
}
