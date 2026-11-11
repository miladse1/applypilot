import { redirect } from "next/navigation";

export default async function MovedStudio({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  redirect(`/resume/versions/${id}`);
}
