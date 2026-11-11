"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import {
  Briefcase,
  FileText,
  GraduationCap,
  HelpCircle,
  LayoutDashboard,
  LogOut,
  Menu,
  Moon,
  Send,
  Settings,
  SlidersHorizontal,
  Sparkles,
  Sun,
  User,
  X,
} from "lucide-react";
import { LogoMark } from "@/components/logo";
import { ToastProvider } from "@/components/ui";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";

type NavItem = { label: string; href: string; icon: typeof Briefcase; badge?: "questions" | "applications"; match?: string[] };

const groups: Array<{ label?: string; items: NavItem[] }> = [
  {
    items: [
      { label: "Home", href: "/dashboard", icon: LayoutDashboard },
      { label: "Assistant", href: "/assistant", icon: Sparkles },
    ],
  },
  {
    label: "Job search",
    items: [
      { label: "Jobs", href: "/jobs", icon: Briefcase },
      { label: "York co-op", href: "/york", icon: GraduationCap },
      { label: "Applications", href: "/applications", icon: Send, badge: "applications", match: ["/applications", "/review", "/tracker"] },
      { label: "Questions", href: "/questions", icon: HelpCircle, badge: "questions", match: ["/questions", "/verify"] },
    ],
  },
  {
    label: "You",
    items: [
      { label: "Resume", href: "/resume", icon: FileText, match: ["/resume", "/studio", "/onboarding"] },
      { label: "Profile", href: "/profile", icon: User, match: ["/profile", "/career"] },
      { label: "Job searches", href: "/searches", icon: SlidersHorizontal },
      { label: "Settings", href: "/settings", icon: Settings },
    ],
  },
];

export function Shell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const [ready, setReady] = useState(false);
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [counts, setCounts] = useState<{ questions: number; applications: number; apply_needs_you?: number }>({ questions: 0, applications: 0 });
  const [open, setOpen] = useState(false);
  const [dark, setDark] = useState(false);

  useEffect(() => {
    api<{ full_name: string; email: string }>("/auth/me")
      .then((user) => {
        setName(user.full_name);
        setEmail(user.email);
        setReady(true);
      })
      .catch(() => router.replace("/login"));
    setDark(document.documentElement.classList.contains("dark"));
  }, [router]);

  useEffect(() => {
    if (!ready) return;
    api<{ questions: number; applications: number; apply_needs_you?: number }>("/nav-counts").then(setCounts).catch(() => undefined);
    setOpen(false);
  }, [pathname, ready]);

  function toggleTheme() {
    const next = !document.documentElement.classList.contains("dark");
    document.documentElement.classList.toggle("dark", next);
    setDark(next);
    try {
      localStorage.setItem("theme", next ? "dark" : "light");
    } catch {
      /* storage unavailable */
    }
  }

  async function logout() {
    await api("/auth/logout", { method: "POST" }).catch(() => undefined);
    router.replace("/login");
  }

  if (!ready) {
    return (
      <div className="flex min-h-screen items-center justify-center text-[13px] text-muted">
        <span className="mr-2 inline-block h-2 w-2 animate-pulse rounded-full bg-accent" /> Loading your workspace…
      </div>
    );
  }

  const nav = (
    <nav className="flex flex-1 flex-col gap-5 overflow-y-auto px-3 py-4 scrollbar-thin">
      {groups.map((group, index) => (
        <div key={index}>
          {group.label && <div className="mb-1 px-2 text-[11px] font-semibold uppercase tracking-wider text-faint">{group.label}</div>}
          <div className="space-y-0.5">
            {group.items.map((item) => {
              const active = (item.match || [item.href]).some((prefix) => pathname === prefix || pathname.startsWith(prefix + "/"));
              const count = item.badge === "applications" ? counts.applications + (counts.apply_needs_you || 0) : item.badge ? counts[item.badge] : 0;
              const Icon = item.icon;
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  className={cn(
                    "flex items-center gap-2.5 rounded-lg px-2 py-1.5 text-[13.5px] transition",
                    active ? "bg-surface2 font-medium text-ink" : "text-muted hover:bg-surface2/70 hover:text-ink",
                  )}
                >
                  <Icon className={cn("h-4 w-4", active ? "text-accent" : "text-faint")} />
                  <span className="flex-1">{item.label}</span>
                  {count > 0 && <span className={cn("rounded-full px-1.5 text-[11px] font-semibold", item.badge === "questions" ? "bg-warn-soft text-warn" : "bg-accent-soft text-accent")}>{count}</span>}
                </Link>
              );
            })}
          </div>
        </div>
      ))}
    </nav>
  );

  const sidebar = (
    <div className="flex h-full flex-col">
      <Link href="/dashboard" className="flex items-center gap-2 px-5 pb-1 pt-5">
        <LogoMark className="h-7 w-7" />
        <span className="text-[15px] font-semibold tracking-tight">ApplyPilot</span>
      </Link>
      {nav}
      <div className="border-t border-line p-3">
        <div className="flex items-center gap-2 rounded-lg px-2 py-1.5">
          <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-surface2 text-[12px] font-semibold">{name.slice(0, 1).toUpperCase()}</span>
          <div className="min-w-0 flex-1">
            <div className="truncate text-[13px] font-medium">{name}</div>
            <div className="truncate text-[11.5px] text-muted">{email}</div>
          </div>
          <button onClick={toggleTheme} className="rounded-md p-1.5 text-muted hover:bg-surface2 hover:text-ink" aria-label="Toggle dark mode" title="Toggle dark mode">
            {dark ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
          </button>
          <button onClick={logout} className="rounded-md p-1.5 text-muted hover:bg-surface2 hover:text-ink" aria-label="Log out" title="Log out">
            <LogOut className="h-4 w-4" />
          </button>
        </div>
      </div>
    </div>
  );

  return (
    <ToastProvider>
      <div className="min-h-screen">
        <aside className="fixed inset-y-0 left-0 z-30 hidden w-60 border-r border-line bg-surface lg:block">{sidebar}</aside>
        <div className="sticky top-0 z-20 flex items-center justify-between border-b border-line bg-surface/90 px-4 py-2.5 backdrop-blur lg:hidden">
          <Link href="/dashboard" className="flex items-center gap-2">
            <LogoMark className="h-7 w-7" />
            <span className="font-semibold">ApplyPilot</span>
          </Link>
          <button onClick={() => setOpen(true)} className="rounded-md p-1.5 text-muted hover:bg-surface2" aria-label="Open menu">
            <Menu className="h-5 w-5" />
          </button>
        </div>
        {open && (
          <div className="fixed inset-0 z-40 bg-black/40 lg:hidden" onClick={() => setOpen(false)}>
            <aside className="absolute inset-y-0 left-0 w-64 border-r border-line bg-surface" onClick={(event) => event.stopPropagation()}>
              <button onClick={() => setOpen(false)} className="absolute right-3 top-4 rounded-md p-1 text-muted hover:bg-surface2" aria-label="Close menu">
                <X className="h-4 w-4" />
              </button>
              {sidebar}
            </aside>
          </div>
        )}
        <main className="lg:pl-60">
          <div className="mx-auto max-w-[1180px] px-4 py-6 sm:px-6 lg:px-8 lg:py-8">{children}</div>
        </main>
      </div>
    </ToastProvider>
  );
}
