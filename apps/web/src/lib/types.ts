export type Option = { value: string; label: string };

export type JobCard = {
  id: string;
  title: string;
  company: string;
  location: string | null;
  industry: string | null;
  work_arrangement: string;
  employment_type: string;
  level: string;
  level_label: string;
  level_reason: string | null;
  experience_years: number | null;
  role_family: string | null;
  role_families: string[];
  role_label: string | null;
  location_scope: string;
  location_label: string;
  salary_min: number | null;
  salary_max: number | null;
  salary_currency: string | null;
  source: string;
  source_label: string;
  also_seen_on: Array<{ source: string; label: string; url: string | null }>;
  is_sample: boolean;
  is_user_added: boolean;
  application_url: string | null;
  posted_at: string | null;
  posted_days_ago: number | null;
  expires_at: string | null;
  discovered_at: string | null;
  last_verified_at: string | null;
  is_active: boolean;
  needs_detail: boolean;
  qualification_score: number | null;
  career_interest_score: number | null;
  unverified_skills: string[];
  required_skills: string[];
  preferred_skills: string[];
  matched_skills?: string[];
  missing_skills?: string[];
  relevance?: number;
  relevance_reasons?: string[];
  skill_overlap?: number;
  saved: boolean;
};

export type MatchItem = {
  name: string;
  normalized_name: string;
  category: string;
  priority: string;
  status: string;
  explanation: string;
  raw_text?: string;
};

export type JobDetail = JobCard & {
  description: string;
  responsibilities: string;
  dismissed: boolean;
  match: {
    items: MatchItem[];
    qualification_score: number;
    unknown_count: number;
    disclaimer: string;
    score_basis: string;
    eligibility_conflicts: Array<{ name: string; message: string }>;
    interest_notes: string[];
  };
  verification: { checked: boolean; closed?: boolean; description_updated?: boolean; error?: string } | null;
  portals?: PortalInfo[];
};

export type PortalInfo = {
  portal: "york" | "linkedin" | "web";
  name: string;
  url: string;
  external_id: string;
  application_method: string | null;
  employer_url: string | null;
  deadline: string | null;
  documents: string | null;
  term: string | null;
  easy_apply: boolean | null;
  channels: Array<"york" | "employer" | "linkedin">;
};

export type CaptureStatus = {
  active: boolean;
  portal?: "york" | "linkedin" | "web";
  portal_name?: string;
  phase?: "opening" | "sign_in" | "find_list" | "reading" | "watching" | "ended";
  message?: string;
  term?: string;
  saved?: Array<{ id: string; title: string; company: string; state: string }>;
  saved_count?: number;
  skipped?: number;
  already?: number;
  failed?: number;
};

export type SubmitChannel = {
  key: "york" | "employer" | "linkedin";
  name: string;
  url: string | null;
  deadline: string | null;
  documents: string | null;
  how: string;
  done: boolean;
  done_at: string | null;
};

export type JobPage = {
  items: JobCard[];
  total: number;
  page: number;
  page_size: number;
  facets: Record<string, Record<string, number>>;
  hidden: {
    total: number;
    by_level: Record<string, number>;
    by_scope: Record<string, number>;
    other_roles: number;
    older: number;
    excluded: number;
    dismissed: number;
  };
};

export type SearchProfile = {
  id: string;
  name: string;
  is_default: boolean;
  role_families: string[];
  custom_titles: string[];
  levels: string[];
  location_scopes: string[];
  city: string;
  include_keywords: string[];
  exclude_keywords: string[];
  exclude_companies: string[];
  employment_types: string[];
  work_arrangements: string[];
  posted_within_days: number | null;
  auto_refresh: boolean;
  refresh_hours: number;
  last_run_at: string | null;
};

export type ProfileOptions = {
  role_families: Option[];
  levels: Option[];
  location_scopes: Option[];
  employment_types: Option[];
  work_arrangements: Option[];
  posted_within_days: number[];
  defaults: { role_families: string[]; levels: string[]; location_scopes: string[] };
  cities: string[];
};

export type DiscoveryStatus = {
  id: string;
  status: string;
  done: boolean;
  created: number;
  updated: number;
  duplicates: number;
  expired: number;
  found?: number;
  sources: Record<string, { label: string; kind: string; status: string; found: number; new: number; error?: string; scanned?: number }>;
  errors: Array<{ source: string; label?: string; message: string }>;
  started_at: string | null;
  finished_at: string | null;
};

export type Question = {
  id: string;
  job_posting_id: string | null;
  job?: { title: string; company: string } | null;
  normalized_name: string;
  display_name: string;
  prompt: string;
  priority: string;
  min_years: number | null;
};

export type Answer = {
  key: string;
  prompt: string;
  answer: string;
  sensitive: boolean;
  requires_user: boolean;
  deferred?: boolean;
  draft?: boolean;
  from_saved?: boolean;
};

export type ResumeSummary = {
  id: string;
  title: string;
  format: string;
  generation: { method: string; provider?: string | null; note?: string; rejected?: unknown[] } | null;
  keywords: { covered: string[]; missing: string[] } | null;
  change_count: number;
};

export type Application = {
  id: string;
  job_posting_id: string;
  title: string | null;
  company: string | null;
  location: string | null;
  application_url: string | null;
  status: string;
  stage: string;
  submission_label: string | null;
  open_questions: number;
  source: string | null;
  source_label: string | null;
  is_sample: boolean;
  posting_active: boolean;
  draft_version: number;
  resume_version_id: string | null;
  cover_letter_id: string | null;
  submission_method: string | null;
  is_live_submission: boolean;
  confirmation_id: string | null;
  notes: string;
  approval_valid: boolean;
  autoapply?: AutoApplySupport;
  submit_on?: SubmitChannel[];
  interview_at: string | null;
  created_at: string | null;
  updated_at: string | null;
  resume: ResumeSummary | null;
  answers?: Answer[];
  cover_letter?: string | null;
  cover_letter_tone?: string | null;
  questions?: Question[];
  job?: { description: string; employment_type: string | null; work_arrangement: string | null; posted_at: string | null };
  apply_guide?: { platform: string | null; url: string; steps: string[]; submission_note: string };
};

export type DocEntry = {
  id: string;
  headers: Array<{ text: string; right: string; bold?: boolean; italic?: boolean }>;
  bullets: Array<{ id: string; text: string; hidden?: boolean }>;
  tech: string | null;
};

export type DocSection = {
  id: string;
  key: string;
  title: string;
  kind: "paragraphs" | "skills" | "entries" | "list";
  paragraphs?: Array<{ id: string; text: string }>;
  groups?: Array<{ id: string; label: string | null; items: string[] }>;
  entries?: DocEntry[];
  items?: Array<{ id: string; text: string; right?: string }>;
};

export type ResumeDocument = {
  header: { name: string; contact_items: string[] };
  sections: DocSection[];
};

export type Change = {
  id: string;
  kind: string;
  section?: string;
  entry_id?: string;
  bullet_id?: string;
  paragraph_id?: string;
  entry?: string;
  group?: string | null;
  skill?: string;
  before?: unknown;
  after?: unknown;
  names?: string[];
  added?: string[];
  omitted?: string[];
  reason?: string;
  problems?: string[];
  evidence?: string | null;
};

export type ChatEdit = { op: string; target: string; before?: string; after?: string; reason?: string; entry?: string; text?: string; problems?: string[] };

export type ResumeChatMessage = { role: "user" | "assistant"; text: string; at: string; applied?: ChatEdit[]; blocked?: ChatEdit[] };

export type ResumeVersion = ResumeSummary & {
  job_posting_id: string | null;
  kind: string;
  created_at: string | null;
  approved_by_user?: boolean;
  can_undo?: boolean;
  private_job?: boolean;
  turn?: ResumeChatMessage;
  content?: {
    format: string;
    origin?: string;
    source_resume_id?: string | null;
    document?: ResumeDocument;
    original_document?: ResumeDocument;
    changes?: Change[];
    fit?: { pages: number; target_pages: number; fits: boolean };
    job?: { id: string; title: string; company: string };
    generation?: ResumeSummary["generation"] & { notes?: string[]; rejected?: Change[] };
    keywords?: { covered: string[]; missing: string[] };
    chat?: ResumeChatMessage[];
  };
  text?: string;
  warnings?: string[];
};

export type OriginalResume = {
  id: string;
  filename: string;
  content_type: string;
  parse_status: string;
  size_bytes: number;
  review_notes: string | null;
  parser: string | null;
  is_primary: boolean;
  extraction: Extraction;
  approved_at: string | null;
  created_at: string | null;
  has_layout: boolean;
};

export type ExtractedSkill = {
  name: string;
  original?: string;
  normalized_name: string;
  category: string;
  group: string | null;
  needs_review: boolean;
  found_in: string;
  accepted?: boolean;
};

export type ExtractedRole = {
  title: string;
  employer: string;
  location: string | null;
  start_date: string | null;
  end_date: string | null;
  is_current: boolean;
  responsibilities: string[];
  technologies: string[];
  needs_review: boolean;
  rejected?: boolean;
};

export type ExtractedSchool = {
  institution: string;
  degree: string | null;
  program: string | null;
  location: string | null;
  graduation_date: string | null;
  coursework: string | null;
  gpa: string | null;
  needs_review: boolean;
  rejected?: boolean;
};

export type ExtractedProject = {
  name: string;
  status: string | null;
  technologies: string[];
  bullets: string[];
  description: string;
  url: string | null;
  rejected?: boolean;
};

export type Extraction = {
  contact: Record<string, unknown> & { full_name?: string; email?: string | null; phone?: string | null; location?: string | null; linkedin_url?: string | null; github_url?: string | null; placeholders?: string[] };
  summary: string;
  skills: ExtractedSkill[];
  skill_groups: Array<{ label: string | null; items: string[] }>;
  experience: ExtractedRole[];
  education: ExtractedSchool[];
  projects: ExtractedProject[];
  certifications: Array<{ name: string; issuer: string | null; issue_date: string | null; needs_review: boolean; rejected?: boolean }>;
  warnings: string[];
  parser?: string;
};

export type ProfileSkill = {
  id: string;
  name: string;
  normalized_name: string;
  category: string;
  proficiency: string | null;
  confirmation_status: string;
  source: string;
  context: string | null;
  duration_months: number | null;
};

export type Profile = {
  id: string;
  full_name: string;
  phone: string | null;
  location: string | null;
  portfolio_url: string | null;
  linkedin_url: string | null;
  github_url: string | null;
  headline: string | null;
  summary: string | null;
  education: Array<{ id: string; institution: string; degree: string | null; program: string | null; graduation_date: string | null; coursework: string | null; achievements: string | null; source: string }>;
  experience: Array<{ id: string; employer: string; title: string; location: string | null; start_date: string | null; end_date: string | null; is_current: boolean; responsibilities: string[]; technologies: string[]; source: string }>;
  projects: Array<{ id: string; name: string; description: string; technologies: string[]; responsibilities: string; results: string; url: string | null; source: string }>;
  skills: ProfileSkill[];
  certifications: Array<{ id: string; name: string; issuer: string | null; issue_date: string | null; source: string }>;
};

export type Home = {
  name: string;
  checklist: Array<{ key: string; label: string; done: boolean; href: string }>;
  ai_configured: boolean;
  matches_total: number;
  new_this_week: number;
  top_matches: JobCard[];
  hidden: JobPage["hidden"];
  open_questions: number;
  pipeline: Record<string, number>;
  last_discovery: DiscoveryStatus | null;
  search_profile: SearchProfile;
};

export type ChatBlock =
  | { type: "jobs"; ids: string[] }
  | { type: "applications"; ids: string[] }
  | { type: "resume"; version_id: string; title: string }
  | { type: "questions"; count: number; job_id: string | null }
  | { type: "discovery"; task_id: string }
  | { type: "search_profile"; id: string };

export type ChatMessage = { id?: string; role: "user" | "assistant"; text: string; blocks: ChatBlock[]; created_at?: string; pending?: boolean; usage?: { cost_usd: number; requests: number; model: string } | null };

export type Health = {
  status: string;
  demo_mode: boolean;
  integrations: { ai: boolean; email?: boolean; environment?: string; ai_provider: string; ai_model: string | null; adzuna: boolean; public_job_sources: boolean; submission_methods: string[]; live_submission: string[] };
};

export type AIUsageTotal = { cost_usd: number; requests: number; input_tokens: number; output_tokens: number; cached_tokens: number };

export type AIUsage = {
  configured: boolean;
  provider: string;
  quality_model: "sonnet" | "opus";
  models: Record<"quality" | "fast", { id: string; label: string; used_for: string }>;
  spend_limit_usd: number;
  default_spend_limit_usd: number;
  totals: Record<"all_time" | "this_month" | "last_7_days" | "today", AIUsageTotal>;
  remaining_usd: number;
  limit_reached: boolean;
  cache_hits: number;
  by_feature: Array<AIUsageTotal & { feature: string; label: string }>;
  by_model: Array<AIUsageTotal & { model: string; label: string }>;
  recent: Array<{ at: string; feature: string; model: string; input_tokens: number; cached_tokens: number; output_tokens: number; cost_usd: number; ok: boolean }>;
  note: string;
};

export type AutoApplySupport = { platform: string | null; level: "full" | "assisted" | "none"; note: string };

export type ApplyQuestion = {
  key: string;
  label: string;
  kind: string;
  options: string[];
  category: string | null;
  remember: boolean;
  required?: boolean;
  status?: "drafted" | "needs_answer";
  draft?: string;
  basis?: string;
  problems?: string[];
};

export type ApplyFilled = { key?: string; kind?: string; label: string; value: string; source: string; basis?: string; page: string };
export type ApplyDocument = { kind: "resume" | "cover_letter"; file: string; slot: string; version_id?: string; title?: string; sha256?: string };

export type ApplyRun = {
  id: string;
  application_id: string;
  batch_id: string | null;
  title: string | null;
  company: string | null;
  platform: string;
  status: "queued" | "running" | "needs_you" | "submitted" | "failed" | "cancelled" | "handed_off" | "interrupted";
  submit_mode: "auto" | "review";
  attention: "login" | "captcha" | "verification" | "questions" | "review_answers" | "review" | "blocked" | "unconfirmed" | "error" | null;
  message: string;
  questions: ApplyQuestion[];
  events: Array<{ at: string; message: string }>;
  filled_count: number;
  filled: ApplyFilled[];
  documents: ApplyDocument[];
  submit_clicked: boolean;
  confirmation_text: string | null;
  confirmation_url: string | null;
  has_screenshot: boolean;
  application_status: string | null;
  tab_open?: boolean;
  created_at: string | null;
  updated_at: string | null;
  finished_at: string | null;
};
