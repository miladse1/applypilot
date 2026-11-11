"use client";

import Link from "next/link";
import { FormEvent, useState } from "react";
import { AuthFrame } from "@/components/auth-frame";
import { Button, Input, Notice } from "@/components/ui";
import { api, ApiError } from "@/lib/api";

export default function ForgotPasswordPage() {
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    setError("");
    setPending(true);
    try {
      const result = await api<{ message: string }>("/auth/password-reset/request", { method: "POST", body: JSON.stringify({ email: data.get("email") }) });
      setMessage(result.message);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Request failed");
    } finally {
      setPending(false);
    }
  }

  return (
    <AuthFrame title="Reset your password" subtitle="Enter your email and we will send you a link to choose a new password." footer={<Link href="/login" className="hover:underline">Back to sign in</Link>}>
      {message ? (
        <Notice tone="good">{message}</Notice>
      ) : (
        <form className="space-y-4" onSubmit={onSubmit}>
          <Input label="Email" name="email" type="email" autoComplete="email" required />
          {error && <Notice tone="bad">{error}</Notice>}
          <Button type="submit" className="w-full" loading={pending}>Email me a reset link</Button>
        </form>
      )}
    </AuthFrame>
  );
}
