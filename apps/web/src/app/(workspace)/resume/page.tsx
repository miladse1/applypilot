"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useRef, useState } from "react";
import { Download, Eye, FileText, RefreshCw, Replace, Star, Trash2, Upload } from "lucide-react";
import { PdfFrame } from "@/components/pdf-frame";
import { Badge, Button, Card, CardHeader, EmptyState, ErrorState, LinkButton, LoadingBlock, Modal, Notice, PageHeader, useToast } from "@/components/ui";
import { api } from "@/lib/api";
import { fullDate } from "@/lib/format";
import { errorMessage, useApi } from "@/lib/hooks";
import type { OriginalResume, ResumeVersion } from "@/lib/types";

export default function ResumePage() {
  const router = useRouter();
  const toast = useToast();
  const { data: resumes, reload, error: resumesError } = useApi<OriginalResume[]>("/resumes");
  const { data: versions, error: versionsError, reload: reloadVersions } = useApi<ResumeVersion[]>("/resume-versions");
  const [preview, setPreview] = useState<OriginalResume | null>(null);
  const [deleting, setDeleting] = useState<OriginalResume | null>(null);
  const [busy, setBusy] = useState("");
  const fileInput = useRef<HTMLInputElement>(null);
  const replaceTarget = useRef<string | null>(null);

  async function act(key: string, action: () => Promise<unknown>, message: string) {
    setBusy(key);
    try {
      await action();
      toast(message, "good");
      await reload();
    } catch (err) {
      toast(errorMessage(err), "bad");
    } finally {
      setBusy("");
    }
  }

  function chooseFile(replaceId: string | null) {
    replaceTarget.current = replaceId;
    fileInput.current?.click();
  }

  async function upload(file: File) {
    const replaceId = replaceTarget.current;
    setBusy(replaceId ? `replace-${replaceId}` : "upload");
    const form = new FormData();
    form.append("file", file);
    try {
      const created = await api<OriginalResume>(`/resumes${replaceId ? `?replace=${replaceId}` : ""}`, { method: "POST", body: form });
      toast(replaceId ? "Replaced. Check what was read and save it to update your profile." : "Uploaded. Check what was read and save it.", "good");
      router.push(`/onboarding?resume=${created.id}`);
    } catch (err) {
      toast(errorMessage(err, "Upload failed"), "bad");
      setBusy("");
    } finally {
      if (fileInput.current) fileInput.current.value = "";
    }
  }

  const tailored = (versions || []).filter((item) => item.kind === "tailored");
  const stale = (resumes || []).some((item) => item.is_primary && !item.has_layout);

  return (
    <div>
      <input ref={fileInput} type="file" accept=".pdf,.docx" className="hidden" onChange={(event) => event.target.files?.[0] && upload(event.target.files[0])} />
      <PageHeader
        title="Resume"
        description="Your uploaded resume is never modified. Each job gets a tailored copy that keeps your layout and only uses facts you have confirmed."
        actions={
          <Button icon={<Upload className="h-4 w-4" />} loading={busy === "upload"} onClick={() => chooseFile(null)}>
            Upload a resume
          </Button>
        }
      />
      {stale && (
        <Notice tone="warn" className="mb-4" title="Your resume was read with the old parser">
          Re-read it and check the result so tailoring uses your real content.
        </Notice>
      )}
      <Card className="mb-6">
        <CardHeader title="Original resumes" description="The main resume is the one ApplyPilot tailors. Replacing it uploads a new file, makes it the main resume, and removes the old file." />
        {resumesError ? (
          <ErrorState message={resumesError} onRetry={reload} />
        ) : !resumes ? (
          <LoadingBlock />
        ) : resumes.length === 0 ? (
          <EmptyState icon={<FileText className="h-5 w-5" />} title="No resume yet" action={<Button onClick={() => chooseFile(null)}>Upload your resume</Button>}>
            Upload a PDF or DOCX to get started.
          </EmptyState>
        ) : (
          <div className="divide-y divide-line">
            {resumes.map((row) => (
              <div key={row.id} className="flex flex-wrap items-center justify-between gap-3 py-3">
                <div className="flex min-w-0 items-center gap-3">
                  <div className="rounded-lg bg-surface2 p-2 text-muted">
                    <FileText className="h-5 w-5" />
                  </div>
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="truncate text-[14px] font-medium">{row.filename}</span>
                      {row.is_primary && <Badge tone="accent">Main</Badge>}
                      {row.approved_at ? <Badge tone="good">Saved to profile</Badge> : <Badge tone="warn">Needs review</Badge>}
                    </div>
                    <div className="text-[12px] text-muted">
                      Uploaded {fullDate(row.created_at)} · {Math.round(row.size_bytes / 1024)} KB · {row.extraction?.experience?.length || 0} roles, {row.extraction?.projects?.length || 0} projects, {row.extraction?.skills?.length || 0} skills
                    </div>
                  </div>
                </div>
                <div className="flex flex-wrap gap-1.5">
                  <Button size="sm" variant="ghost" icon={<Eye className="h-3.5 w-3.5" />} onClick={() => setPreview(row)}>
                    Preview
                  </Button>
                  <LinkButton href={`/api/v1/resumes/${row.id}/file`} external size="sm" variant="ghost" icon={<Download className="h-3.5 w-3.5" />}>
                    Original
                  </LinkButton>
                  <Button size="sm" variant="ghost" icon={<RefreshCw className="h-3.5 w-3.5" />} loading={busy === `reparse-${row.id}`} onClick={() => act(`reparse-${row.id}`, async () => { await api(`/resumes/${row.id}/reparse`, { method: "POST" }); router.push(`/onboarding?resume=${row.id}`); }, "Read again. Review it and save to update your profile.")}>
                    Re-read
                  </Button>
                  {!row.is_primary && (
                    <Button size="sm" variant="ghost" icon={<Star className="h-3.5 w-3.5" />} loading={busy === `primary-${row.id}`} onClick={() => act(`primary-${row.id}`, () => api(`/resumes/${row.id}/primary`, { method: "POST" }), "Set as your main resume.")}>
                      Make main
                    </Button>
                  )}
                  <Button size="sm" variant="secondary" icon={<Replace className="h-3.5 w-3.5" />} loading={busy === `replace-${row.id}`} onClick={() => chooseFile(row.id)}>
                    Replace
                  </Button>
                  <LinkButton href={`/onboarding?resume=${row.id}`} size="sm" variant="secondary">
                    Review
                  </LinkButton>
                  <Button size="sm" variant="ghost" aria-label={`Delete ${row.filename}`} icon={<Trash2 className="h-3.5 w-3.5" />} onClick={() => setDeleting(row)} />
                </div>
              </div>
            ))}
          </div>
        )}
      </Card>

      <Card>
        <CardHeader title="Tailored versions" description="One per job you tailored for or applied to." />
        {versionsError ? (
          <ErrorState message={versionsError} onRetry={reloadVersions} />
        ) : !versions ? (
          <LoadingBlock />
        ) : tailored.length === 0 ? (
          <p className="text-[13px] text-muted">None yet. Open a job and choose “Tailor my resume”.</p>
        ) : (
          <div className="divide-y divide-line">
            {tailored.map((version) => (
              <Link key={version.id} href={`/resume/versions/${version.id}`} className="flex flex-wrap items-center justify-between gap-2 py-2.5 hover:text-accent">
                <div className="min-w-0">
                  <div className="truncate text-[13.5px] font-medium">{version.title}</div>
                  <div className="text-[12px] text-muted">
                    {fullDate(version.created_at)} · {version.change_count} change{version.change_count === 1 ? "" : "s"}
                    {version.keywords && ` · ${version.keywords.covered.length} of ${version.keywords.covered.length + version.keywords.missing.length} job keywords covered`}
                  </div>
                </div>
                <div className="flex gap-1.5">
                  {version.format !== "document" && <Badge>Older format</Badge>}
                  <Badge tone={version.generation?.method === "ai" ? "accent" : "neutral"}>{version.generation?.method === "ai" ? "Rewritten by Claude" : "Reordered & highlighted"}</Badge>
                </div>
              </Link>
            ))}
          </div>
        )}
      </Card>

      <Modal open={Boolean(preview)} onClose={() => setPreview(null)} title={preview?.filename || ""} wide>
        {preview && <PdfFrame src={`/api/v1/resumes/${preview.id}/preview`} title="Resume preview" className="h-[75vh] rounded-lg border border-line" />}
      </Modal>

      <Modal
        open={Boolean(deleting)}
        onClose={() => setDeleting(null)}
        title={`Delete ${deleting?.filename || ""}?`}
        description="The file is removed from ApplyPilot. Your profile, saved answers, and tailored versions made from it are kept."
        footer={
          <>
            <Button variant="secondary" onClick={() => setDeleting(null)}>Cancel</Button>
            <Button
              variant="danger"
              loading={busy === "delete"}
              onClick={() =>
                deleting &&
                act("delete", async () => {
                  await api(`/resumes/${deleting.id}`, { method: "DELETE" });
                  setDeleting(null);
                }, "Resume deleted.")
              }
            >
              Delete
            </Button>
          </>
        }
      >
        {deleting?.is_primary && <Notice tone="warn">This is your main resume. {resumes && resumes.length > 1 ? "Your next most recent resume becomes the main one." : "Upload a new one before tailoring again."}</Notice>}
      </Modal>
    </div>
  );
}
