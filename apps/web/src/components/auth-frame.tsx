import Link from "next/link";
import { LogoMark } from "@/components/logo";

export function AuthFrame({ title, subtitle, children, footer }: { title: string; subtitle?: string; children: React.ReactNode; footer?: React.ReactNode }) {
  return (
    <main className="flex min-h-screen flex-col items-center justify-center px-4 py-12">
      <Link href="/" className="mb-8 flex items-center gap-2">
        <LogoMark className="h-8 w-8" />
        <span className="text-[17px] font-semibold tracking-tight">ApplyPilot</span>
      </Link>
      <div className="w-full max-w-sm rounded-2xl border border-line bg-surface p-6 shadow-card">
        <h1 className="text-[19px] font-semibold tracking-tight">{title}</h1>
        {subtitle && <p className="mt-1 text-[13px] text-muted">{subtitle}</p>}
        <div className="mt-5">{children}</div>
      </div>
      {footer && <div className="mt-4 text-[13px] text-muted">{footer}</div>}
    </main>
  );
}
