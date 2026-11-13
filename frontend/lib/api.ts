// Thin fetch wrapper for the FastAPI service (shared §7). Errors come back as values, never thrown,
// so every screen can show "not available yet" instead of crashing while endpoints are still landing.
import type { ApiError } from "./types";

export const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";

export type Result<T> = { ok: true; data: T } | { ok: false; status: number; message: string };

export async function api<T>(path: string, init?: { method?: string; body?: unknown }): Promise<Result<T>> {
  try {
    const res = await fetch(`${API_BASE}${path}`, {
      method: init?.method ?? "GET",
      headers: init?.body !== undefined ? { "Content-Type": "application/json" } : undefined,
      body: init?.body !== undefined ? JSON.stringify(init.body) : undefined,
      cache: "no-store",
    });
    const text = await res.text();
    const json = text ? JSON.parse(text) : null;
    if (!res.ok) {
      const err = json as Partial<ApiError> & { detail?: unknown };
      const message =
        err?.error?.message ??
        (res.status === 404 ? "This endpoint is not available on the API yet." : JSON.stringify(err?.detail ?? json));
      return { ok: false, status: res.status, message };
    }
    return { ok: true, data: json as T };
  } catch (e) {
    return { ok: false, status: 0, message: `Cannot reach the API at ${API_BASE} (${(e as Error).message})` };
  }
}
