// The single place `fetch` is used. All backend HTTP goes through here.
import { getToken } from "./auth";
import type {
  Checkout,
  NodeState,
  Role,
  SpineSummary,
  SpineWithNodes,
} from "./types";

export const API_BASE =
  process.env.NEXT_PUBLIC_AXON_API_BASE ?? "http://localhost:4100";

export function wsBase(): string {
  return API_BASE.replace(/^http/, "ws");
}

class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const token = getToken();
  const headers = new Headers(init.headers);
  headers.set("Content-Type", "application/json");
  if (token) headers.set("Authorization", `Bearer ${token}`);

  const res = await fetch(`${API_BASE}${path}`, { ...init, headers });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      detail = (await res.json()).detail ?? detail;
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(res.status, detail);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export async function issueToken(userId: string, role: Role): Promise<string> {
  const { token } = await request<{ token: string }>("/auth/token", {
    method: "POST",
    body: JSON.stringify({ user_id: userId, role }),
  });
  return token;
}

export const listSpines = () => request<SpineSummary[]>("/graph/spines");

export const getSpine = (spineId: string) =>
  request<SpineWithNodes>(`/graph/spines/${spineId}`);

export const createCheckout = (spineId: string | null, subject: string | null) =>
  request<Checkout>("/library/checkout", {
    method: "POST",
    body: JSON.stringify({ spine_id: spineId, subject }),
  });

export const getOverlay = (checkoutId: string) =>
  request<NodeState[]>(`/library/checkout/${checkoutId}`);

export { ApiError };
