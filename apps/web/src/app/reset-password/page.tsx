"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { FormEvent, useEffect, useState } from "react";
import { AuthFrame } from "@/components/auth-frame";
import { Button, Notice, PasswordField } from "@/components/ui";
import { api, ApiError } from "@/lib/api";

export default function ResetPasswordPage() {
  const router = useRouter();
  const [token, setToken] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);

  useEffect(() => {
    // The emailed link carries the token in the URL fragment, which browsers never send to servers.
    const fromHash = new URLSearchParams(window.location.hash.slice(1)).get("token");
    const fromQuery = new URLSearchParams(window.location.search).get("token");
    setToken(fromHash || fromQuery || "");
    if (fromHash || fromQuery) window.history.replaceState(null, "", "/reset-password");
  }, []);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    if (data.get("password") !== data.get("confirm")) {
      setError("The passwords do not match.");
      return;
    }
    setPending(true);
    setError("");
    try {
      await api("/auth/password-reset/confirm", { method: "POST", body: JSON.stringify({ token, password: data.get("password") }) });
      router.push("/login?reset=1");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Reset failed");
    } finally {
      setPending(false);
    }
  }

  if (token === null) return null;
  if (!token) {
    return (
      <AuthFrame title="Reset link missing" footer={<Link href="/forgot-password" className="text-accent hover:underline">Request a new link</Link>}>
        <Notice tone="warn">Open this page from the link in your reset email.</Notice>
      </AuthFrame>
    );
  }
  return (
    <AuthFrame title="Choose a new password" subtitle="You will be signed out of other devices.">
      <form className="space-y-4" onSubmit={onSubmit}>
        <PasswordField label="New password" name="password" minLength={10} autoComplete="new-password" required />
        <PasswordField label="Confirm new password" name="confirm" minLength={10} autoComplete="new-password" required />
        {error && (
          <Notice tone="bad">
            {error} {error.includes("expired") && <Link href="/forgot-password" className="text-accent underline">Request a new link</Link>}
          </Notice>
        )}
        <Button type="submit" className="w-full" loading={pending}>Update password</Button>
      </form>
    </AuthFrame>
  );
}
