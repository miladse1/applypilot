export const skillMatchStatuses = [
  "matched",
  "unverified",
  "partial",
  "in_progress",
  "not_possessed",
] as const;

export const applicationStatuses = [
  "discovered",
  "saved",
  "preparing",
  "awaiting_skill_verification",
  "awaiting_review",
  "approved",
  "submitting",
  "submitted",
  "manual_action_required",
  "failed",
  "interview",
  "offer",
  "rejected",
  "withdrawn",
] as const;

export type SkillMatchStatus = (typeof skillMatchStatuses)[number];
export type ApplicationStatus = (typeof applicationStatuses)[number];

export function skillStatusLabel(status: string): string {
  const labels: Record<string, string> = {
    matched: "Matched",
    unverified: "Needs your confirmation",
    partial: "Partial match",
    in_progress: "Learning",
    not_possessed: "Not currently possessed",
    unsure: "Unsure",
    skipped: "Skipped",
    confirmed: "Confirmed",
    pending_review: "Pending review",
  };
  return labels[status] ?? status;
}
