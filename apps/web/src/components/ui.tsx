"use client";

import Link from "next/link";
import { Check, ChevronDown, Loader2, Search, X } from "lucide-react";
import {
  ButtonHTMLAttributes,
  InputHTMLAttributes,
  ReactNode,
  SelectHTMLAttributes,
  TextareaHTMLAttributes,
  createContext,
  forwardRef,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { cn } from "@/lib/utils";

// ---------------------------------------------------------------------------
// Buttons
// ---------------------------------------------------------------------------

type Variant = "primary" | "secondary" | "ghost" | "danger" | "subtle";
type Size = "sm" | "md" | "lg";

const variants: Record<Variant, string> = {
  primary: "bg-accent text-accent-ink hover:opacity-90 shadow-sm",
  secondary: "border border-line bg-surface text-ink hover:bg-surface2 shadow-sm",
  ghost: "text-muted hover:bg-surface2 hover:text-ink",
  danger: "bg-danger text-white hover:opacity-90",
  subtle: "bg-accent-soft text-accent hover:opacity-90",
};
const sizes: Record<Size, string> = {
  sm: "h-8 gap-1.5 px-2.5 text-[13px]",
  md: "h-9 gap-2 px-3.5 text-[13.5px]",
  lg: "h-11 gap-2 px-5 text-[15px]",
};

export function buttonClass(variant: Variant = "primary", size: Size = "md", className?: string) {
  return cn(
    "inline-flex select-none items-center justify-center whitespace-nowrap rounded-lg font-medium transition disabled:cursor-not-allowed disabled:opacity-50",
    variants[variant],
    sizes[size],
    className,
  );
}

export function Button({
  variant = "primary",
  size = "md",
  loading,
  icon,
  className,
  children,
  disabled,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; size?: Size; loading?: boolean; icon?: ReactNode }) {
  return (
    <button className={buttonClass(variant, size, className)} disabled={disabled || loading} {...props}>
      {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : icon}
      {children}
    </button>
  );
}

export function LinkButton({ href, variant = "secondary", size = "md", className, children, icon, external }: { href: string; variant?: Variant; size?: Size; className?: string; children: ReactNode; icon?: ReactNode; external?: boolean }) {
  if (external) {
    return (
      <a href={href} target="_blank" rel="noreferrer" className={buttonClass(variant, size, className)}>
        {icon}
        {children}
      </a>
    );
  }
  return (
    <Link href={href} className={buttonClass(variant, size, className)}>
      {icon}
      {children}
    </Link>
  );
}

// ---------------------------------------------------------------------------
// Surfaces
// ---------------------------------------------------------------------------

export function Card({ className, children, padded = true }: { className?: string; children: ReactNode; padded?: boolean }) {
  return <section className={cn("rounded-xl border border-line bg-surface shadow-card", padded && "p-5", className)}>{children}</section>;
}

export function CardHeader({ title, description, actions, className }: { title: ReactNode; description?: ReactNode; actions?: ReactNode; className?: string }) {
  return (
    <div className={cn("mb-4 flex flex-wrap items-start justify-between gap-3", className)}>
      <div className="min-w-0">
        <h2 className="text-[15px] font-semibold text-ink">{title}</h2>
        {description && <p className="mt-0.5 text-[13px] text-muted">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

export function PageHeader({ title, description, actions, eyebrow }: { title: ReactNode; description?: ReactNode; actions?: ReactNode; eyebrow?: ReactNode }) {
  return (
    <header className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div className="min-w-0">
        {eyebrow && <div className="mb-1 text-[12px] font-medium uppercase tracking-wide text-muted">{eyebrow}</div>}
        <h1 className="text-[22px] font-semibold tracking-tight text-ink">{title}</h1>
        {description && <p className="mt-1 max-w-3xl text-[13.5px] text-muted">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </header>
  );
}

export function Stat({ label, value, hint, href, tone = "neutral" }: { label: string; value: ReactNode; hint?: ReactNode; href?: string; tone?: "neutral" | "accent" | "warn" | "good" }) {
  const body = (
    <div className={cn("rounded-xl border border-line bg-surface p-4 shadow-card transition", href && "hover:border-accent/40")}>
      <div className="text-[12.5px] font-medium text-muted">{label}</div>
      <div className={cn("mt-1 text-[24px] font-semibold tracking-tight", tone === "accent" && "text-accent", tone === "warn" && "text-warn", tone === "good" && "text-success")}>{value}</div>
      {hint && <div className="mt-0.5 text-[12px] text-muted">{hint}</div>}
    </div>
  );
  return href ? <Link href={href}>{body}</Link> : body;
}

// ---------------------------------------------------------------------------
// Badges and notices
// ---------------------------------------------------------------------------

export type Tone = "neutral" | "accent" | "good" | "warn" | "bad";
const tones: Record<Tone, string> = {
  neutral: "bg-surface2 text-muted border-line",
  accent: "bg-accent-soft text-accent border-transparent",
  good: "bg-success-soft text-success border-transparent",
  warn: "bg-warn-soft text-warn border-transparent",
  bad: "bg-danger-soft text-danger border-transparent",
};

export function Badge({ children, tone = "neutral", className, icon }: { children: ReactNode; tone?: Tone; className?: string; icon?: ReactNode }) {
  return (
    <span className={cn("inline-flex max-w-full items-center gap-1 truncate rounded-md border px-1.5 py-0.5 text-[11.5px] font-medium leading-4", tones[tone], className)}>
      {icon}
      {children}
    </span>
  );
}

export function Notice({ children, tone = "warn", title, action, className }: { children?: ReactNode; tone?: Tone; title?: ReactNode; action?: ReactNode; className?: string }) {
  return (
    <div className={cn("flex flex-wrap items-start justify-between gap-3 rounded-lg border px-3.5 py-2.5 text-[13px]", tones[tone], className)}>
      <div className="min-w-0 text-ink">
        {title && <div className="font-medium">{title}</div>}
        {children && <div className={cn(title && "mt-0.5 text-muted")}>{children}</div>}
      </div>
      {action}
    </div>
  );
}

export function EmptyState({ icon, title, children, action }: { icon?: ReactNode; title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center rounded-xl border border-dashed border-line bg-surface px-6 py-12 text-center">
      {icon && <div className="mb-3 rounded-full bg-surface2 p-3 text-muted">{icon}</div>}
      <h3 className="text-[15px] font-semibold">{title}</h3>
      {children && <div className="mt-1 max-w-md text-[13px] text-muted">{children}</div>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

export function Spinner({ className }: { className?: string }) {
  return <Loader2 className={cn("h-4 w-4 animate-spin text-muted", className)} />;
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={cn("animate-pulse rounded-md bg-surface2", className)} />;
}

export function LoadingBlock({ label = "Loading" }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 py-10 text-[13px] text-muted">
      <Spinner /> {label}…
    </div>
  );
}

export function Meter({ value, label, tone = "accent" }: { value: number | null | undefined; label?: string; tone?: "accent" | "good" | "warn" }) {
  const pct = Math.max(0, Math.min(100, value ?? 0));
  return (
    <div className="min-w-[80px]">
      {label && (
        <div className="mb-1 flex justify-between text-[11.5px] text-muted">
          <span>{label}</span>
          <span className="font-medium text-ink">{value ?? "—"}</span>
        </div>
      )}
      <div className="h-1.5 overflow-hidden rounded-full bg-surface2">
        <div className={cn("h-full rounded-full", tone === "accent" && "bg-accent", tone === "good" && "bg-success", tone === "warn" && "bg-warn")} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Form controls
// ---------------------------------------------------------------------------

const control = "w-full rounded-lg border border-line bg-surface px-3 text-[13.5px] text-ink outline-none transition placeholder:text-faint focus:border-accent focus:ring-2 focus:ring-accent/15";

export function FieldShell({ label, hint, error, children, className }: { label?: ReactNode; hint?: ReactNode; error?: string; children: ReactNode; className?: string }) {
  return (
    <label className={cn("block", className)}>
      {label && <span className="mb-1 block text-[12.5px] font-medium text-ink">{label}</span>}
      {children}
      {hint && !error && <span className="mt-1 block text-[12px] text-muted">{hint}</span>}
      {error && <span className="mt-1 block text-[12px] text-danger">{error}</span>}
    </label>
  );
}

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement> & { label?: ReactNode; hint?: ReactNode; error?: string; wrapperClassName?: string }>(
  function Input({ label, hint, error, className, wrapperClassName, ...props }, ref) {
    return (
      <FieldShell label={label} hint={hint} error={error} className={wrapperClassName}>
        <input ref={ref} className={cn(control, "h-9", className)} {...props} />
      </FieldShell>
    );
  },
);

export function Textarea({ label, hint, error, className, wrapperClassName, ...props }: TextareaHTMLAttributes<HTMLTextAreaElement> & { label?: ReactNode; hint?: ReactNode; error?: string; wrapperClassName?: string }) {
  return (
    <FieldShell label={label} hint={hint} error={error} className={wrapperClassName}>
      <textarea className={cn(control, "min-h-24 py-2 leading-relaxed", className)} {...props} />
    </FieldShell>
  );
}

export function Select({ label, hint, className, wrapperClassName, options, ...props }: SelectHTMLAttributes<HTMLSelectElement> & { label?: ReactNode; hint?: ReactNode; wrapperClassName?: string; options: Array<{ value: string; label: string }> }) {
  return (
    <FieldShell label={label} hint={hint} className={wrapperClassName}>
      <div className="relative">
        <select className={cn(control, "h-9 appearance-none pr-8", className)} {...props}>
          {options.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
        <ChevronDown className="pointer-events-none absolute right-2.5 top-2.5 h-4 w-4 text-muted" />
      </div>
    </FieldShell>
  );
}

export function PasswordField({ label, ...props }: InputHTMLAttributes<HTMLInputElement> & { label: string }) {
  const [visible, setVisible] = useState(false);
  return (
    <FieldShell label={label}>
      <span className="flex overflow-hidden rounded-lg border border-line bg-surface focus-within:border-accent focus-within:ring-2 focus-within:ring-accent/15">
        <input {...props} type={visible ? "text" : "password"} className="h-9 min-w-0 flex-1 bg-transparent px-3 text-[13.5px] outline-none" />
        <button type="button" className="px-3 text-[12px] font-medium text-muted hover:text-ink" aria-label={visible ? `Hide ${label}` : `Show ${label}`} onClick={() => setVisible((current) => !current)}>
          {visible ? "Hide" : "Show"}
        </button>
      </span>
    </FieldShell>
  );
}

export function Switch({ checked, onChange, label, description }: { checked: boolean; onChange: (value: boolean) => void; label?: ReactNode; description?: ReactNode }) {
  return (
    <label className="flex cursor-pointer items-start gap-3">
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        onClick={() => onChange(!checked)}
        className={cn("relative mt-0.5 h-5 w-9 shrink-0 rounded-full transition", checked ? "bg-accent" : "bg-line")}
      >
        <span className={cn("absolute top-0.5 h-4 w-4 rounded-full bg-white shadow transition", checked ? "left-[18px]" : "left-0.5")} />
      </button>
      {(label || description) && (
        <span>
          {label && <span className="block text-[13.5px] font-medium">{label}</span>}
          {description && <span className="block text-[12.5px] text-muted">{description}</span>}
        </span>
      )}
    </label>
  );
}

export function Checkbox({ checked, onChange, label, className }: { checked: boolean; onChange: (value: boolean) => void; label?: ReactNode; className?: string }) {
  return (
    <label className={cn("inline-flex cursor-pointer items-center gap-2 text-[13.5px]", className)} onClick={(event) => event.stopPropagation()}>
      <button
        type="button"
        role="checkbox"
        aria-checked={checked}
        onClick={() => onChange(!checked)}
        className={cn("flex h-4 w-4 shrink-0 items-center justify-center rounded border transition", checked ? "border-accent bg-accent text-accent-ink" : "border-line bg-surface")}
      >
        {checked && <Check className="h-3 w-3" strokeWidth={3} />}
      </button>
      {label}
    </label>
  );
}

/** Toggle chips for choosing one or several options from a short list. */
export function ChipGroup({
  options,
  value,
  onChange,
  multiple = true,
  size = "md",
}: {
  options: Array<{ value: string; label: string; hint?: string }>;
  value: string[];
  onChange: (value: string[]) => void;
  multiple?: boolean;
  size?: "sm" | "md";
}) {
  return (
    <div className="flex flex-wrap gap-1.5">
      {options.map((option) => {
        const active = value.includes(option.value);
        return (
          <button
            key={option.value}
            type="button"
            title={option.hint}
            onClick={() => {
              if (!multiple) onChange([option.value]);
              else onChange(active ? value.filter((item) => item !== option.value) : [...value, option.value]);
            }}
            className={cn(
              "inline-flex items-center gap-1 rounded-full border transition",
              size === "sm" ? "px-2.5 py-1 text-[12px]" : "px-3 py-1.5 text-[13px]",
              active ? "border-accent bg-accent-soft font-medium text-accent" : "border-line bg-surface text-muted hover:border-faint hover:text-ink",
            )}
          >
            {active && <Check className="h-3.5 w-3.5" />}
            {option.label}
          </button>
        );
      })}
    </div>
  );
}

function useOutside(ref: React.RefObject<HTMLElement | null>, onOutside: () => void) {
  useEffect(() => {
    function handle(event: MouseEvent) {
      if (ref.current && !ref.current.contains(event.target as Node)) onOutside();
    }
    document.addEventListener("mousedown", handle);
    return () => document.removeEventListener("mousedown", handle);
  }, [ref, onOutside]);
}

/** Dropdown with checkboxes and search for longer option lists. */
export function MultiSelect({ options, value, onChange, placeholder = "Select", label, className }: { options: Array<{ value: string; label: string }>; value: string[]; onChange: (value: string[]) => void; placeholder?: string; label?: ReactNode; className?: string }) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const ref = useRef<HTMLDivElement>(null);
  useOutside(ref, useCallback(() => setOpen(false), []));
  const filtered = options.filter((option) => option.label.toLowerCase().includes(query.toLowerCase()));
  const selected = options.filter((option) => value.includes(option.value));
  return (
    <div ref={ref} className={cn("relative", className)}>
      {label && <span className="mb-1 block text-[12.5px] font-medium">{label}</span>}
      <button type="button" onClick={() => setOpen((current) => !current)} className={cn(control, "flex h-9 items-center justify-between gap-2 text-left")}>
        <span className={cn("truncate", !selected.length && "text-faint")}>
          {selected.length === 0 ? placeholder : selected.length <= 2 ? selected.map((item) => item.label).join(", ") : `${selected.length} selected`}
        </span>
        <ChevronDown className="h-4 w-4 shrink-0 text-muted" />
      </button>
      {open && (
        <div className="absolute z-30 mt-1 w-full min-w-[220px] overflow-hidden rounded-lg border border-line bg-surface shadow-pop animate-fade-in">
          {options.length > 8 && (
            <div className="flex items-center gap-2 border-b border-line px-2.5">
              <Search className="h-3.5 w-3.5 text-muted" />
              <input autoFocus value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Filter" className="h-9 w-full bg-transparent text-[13px] outline-none" />
            </div>
          )}
          <div className="max-h-64 overflow-auto p-1 scrollbar-thin">
            {filtered.map((option) => {
              const active = value.includes(option.value);
              return (
                <button
                  key={option.value}
                  type="button"
                  onClick={() => onChange(active ? value.filter((item) => item !== option.value) : [...value, option.value])}
                  className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-[13px] hover:bg-surface2"
                >
                  <span className={cn("flex h-4 w-4 items-center justify-center rounded border", active ? "border-accent bg-accent text-accent-ink" : "border-line")}>{active && <Check className="h-3 w-3" strokeWidth={3} />}</span>
                  {option.label}
                </button>
              );
            })}
            {filtered.length === 0 && <div className="px-2 py-2 text-[12.5px] text-muted">No options</div>}
          </div>
          {value.length > 0 && (
            <div className="flex justify-between border-t border-line px-2.5 py-1.5 text-[12px]">
              <button type="button" className="text-muted hover:text-ink" onClick={() => onChange([])}>
                Clear
              </button>
              <button type="button" className="font-medium text-accent" onClick={() => setOpen(false)}>
                Done
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

/** Type-ahead input that adds items as chips. Suggestions are optional; free text is allowed. */
export function TagInput({ value, onChange, suggestions = [], placeholder = "Type and press Enter", label, hint }: { value: string[]; onChange: (value: string[]) => void; suggestions?: string[]; placeholder?: string; label?: ReactNode; hint?: ReactNode }) {
  const [draft, setDraft] = useState("");
  const [focused, setFocused] = useState(false);
  const matches = useMemo(() => {
    const needle = draft.trim().toLowerCase();
    if (!needle) return [];
    return suggestions.filter((item) => item.toLowerCase().includes(needle) && !value.includes(item)).slice(0, 8);
  }, [draft, suggestions, value]);
  function add(item: string) {
    const clean = item.trim();
    if (!clean || value.some((existing) => existing.toLowerCase() === clean.toLowerCase())) return;
    onChange([...value, clean]);
    setDraft("");
  }
  return (
    <FieldShell label={label} hint={hint}>
      <div className="relative">
        <div className={cn(control, "flex min-h-9 flex-wrap items-center gap-1.5 py-1.5")}>
          {value.map((item) => (
            <span key={item} className="inline-flex items-center gap-1 rounded-md bg-surface2 px-2 py-0.5 text-[12.5px]">
              {item}
              <button type="button" className="text-muted hover:text-danger" aria-label={`Remove ${item}`} onClick={() => onChange(value.filter((entry) => entry !== item))}>
                <X className="h-3 w-3" />
              </button>
            </span>
          ))}
          <input
            value={draft}
            onFocus={() => setFocused(true)}
            onBlur={() => setTimeout(() => setFocused(false), 120)}
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" || event.key === ",") {
                event.preventDefault();
                add(matches[0] && draft.length > 1 && matches[0].toLowerCase().startsWith(draft.toLowerCase()) ? matches[0] : draft);
              } else if (event.key === "Backspace" && !draft && value.length) {
                onChange(value.slice(0, -1));
              }
            }}
            placeholder={value.length ? "" : placeholder}
            className="min-w-[120px] flex-1 bg-transparent text-[13.5px] outline-none placeholder:text-faint"
          />
        </div>
        {focused && matches.length > 0 && (
          <div className="absolute z-30 mt-1 w-full overflow-hidden rounded-lg border border-line bg-surface p-1 shadow-pop">
            {matches.map((item) => (
              <button key={item} type="button" onMouseDown={(event) => event.preventDefault()} onClick={() => add(item)} className="block w-full rounded-md px-2 py-1.5 text-left text-[13px] hover:bg-surface2">
                {item}
              </button>
            ))}
          </div>
        )}
      </div>
    </FieldShell>
  );
}

// ---------------------------------------------------------------------------
// Tabs and dialogs
// ---------------------------------------------------------------------------

export function Tabs({ items, value, onChange, className }: { items: Array<{ value: string; label: ReactNode; count?: number }>; value: string; onChange: (value: string) => void; className?: string }) {
  return (
    <div className={cn("flex gap-1 overflow-x-auto border-b border-line scrollbar-thin", className)}>
      {items.map((item) => (
        <button
          key={item.value}
          type="button"
          onClick={() => onChange(item.value)}
          className={cn(
            "-mb-px flex shrink-0 items-center gap-1.5 border-b-2 px-3 py-2 text-[13.5px] transition",
            value === item.value ? "border-accent font-medium text-ink" : "border-transparent text-muted hover:text-ink",
          )}
        >
          {item.label}
          {item.count !== undefined && <span className={cn("rounded-full px-1.5 text-[11px]", value === item.value ? "bg-accent-soft text-accent" : "bg-surface2 text-muted")}>{item.count}</span>}
        </button>
      ))}
    </div>
  );
}

export function Modal({ open, onClose, title, description, children, footer, wide }: { open: boolean; onClose: () => void; title: ReactNode; description?: ReactNode; children: ReactNode; footer?: ReactNode; wide?: boolean }) {
  useEffect(() => {
    if (!open) return;
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") onClose();
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/40 p-4 pt-[8vh]" onMouseDown={onClose}>
      <div className={cn("w-full rounded-xl border border-line bg-surface shadow-pop animate-fade-in", wide ? "max-w-3xl" : "max-w-lg")} onMouseDown={(event) => event.stopPropagation()}>
        <div className="flex items-start justify-between gap-4 border-b border-line px-5 py-4">
          <div>
            <h2 className="text-[15px] font-semibold">{title}</h2>
            {description && <p className="mt-0.5 text-[13px] text-muted">{description}</p>}
          </div>
          <button type="button" onClick={onClose} className="rounded-md p-1 text-muted hover:bg-surface2 hover:text-ink" aria-label="Close">
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="max-h-[70vh] overflow-y-auto px-5 py-4 scrollbar-thin">{children}</div>
        {footer && <div className="flex justify-end gap-2 border-t border-line px-5 py-3">{footer}</div>}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Toasts
// ---------------------------------------------------------------------------

type Toast = { id: number; message: ReactNode; tone: Tone };
const ToastContext = createContext<(message: ReactNode, tone?: Tone) => void>(() => undefined);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const push = useCallback((message: ReactNode, tone: Tone = "neutral") => {
    const id = Date.now() + Math.random();
    setToasts((current) => [...current, { id, message, tone }]);
    setTimeout(() => setToasts((current) => current.filter((toast) => toast.id !== id)), 4500);
  }, []);
  return (
    <ToastContext.Provider value={push}>
      {children}
      <div className="pointer-events-none fixed bottom-4 right-4 z-[60] flex max-w-sm flex-col gap-2">
        {toasts.map((toast) => (
          <div
            key={toast.id}
            className={cn(
              "pointer-events-auto rounded-lg border bg-surface px-3.5 py-2.5 text-[13px] shadow-pop animate-fade-in",
              toast.tone === "bad" && "border-danger/30",
              toast.tone === "good" && "border-success/30",
              toast.tone === "warn" && "border-warn/30",
            )}
          >
            {toast.message}
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast() {
  return useContext(ToastContext);
}

// ---------------------------------------------------------------------------
// Light text formatting (assistant replies and job descriptions)
// ---------------------------------------------------------------------------

function inline(text: string): ReactNode[] {
  const parts = text.split(/(\*\*[^*]+\*\*|_[^_]+_|https?:\/\/\S+)/g);
  return parts.map((part, index) => {
    if (part.startsWith("**") && part.endsWith("**")) return <strong key={index}>{part.slice(2, -2)}</strong>;
    if (part.startsWith("_") && part.endsWith("_") && part.length > 2) return <em key={index} className="text-muted">{part.slice(1, -1)}</em>;
    if (/^https?:\/\//.test(part)) return <a key={index} href={part} target="_blank" rel="noreferrer" className="text-accent underline underline-offset-2">{part}</a>;
    return <span key={index}>{part}</span>;
  });
}

export function RichText({ text, className }: { text: string; className?: string }) {
  const blocks = text.split(/\n{2,}/);
  return (
    <div className={cn("space-y-2 leading-relaxed", className)}>
      {blocks.map((block, index) => {
        const lines = block.split("\n").filter((line) => line.trim());
        const isList = lines.length > 0 && lines.every((line) => /^\s*([-*•]|\d+\.)\s+/.test(line));
        if (isList) {
          const ordered = /^\s*\d+\./.test(lines[0]);
          const Tag = ordered ? "ol" : "ul";
          return (
            <Tag key={index} className={cn("space-y-1 pl-5", ordered ? "list-decimal" : "list-disc")}>
              {lines.map((line, lineIndex) => (
                <li key={lineIndex}>{inline(line.replace(/^\s*([-*•]|\d+\.)\s+/, ""))}</li>
              ))}
            </Tag>
          );
        }
        if (lines.length === 1 && lines[0].length < 60 && !/[.!?:]$/.test(lines[0]) && index > 0 && blocks.length > 2) {
          return <h4 key={index} className="pt-1 font-semibold">{inline(lines[0])}</h4>;
        }
        return (
          <p key={index}>
            {lines.map((line, lineIndex) => (
              <span key={lineIndex}>
                {lineIndex > 0 && <br />}
                {inline(line.replace(/^\s*[-*•]\s+/, "• "))}
              </span>
            ))}
          </p>
        );
      })}
    </div>
  );
}

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="rounded-xl border border-danger/30 bg-danger-soft px-4 py-3 text-[13.5px]">
      <div className="font-medium text-danger">Something went wrong</div>
      <div className="mt-0.5 text-ink/80">{message}</div>
      {onRetry && (
        <button onClick={onRetry} className="mt-2 rounded-md border border-line bg-surface px-2.5 py-1 text-[12.5px] font-medium hover:bg-surface2">
          Try again
        </button>
      )}
    </div>
  );
}
