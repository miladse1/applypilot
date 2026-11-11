"use client";

import { useEffect, useState } from "react";
import { Button, Card, CardHeader, ErrorState, Input, LoadingBlock, Meter, Notice, Select, Stat, useToast } from "@/components/ui";
import { api } from "@/lib/api";
import { errorMessage, useApi } from "@/lib/hooks";
import type { AIUsage } from "@/lib/types";

const MODEL_OPTIONS = [
  { value: "sonnet", label: "Claude Sonnet 5.5 (recommended)" },
  { value: "opus", label: "Claude Opus 5.5 (higher quality, about 2× cost)" },
];

export function usd(value: number) {
  if (value === 0) return "$0.00";
  if (value < 0.0001) return "<$0.0001";
  if (value < 0.01) return `$${value.toFixed(4)}`;
  return `$${value.toFixed(2)}`;
}

function tokens(value: number) {
  return value >= 1000 ? `${(value / 1000).toFixed(value >= 10000 ? 0 : 1)}k` : String(value);
}

export function AIUsageCard() {
  const toast = useToast();
  const { data, error, reload } = useApi<AIUsage>("/ai/usage");
  const [limit, setLimit] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (data) setLimit(data.spend_limit_usd.toFixed(2));
  }, [data]);

  async function save(body: { quality_model?: string; spend_limit_usd?: number }) {
    setSaving(true);
    try {
      await api("/ai/settings", { method: "PUT", body: JSON.stringify(body) });
      toast("AI settings saved.", "good");
      reload();
    } catch (err) {
      toast(errorMessage(err), "bad");
    } finally {
      setSaving(false);
    }
  }

  if (error) return <ErrorState message={error} onRetry={reload} />;
  if (!data) return <LoadingBlock label="Loading AI usage" />;
  const spent = data.totals.all_time.cost_usd;
  const used = data.spend_limit_usd > 0 ? Math.round((spent / data.spend_limit_usd) * 100) : 100;
  const limitValue = Number(limit);

  return (
    <Card>
      <CardHeader
        title="AI usage and cost"
        description="Estimated from the token counts Anthropic reports for each request. Job classification, skill extraction, and matching run locally and cost nothing."
      />
      {data.limit_reached && (
        <Notice tone="bad" title="Spending limit reached" className="mb-4">
          Claude is paused for your account. Tailoring, cover letters, and the assistant keep working with built-in rules. Raise the limit below to use Claude again.
        </Notice>
      )}
      <div className="grid gap-3 sm:grid-cols-4">
        <Stat label="Today" value={usd(data.totals.today.cost_usd)} hint={`${data.totals.today.requests} request(s)`} />
        <Stat label="Last 7 days" value={usd(data.totals.last_7_days.cost_usd)} hint={`${data.totals.last_7_days.requests} request(s)`} />
        <Stat label="This month" value={usd(data.totals.this_month.cost_usd)} hint={`${data.totals.this_month.requests} request(s)`} />
        <Stat label="All time" value={usd(spent)} hint={`${data.cache_hits} reused result(s), no charge`} tone={data.limit_reached ? "warn" : "neutral"} />
      </div>
      <div className="mt-4">
        <div className="mb-1 text-[12px] text-muted">
          {usd(spent)} of your {usd(data.spend_limit_usd)} limit used · {usd(data.remaining_usd)} left
        </div>
        <Meter value={used} tone={used >= 80 ? "warn" : "accent"} />
      </div>

      <div className="mt-5 grid gap-4 sm:grid-cols-2">
        <Select
          label="Model for resume rewriting, cover letters, and the assistant"
          value={data.quality_model}
          options={MODEL_OPTIONS}
          disabled={saving}
          onChange={(event) => save({ quality_model: event.target.value })}
          hint={`Simple checks use ${data.models.fast.label}.`}
        />
        <div className="flex items-end gap-2">
          <Input
            label="Spending limit (USD)"
            type="number"
            min={0}
            max={1000}
            step={0.5}
            value={limit}
            onChange={(event) => setLimit(event.target.value)}
            wrapperClassName="flex-1"
            hint="Claude stops when estimated spend reaches this amount."
          />
          <Button
            variant="secondary"
            className="mb-[22px]"
            loading={saving}
            disabled={!limit || Number.isNaN(limitValue) || limitValue < 0 || limitValue === data.spend_limit_usd}
            onClick={() => save({ spend_limit_usd: limitValue })}
          >
            Save
          </Button>
        </div>
      </div>

      {data.by_feature.length > 0 && (
        <div className="mt-6 grid gap-6 lg:grid-cols-2">
          <UsageTable title="By feature" rows={data.by_feature.map((row) => ({ key: row.feature, name: row.label, ...row }))} />
          <UsageTable title="By model" rows={data.by_model.map((row) => ({ key: row.model, name: row.label, ...row }))} />
        </div>
      )}

      {data.recent.length > 0 && (
        <div className="mt-6">
          <h3 className="mb-2 text-[13px] font-semibold">Recent requests</h3>
          <div className="overflow-x-auto">
            <table className="w-full text-[12.5px]">
              <thead className="text-left text-muted">
                <tr className="border-b border-line">
                  <th className="py-1.5 pr-3 font-medium">When</th>
                  <th className="py-1.5 pr-3 font-medium">Feature</th>
                  <th className="py-1.5 pr-3 font-medium">Model</th>
                  <th className="py-1.5 pr-3 text-right font-medium">Input</th>
                  <th className="py-1.5 pr-3 text-right font-medium">Output</th>
                  <th className="py-1.5 text-right font-medium">Cost</th>
                </tr>
              </thead>
              <tbody>
                {data.recent.map((row, index) => (
                  <tr key={`${row.at}-${index}`} className="border-b border-line/60 last:border-0">
                    <td className="whitespace-nowrap py-1.5 pr-3 text-muted">{new Date(row.at).toLocaleString([], { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" })}</td>
                    <td className="py-1.5 pr-3">{row.feature}{!row.ok && <span className="ml-1 text-danger">(failed)</span>}</td>
                    <td className="py-1.5 pr-3 text-muted">{row.model}</td>
                    <td className="py-1.5 pr-3 text-right tabular-nums">{tokens(row.input_tokens)}{row.cached_tokens > 0 && <span className="text-muted"> ({tokens(row.cached_tokens)} cached)</span>}</td>
                    <td className="py-1.5 pr-3 text-right tabular-nums">{tokens(row.output_tokens)}</td>
                    <td className="py-1.5 text-right tabular-nums">{usd(row.cost_usd)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
      <p className="mt-4 text-[12px] text-muted">{data.note}</p>
    </Card>
  );
}

function UsageTable({ title, rows }: { title: string; rows: Array<{ key: string; name: string; requests: number; cost_usd: number }> }) {
  return (
    <div>
      <h3 className="mb-2 text-[13px] font-semibold">{title}</h3>
      <table className="w-full text-[12.5px]">
        <tbody>
          {rows.map((row) => (
            <tr key={row.key} className="border-b border-line/60 last:border-0">
              <td className="py-1.5 pr-3">{row.name}</td>
              <td className="py-1.5 pr-3 text-right tabular-nums text-muted">{row.requests} req</td>
              <td className="py-1.5 text-right tabular-nums">{usd(row.cost_usd)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
