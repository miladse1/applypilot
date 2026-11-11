"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { FormEvent, useEffect, useState } from "react";
import { AuthFrame } from "@/components/auth-frame";
import { Button, Input, Notice, PasswordField } from "@/components/ui";
import { api, ApiError } from "@/lib/api";

export default function LoginPage() {
  const router = useRouter();
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);
  const [notice, setNotice] = useState("");
  useEffect(() => {
    if (new URLSearchParams(window.location.search).get("reset")) setNotice("Your password was changed. Sign in with the new one.");
  }, []);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    setPending(true);
    setError("");
    try {
      await api("/auth/login", { method: "POST", body: JSON.stringify({ email: data.get("email"), password: data.get("password") }) });
      router.push("/dashboard");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not sign in");
    } finally {
      setPending(false);
    }
  }

  return (
    <AuthFrame
      title="Welcome back"
      subtitle="Sign in to your job search workspace."
      footer={
        <>
          <Link href="/register" className="text-accent hover:underline">Create an account</Link>
          {" · "}
          <Link href="/forgot-password" className="hover:underline">Forgot password</Link>
        </>
      }
    >
      <form className="space-y-4" onSubmit={onSubmit}>
        <Input label="Email" name="email" type="email" autoComplete="email" required />
        <PasswordField label="Password" name="password" autoComplete="current-password" required />
        {notice && <Notice tone="good">{notice}</Notice>}
        {error && <Notice tone="bad">{error}</Notice>}
        <Button type="submit" className="w-full" loading={pending}>Sign in</Button>
      </form>
    </AuthFrame>
  );
}
