export function skillStatusLabel(status: string): string {
  const labels: Record<string, string> = {
    matched: "Matched",
    unverified: "Not on your profile yet",
    partial: "Partial match",
    in_progress: "Learning",
    not_possessed: "You don't have this",
    confirmed: "Confirmed",
    pending_review: "Pending review",
    unsure: "Unsure",
    skipped: "Skipped",
  };
  return labels[status] ?? status;
}

export function applicationStatusLabel(status: string): string {
  const labels: Record<string, string> = {
    preparing: "Preparing",
    awaiting_skill_verification: "Needs your answers",
    awaiting_review: "Ready for review",
    approved: "Approved",
    submitting: "Submitting",
    manual_action_required: "Finish on employer site",
    submitted: "Submitted",
    failed: "Submission failed",
    interview: "Interviewing",
    offer: "Offer",
    rejected: "Rejected",
    withdrawn: "Withdrawn",
  };
  return labels[status] ?? status.split("_").join(" ");
}

export function undocumentedMeansMissing(status: string): boolean {
  return status === "not_possessed";
}

export const STAGE_TONE: Record<string, "neutral" | "accent" | "good" | "warn" | "bad"> = {
  preparing: "neutral",
  awaiting_skill_verification: "warn",
  awaiting_review: "accent",
  approved: "good",
  manual_action_required: "warn",
  submitted: "good",
  failed: "bad",
  interview: "accent",
  offer: "good",
  rejected: "neutral",
  withdrawn: "neutral",
};
