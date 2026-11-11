export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body && !(init.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const response = await fetch(`/api/v1${path}`, { ...init, headers, credentials: "include" });
  if (response.status === 204) return undefined as T;
  const type = response.headers.get("content-type") || "";
  if (!type.includes("application/json")) {
    if (!response.ok) throw new ApiError(response.status, "Request failed");
    return (await response.blob()) as T;
  }
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = payload.detail;
    const message = typeof detail === "string" ? detail : detail?.message || "Request failed";
    throw new ApiError(response.status, message);
  }
  return payload as T;
}
