"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { FormEvent, useState } from "react";
import { AuthFrame } from "@/components/auth-frame";
import { Button, Input, Notice, PasswordField } from "@/components/ui";
import { api, ApiError } from "@/lib/api";

export default function RegisterPage() {
  const router = useRouter();
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    setPending(true);
    setError("");
    try {
      await api("/auth/register", { method: "POST", body: JSON.stringify({ full_name: data.get("full_name"), email: data.get("email"), password: data.get("password") }) });
      router.push("/onboarding");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not create the account");
    } finally {
      setPending(false);
    }
  }

  return (
    <AuthFrame title="Create your account" subtitle="Then upload your resume and tell ApplyPilot what jobs you want." footer={<Link href="/login" className="text-accent hover:underline">I already have an account</Link>}>
      <form className="space-y-4" onSubmit={onSubmit}>
        <Input label="Full name" name="full_name" autoComplete="name" required />
        <Input label="Email" name="email" type="email" autoComplete="email" required />
        <PasswordField label="Password" name="password" minLength={10} autoComplete="new-password" required />
        <p className="text-[12px] text-muted">At least 10 characters.</p>
        {error && <Notice tone="bad">{error}</Notice>}
        <Button type="submit" className="w-full" loading={pending}>Create account</Button>
      </form>
    </AuthFrame>
  );
}
