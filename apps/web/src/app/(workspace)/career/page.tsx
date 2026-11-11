"use client";

import { useState } from "react";
import { BarChart3 } from "lucide-react";
import { Button, Card, EmptyState, Input, LoadingBlock, Notice, PageHeader, useToast } from "@/components/ui";
import { api } from "@/lib/api";
import { errorMessage, useApi } from "@/lib/hooks";

type Gap = { normalized_name: string; display_name: string; frequency: number; plan_status: string | null; reason: string };

export default function CareerPage() {
  const toast = useToast();
  const { data, reload, error } = useApi<{ disclaimer: string; recommendations: Gap[] }>("/career/gaps");
  const [plans, setPlans] = useState<Record<string, string>>({});
  const [context, setContext] = useState<Record<string, string>>({});

  async function mark(item: Gap, status: string) {
    try {
      const plan = await api<{ id: string }>("/career/plans", { method: "POST", body: JSON.stringify({ normalized_name: item.normalized_name, display_name: item.display_name, status }) });
      setPlans((current) => ({ ...current, [item.normalized_name]: plan.id }));
      toast(status === "learning" ? `Marked ${item.display_name} as learning.` : "Saved.", "good");
    } catch (err) {
      toast(errorMessage(err), "bad");
    }
  }

  async function complete(item: Gap) {
    const planId = plans[item.normalized_name];
    try {
      await api(`/career/plans/${planId}/complete`, { method: "POST", body: JSON.stringify({ context: context[item.normalized_name], proficiency: "intermediate" }) });
      toast(`${item.display_name} is now a confirmed skill.`, "good");
      await reload();
    } catch (err) {
      toast(errorMessage(err), "bad");
    }
  }

  const top = (data?.recommendations || []).slice(0, 30);
  const max = Math.max(1, ...top.map((item) => item.frequency));

  return (
    <div>
      <PageHeader title="Skill gaps" description="Skills that appear most often in the jobs ApplyPilot found for you and are not on your profile. Use it to decide what to learn next, or confirm skills you already have." />
      {error && <Notice tone="bad">{error}</Notice>}
      {!data ? (
        error ? null : <LoadingBlock />
      ) : top.length === 0 ? (
        <EmptyState icon={<BarChart3 className="h-5 w-5" />} title="No gaps yet">Find more jobs first. Gaps are computed from the postings in your list.</EmptyState>
      ) : (
        <Card>
          <div className="divide-y divide-line">
            {top.map((item) => (
              <div key={item.normalized_name} className="py-3">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div className="min-w-[200px] flex-1">
                    <div className="text-[14px] font-medium">{item.display_name}</div>
                    <div className="mt-1 flex items-center gap-2">
                      <div className="h-1.5 w-40 overflow-hidden rounded-full bg-surface2">
                        <div className="h-full rounded-full bg-accent" style={{ width: `${(100 * item.frequency) / max}%` }} />
                      </div>
                      <span className="text-[12px] text-muted">in {item.frequency} job{item.frequency === 1 ? "" : "s"}</span>
                    </div>
                  </div>
                  <div className="flex gap-1.5">
                    <Button size="sm" variant="secondary" onClick={() => mark(item, "learning")}>I'm learning it</Button>
                    <Button size="sm" variant="secondary" onClick={() => mark(item, "interested")}>I already have it</Button>
                    <Button size="sm" variant="ghost" onClick={() => mark(item, "not_interested")}>Not interested</Button>
                  </div>
                </div>
                {plans[item.normalized_name] && (
                  <div className="mt-2 flex flex-wrap items-end gap-2">
                    <Input label="Where have you used it?" value={context[item.normalized_name] || ""} onChange={(event) => setContext((current) => ({ ...current, [item.normalized_name]: event.target.value }))} wrapperClassName="flex-1 min-w-[260px]" />
                    <Button size="sm" disabled={!context[item.normalized_name]} onClick={() => complete(item)}>Add as a confirmed skill</Button>
                  </div>
                )}
              </div>
            ))}
          </div>
          <p className="mt-3 text-[12px] text-muted">{data.disclaimer}</p>
        </Card>
      )}
    </div>
  );
}
