"use client";

import { FormEvent, useState } from "react";
import { CheckCircle2, CircleDashed, Download, KeyRound } from "lucide-react";
import { AIUsageCard } from "@/components/ai-usage";
import { AutofillSettings } from "@/components/autofill-settings";
import { JobSiteAccount } from "@/components/jobsite-account";
import { bookmarkletCode } from "@/components/jobs";
import { Badge, Button, Card, CardHeader, ErrorState, Input, LoadingBlock, Notice, PageHeader, PasswordField, useToast } from "@/components/ui";
import { api } from "@/lib/api";
import { errorMessage, useApi } from "@/lib/hooks";
import type { Health } from "@/lib/types";

function Status({ ok, label }: { ok: boolean; label: string }) {
  return ok ? (
    <Badge tone="good" icon={<CheckCircle2 className="h-3 w-3" />}>{label}</Badge>
  ) : (
    <Badge icon={<CircleDashed className="h-3 w-3" />}>{label}</Badge>
  );
}

function Code({ children }: { children: string }) {
  return <pre className="mt-2 overflow-x-auto rounded-lg bg-surface2 px-3 py-2 text-[12.5px] leading-relaxed">{children}</pre>;
}

export default function SettingsPage() {
  const toast = useToast();
  const { data: health, error: healthError, reload: reloadHealth } = useApi<Health>("/health");
  const [confirmEmail, setConfirmEmail] = useState("");
  const [aiTest, setAiTest] = useState<{ ok: boolean; message?: string; reply?: string; model?: string; latency_ms?: number } | null>(null);
  const [testing, setTesting] = useState(false);

  async function testAi() {
    setTesting(true);
    try {
      setAiTest(await api("/ai/test", { method: "POST" }));
    } catch (err) {
      setAiTest({ ok: false, message: errorMessage(err) });
    } finally {
      setTesting(false);
    }
  }

  async function exportData() {
    const payload = await api("/auth/export");
    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = "applypilot-export.json";
    anchor.click();
    URL.revokeObjectURL(url);
  }

  async function changePassword(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    try {
      await api("/auth/password-change", { method: "POST", body: JSON.stringify({ current_password: data.get("current"), new_password: data.get("next") }) });
      toast("Password updated.", "good");
      form.reset();
    } catch (err) {
      toast(errorMessage(err), "bad");
    }
  }

  if (healthError) return <ErrorState message={healthError} onRetry={reloadHealth} />;
  if (!health) return <LoadingBlock />;
  const integrations = health.integrations;

  return (
    <div>
      <PageHeader title="Settings" />
      <div className="space-y-6">
        <Card>
          <CardHeader title="AI (Claude)" description="Claude rewrites resume bullets and summaries, writes cover letters, double-checks resume extraction, and powers the assistant. Every output is checked against your own facts before it is used." actions={<Status ok={integrations.ai} label={integrations.ai ? "Connected" : "Not connected"} />} />
          <div className="mb-3 flex flex-wrap items-center gap-3">
            <Button size="sm" variant="secondary" loading={testing} onClick={testAi}>Test connection</Button>
            <span className="text-[12px] text-muted">Uses Claude Haiku 5.5 (well under $0.001).</span>
            {aiTest && (aiTest.ok ? <span className="text-[13px] text-success">Working. {aiTest.model} answered in {aiTest.latency_ms} ms: “{aiTest.reply}”</span> : <span className="text-[13px] text-danger">{aiTest.message}</span>)}
          </div>
          {!integrations.ai && (
            <div className="text-[13px]">
              <p className="mb-2">The easiest way: in a terminal, from the ApplyPilot folder, run <code className="rounded bg-surface2 px-1">./configure.sh ai</code>. It asks for the key without showing it, stores it only on this computer, and checks it with a real request. Or do it by hand:</p>
              <ol className="list-decimal space-y-1.5 pl-5">
                <li>
                  Create an API key at{" "}
                  <a href="https://console.anthropic.com/settings/keys" target="_blank" rel="noreferrer" className="text-accent underline underline-offset-2">console.anthropic.com</a>.
                </li>
                <li>
                  Add it to <code className="rounded bg-surface2 px-1">~/Library/Application Support/ApplyPilot/.env</code> (outside the code folder, so it can never be committed):
                  <Code>{`ANTHROPIC_API_KEY=sk-ant-...\n# optional, this is the default:\nANTHROPIC_MODEL=claude-sonnet-5-5`}</Code>
                </li>
                <li>Restart the API server. This page will show “Connected”.</li>
              </ol>
              <p className="mt-3 text-muted">Without a key, ApplyPilot still parses resumes, finds and ranks jobs, reorders and highlights your resume for each job, and runs the assistant with built-in rules.</p>
            </div>
          )}
        </Card>

        {integrations.ai && <AIUsageCard />}

        <Card>
          <CardHeader title="Adzuna (job aggregator)" description="Adds tens of thousands of Canadian postings from many boards. The other sources need no keys." actions={<Status ok={integrations.adzuna} label={integrations.adzuna ? "Connected" : "Optional"} />} />
          {!integrations.adzuna && (
            <div className="text-[13px]">
              Register free at{" "}
              <a href="https://developer.adzuna.com/signup" target="_blank" rel="noreferrer" className="text-accent underline underline-offset-2">developer.adzuna.com</a>, then add:
              <Code>{`ADZUNA_APP_ID=your-app-id\nADZUNA_APP_KEY=your-app-key\nADZUNA_COUNTRY=ca`}</Code>
            </div>
          )}
        </Card>

        <Card>
          <CardHeader title="Email (password reset)" description="Reset links are emailed, work once, and expire after 30 minutes. They are never shown in the app." actions={<Status ok={Boolean(integrations.email)} label={integrations.email ? "Connected" : "Not configured"} />} />
          {!integrations.email && (
            <div className="text-[13px]">
              Run <code className="rounded bg-surface2 px-1">./configure.sh email</code> and enter your provider's SMTP settings (for Gmail: <code className="rounded bg-surface2 px-1">smtp.gmail.com</code>, port 587, and an{" "}
              <a href="https://myaccount.google.com/apppasswords" target="_blank" rel="noreferrer" className="text-accent underline underline-offset-2">app password</a>). Until then, in development only, reset links are written to the API log (<code className="rounded bg-surface2 px-1">~/Library/Application Support/ApplyPilot/logs/api.log</code>), never to the website.
            </div>
          )}
        </Card>

        <AutofillSettings />

        <JobSiteAccount />

        <Card>
          <CardHeader title="Application submission" description="ApplyPilot can fill in and submit approved applications on Greenhouse, Lever, Ashby, and Workday (after you sign in), and assist on other employer sites. It works in its own Chrome window, can sign in for you (see Job-site sign-in), and stops for CAPTCHAs, verification emails, and anything it doesn't know." />
          <ul className="list-disc space-y-1 pl-5 text-[13px] text-muted">
            <li>Every application needs your explicit approval of the exact resume, letter, and answers before ApplyPilot opens it.</li>
            <li>“Submitted by ApplyPilot (employer confirmed)” means the employer's confirmation page was captured, with a screenshot. Without that, ApplyPilot asks you to check.</li>
            <li>LinkedIn, Indeed, and university portals don't allow automated applications, so ApplyPilot never automates them.</li>
            <li>“Submitted by you” means you finished the employer's form and confirmed it here.</li>
            <li>{health.demo_mode ? "Demo mode is on, so practice (simulated) submissions are available. They are always labeled and never reach an employer." : "Demo mode is off. Simulated submissions are disabled."}</li>
          </ul>
        </Card>

        <Card>
          <CardHeader title="Import button for LinkedIn, Indeed, and Experience York" description="Drag this to your bookmarks bar. On a posting you are viewing, click it to send the page text to ApplyPilot." />
          <a href={bookmarkletCode()} onClick={(event) => event.preventDefault()} className="inline-flex items-center gap-2 rounded-lg bg-accent px-3 py-1.5 text-[13px] font-medium text-accent-ink">
            Send to ApplyPilot
          </a>
          <p className="mt-2 text-[12px] text-muted">It runs only when you click it, on the page you have open, and only reads that page.</p>
        </Card>

        <Card>
          <CardHeader title="Password" />
          <form className="grid max-w-md gap-3" onSubmit={changePassword}>
            <PasswordField label="Current password" name="current" required />
            <PasswordField label="New password" name="next" minLength={10} required />
            <div>
              <Button type="submit" icon={<KeyRound className="h-4 w-4" />}>Change password</Button>
            </div>
          </form>
        </Card>

        <Card>
          <CardHeader title="Your data" />
          <div className="flex flex-wrap items-end gap-4">
            <Button variant="secondary" icon={<Download className="h-4 w-4" />} onClick={exportData}>Download a copy</Button>
          </div>
          <div className="mt-6 border-t border-line pt-4">
            <Notice tone="bad" title="Delete account">This permanently deletes your profile, resumes, and applications.</Notice>
            <div className="mt-3 flex flex-wrap items-end gap-2">
              <Input label="Type your email to confirm" type="email" value={confirmEmail} onChange={(event) => setConfirmEmail(event.target.value)} wrapperClassName="w-72" />
              <Button
                variant="danger"
                disabled={!confirmEmail.includes("@")}
                onClick={async () => {
                  await api("/auth/account", { method: "DELETE" });
                  window.location.href = "/";
                }}
              >
                Delete account
              </Button>
            </div>
          </div>
        </Card>
      </div>
    </div>
  );
}
