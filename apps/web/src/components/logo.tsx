import { cn } from "@/lib/utils";

// Same mark as the app icon (mac/icons/make_icons.py).
export function LogoMark({ className }: { className?: string }) {
  return (
    <span className={cn("flex items-center justify-center rounded-lg bg-gradient-to-b from-[#6366f1] to-[#4338ca]", className)}>
      <svg viewBox="0 0 24 24" fill="none" className="h-[58%] w-[58%]" aria-hidden>
        <path d="M14.536 21.686a.5.5 0 0 0 .937-.024l6.5-19a.496.496 0 0 0-.635-.635l-19 6.5a.5.5 0 0 0-.024.937l7.93 3.18a2 2 0 0 1 1.112 1.11z" fill="#fff" />
        <path d="m21.854 2.147-10.94 10.939" stroke="#4338ca" strokeWidth="1.6" strokeLinecap="round" />
      </svg>
    </span>
  );
}
