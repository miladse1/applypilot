import { NextRequest, NextResponse } from "next/server";
import { isTrustedWrite } from "@/lib/csrf";

const API_URL = process.env.API_URL || "http://127.0.0.1:8000";

async function proxy(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  if (!isTrustedWrite(request.method, request.headers.get("origin"), request.headers.get("host"), request.headers.get("sec-fetch-site"))) {
    return NextResponse.json({ detail: { code: "forbidden_origin", message: "This request did not come from ApplyPilot." } }, { status: 403 });
  }
  const { path } = await context.params;
  const target = `${API_URL}/api/v1/${path.join("/")}${request.nextUrl.search}`;
  const headers = new Headers();
  const contentType = request.headers.get("content-type");
  if (contentType) headers.set("content-type", contentType);
  const token = request.cookies.get("applypilot_session")?.value;
  if (token) headers.set("authorization", `Bearer ${token}`);
  const method = request.method;
  let upstream: Response;
  try {
    upstream = await fetch(target, {
      method,
      headers,
      body: method === "GET" || method === "HEAD" ? undefined : await request.arrayBuffer(),
      cache: "no-store",
    });
  } catch {
    return NextResponse.json(
      { detail: { code: "api_unreachable", message: `The ApplyPilot API is not running at ${API_URL}. Start it with ./dev.sh.` } },
      { status: 502 },
    );
  }
  const responseType = upstream.headers.get("content-type") || "";
  if (!responseType.includes("application/json")) {
    const response = new NextResponse(await upstream.arrayBuffer(), { status: upstream.status });
    if (responseType) response.headers.set("content-type", responseType);
    const disposition = upstream.headers.get("content-disposition");
    if (disposition) response.headers.set("content-disposition", disposition);
    return response;
  }
  const payload = await upstream.json().catch(() => ({}));
  const tokenValue = payload?.session_token as string | undefined;
  if (payload && typeof payload === "object") delete payload.session_token;
  const response = NextResponse.json(payload, { status: upstream.status });
  if (tokenValue) {
    response.cookies.set("applypilot_session", tokenValue, {
      httpOnly: true,
      sameSite: "lax",
      path: "/",
      secure: process.env.COOKIE_SECURE === "true",
      maxAge: 60 * 60 * 12,
    });
  }
  if (path.join("/") === "auth/logout") {
    response.cookies.set("applypilot_session", "", { httpOnly: true, path: "/", maxAge: 0 });
  }
  return response;
}

export const GET = proxy;
export const POST = proxy;
export const PATCH = proxy;
export const PUT = proxy;
export const DELETE = proxy;
