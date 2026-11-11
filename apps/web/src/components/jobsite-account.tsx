"use client";

import { useEffect, useState } from "react";
import { KeyRound } from "lucide-react";
import { Badge, Button, Card, CardHeader, ErrorState, Input, LoadingBlock, Notice, PasswordField, Switch, useToast } from "@/components/ui";
import { api } from "@/lib/api";
import { fullDate } from "@/lib/format";
import { errorMessage, useApi } from "@/lib/hooks";

type Account = {
  email: string;
  has_password: boolean;
  sign_in: boolean;
  create_accounts: boolean;
  keychain_available: boolean;
  sites: Array<{ host: string; email: string; created_by_applypilot: boolean; last_used_at: string | null }>;
};

// Workday's usual rule: 8+ characters with an uppercase letter, a lowercase letter, a number, and a symbol.
function strongEnough(password: string) {
  return password.length >= 8 && /[A-Z]/.test(password) && /[a-z]/.test(password) && /\d/.test(password) && /[^A-Za-z0-9]/.test(password);
}

export function JobSiteAccount() {
  const toast = useToast();
  const { data, error, reload, setData } = useApi<Account>("/apply/account");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (data) setEmail(data.email);
  }, [data]);

  async function save(body: Partial<Account> & { password?: string }, message: string) {
    setBusy(true);
    try {
      setData(await api<Account>("/apply/account", { method: "PUT", body: JSON.stringify(body) }));
      setPassword("");
      toast(message, "good");
    } catch (err) {
      toast(errorMessage(err), "bad");
    } finally {
      setBusy(false);
    }
  }

  if (error) return <ErrorState message={error} onRetry={reload} />;
  if (!data) return <LoadingBlock label="Loading job-site sign-in" />;

  return (
    <Card>
      <CardHeader
        title="Job-site sign-in"
        description="Let ApplyPilot sign in to employer job sites such as Workday during automatic applications. Your password is kept in your Mac's Keychain, never in ApplyPilot's database, logs, or anything sent to Claude."
        actions={data.has_password ? <Badge tone="good" icon={<KeyRound className="h-3 w-3" />}>Password saved</Badge> : <Badge>No password saved</Badge>}
      />
      {!data.keychain_available && <Notice tone="bad" className="mb-3">No system keychain is available, so ApplyPilot cannot store a password on this computer.</Notice>}
      <div className="grid gap-3 sm:grid-cols-2">
        <Input label="Email you use on job sites" type="email" value={email} onChange={(event) => setEmail(event.target.value)} hint="Usually the same email as your applications." />
        <div>
          <PasswordField label={data.has_password ? "Change password" : "Password"} value={password} onChange={(event) => setPassword(event.target.value)} autoComplete="new-password" />
          <p className="mt-1 text-[12px] text-muted">
            {password && !strongEnough(password)
              ? "Workday usually requires 8+ characters with upper and lower case, a number, and a symbol."
              : "Use the password you use on Workday sites, or a new one for accounts ApplyPilot creates."}
          </p>
        </div>
      </div>
      <div className="mt-3 flex flex-wrap gap-2">
        <Button size="sm" loading={busy} disabled={!email.includes("@") || (!password && email === data.email)} onClick={() => save({ email, ...(password ? { password, sign_in: true } : {}) }, password ? "Saved to your Keychain. ApplyPilot will sign in for you." : "Email saved.")}>
          Save
        </Button>
        {data.has_password && (
          <Button size="sm" variant="ghost" loading={busy} onClick={() => save({ password: "" }, "Password removed from your Keychain.")}>Remove password</Button>
        )}
      </div>
      <div className="mt-5 space-y-3">
        <Switch
          checked={data.sign_in}
          onChange={(value) => save({ sign_in: value }, value ? "ApplyPilot will sign in for you." : "ApplyPilot will wait for you to sign in.")}
          label="Sign in for me"
          description={data.has_password ? "When a job site asks you to sign in, ApplyPilot uses the email and password above. It tries a password once per site, so a wrong one never locks your account." : "Save a password first."}
        />
        <Switch
          checked={data.create_accounts}
          onChange={(value) => save({ create_accounts: value }, value ? "ApplyPilot may create job-site accounts for you." : "ApplyPilot will not create accounts.")}
          label="Create an account when I don't have one"
          description="Uses the same email and password, and accepts that site's account terms for you. If the site sends a verification email, ApplyPilot waits until you click the link."
        />
      </div>
      {data.sites.length > 0 && (
        <div className="mt-5">
          <h3 className="mb-2 text-[13px] font-semibold">Sites ApplyPilot has used ({data.sites.length})</h3>
          <div className="divide-y divide-line rounded-lg border border-line text-[13px]">
            {data.sites.map((site) => (
              <div key={site.host} className="flex items-center justify-between gap-3 px-3 py-2">
                <div className="min-w-0">
                  <div className="truncate">{site.host}</div>
                  <div className="text-[12px] text-muted">{site.email}{site.last_used_at ? ` · last used ${fullDate(site.last_used_at)}` : ""}</div>
                </div>
                {site.created_by_applypilot ? <Badge tone="accent">Account created by ApplyPilot</Badge> : <Badge>Signed in</Badge>}
              </div>
            ))}
          </div>
        </div>
      )}
    </Card>
  );
}
