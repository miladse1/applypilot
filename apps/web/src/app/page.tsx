import Link from "next/link";
import { Briefcase, FileText, HelpCircle, ShieldCheck, Sparkles } from "lucide-react";

const features = [
  { icon: Briefcase, title: "Relevant jobs only", body: "Co-op, internship, new-grad, and junior roles from 50+ employer career sites (TD, RBC, Scotiabank, Amazon, IBM, AMD, Stripe and more), Job Bank, and remote boards. Senior roles and roles outside your locations stay out of the way." },
  { icon: FileText, title: "Your resume, tailored", body: "ApplyPilot reads your own resume, layout included, and tailors it for each job: relevant bullets first, matching skills highlighted, and with Claude, wording rewritten. Every change is checked against your facts." },
  { icon: HelpCircle, title: "Questions only when they matter", body: "If a job needs a skill your resume does not mention, ApplyPilot asks while you apply, not before. It remembers your answer." },
  { icon: ShieldCheck, title: "You approve everything", body: "Drafts wait for your review. ApplyPilot never claims an application was submitted unless you confirm it." },
  { icon: Sparkles, title: "An assistant that does the work", body: "“Find data engineering internships in Toronto.” “Prepare applications for these.” It searches, ranks, tailors, and drafts." },
];

export default function LandingPage() {
  return (
    <main className="mx-auto max-w-5xl px-6 py-14">
      <nav className="mb-16 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-accent text-[14px] font-bold text-accent-ink">A</span>
          <span className="text-[17px] font-semibold tracking-tight">ApplyPilot</span>
        </div>
        <div className="flex gap-2">
          <Link href="/login" className="rounded-lg px-3 py-2 text-[13.5px] font-medium text-muted hover:text-ink">Sign in</Link>
          <Link href="/register" className="rounded-lg bg-accent px-3.5 py-2 text-[13.5px] font-medium text-accent-ink">Get started</Link>
        </div>
      </nav>
      <p className="text-[13px] font-semibold uppercase tracking-wider text-accent">For students and new grads in Canada</p>
      <h1 className="mt-3 max-w-3xl text-[40px] font-semibold leading-[1.1] tracking-tight md:text-[52px]">Upload your resume. Say what you want. Review applications that are ready to send.</h1>
      <p className="mt-5 max-w-2xl text-[16px] leading-relaxed text-muted">ApplyPilot finds relevant co-op and early-career roles, tailors your own resume for each one, prepares cover letters and answers, and waits for your approval.</p>
      <div className="mt-8 flex gap-3">
        <Link href="/register" className="rounded-lg bg-accent px-5 py-3 text-[14px] font-semibold text-accent-ink">Create a free account</Link>
        <Link href="/login" className="rounded-lg border border-line bg-surface px-5 py-3 text-[14px] font-semibold">Sign in</Link>
      </div>
      <div className="mt-16 grid gap-4 md:grid-cols-2">
        {features.map((feature) => (
          <div key={feature.title} className="rounded-xl border border-line bg-surface p-5 shadow-card">
            <feature.icon className="h-5 w-5 text-accent" />
            <h2 className="mt-3 text-[15px] font-semibold">{feature.title}</h2>
            <p className="mt-1 text-[13.5px] leading-relaxed text-muted">{feature.body}</p>
          </div>
        ))}
      </div>
    </main>
  );
}
