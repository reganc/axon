// The single place `fetch` is used. All backend HTTP goes through here.
import { getToken, clearSession } from "./auth";
import type { VoiceConfig } from "./config";
import type {
  Checkout,
  CheckoutSummary,
  EdgeDTO,
  Facets,
  NodeDTO,
  NodeState,
  Role,
  SpineSummary,
  SpineWithNodes,
  StreamEvent,
} from "./types";

// The browser makes every API call, so the API host must be one the *browser*
// can reach — not the server's `localhost`. Derive it from however the page was
// reached (localhost, a LAN IP, Tailscale, …) so the app works from any origin
// without a per-host rebuild. An explicit env override always wins; the port is
// the backend's AXON_API_PORT (4100), overridable for non-standard setups.
const API_PORT = process.env.NEXT_PUBLIC_AXON_API_PORT ?? "4100";

function defaultApiBase(): string {
  if (typeof window !== "undefined") {
    return `${window.location.protocol}//${window.location.hostname}:${API_PORT}`;
  }
  return `http://localhost:${API_PORT}`;
}

export const API_BASE =
  process.env.NEXT_PUBLIC_AXON_API_BASE ?? defaultApiBase();

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

/**
 * Human-readable message for a caught value, preferring the API's `detail`.
 * `fetch` rejects with a `TypeError` when the host is unreachable — surface that
 * as an actionable hint rather than a generic fallback, since a dead backend is
 * the most common cause of an otherwise-mysterious "X failed".
 */
export function errorMessage(e: unknown, fallback: string): string {
  if (e instanceof ApiError) return e.message;
  if (e instanceof TypeError)
    return `${fallback}: can't reach the API — is the backend running?`;
  if (e instanceof Error && e.message) return e.message;
  return fallback;
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const token = getToken();
  const headers = new Headers(init.headers);
  headers.set("Content-Type", "application/json");
  if (token) headers.set("Authorization", `Bearer ${token}`);

  const res = await fetch(`${API_BASE}${path}`, { ...init, headers });
  if (res.status === 401 && typeof window !== "undefined") {
    // Stale/expired/invalid token: drop it and bounce to login rather than
    // stranding the user on a guarded page where every call 401s. AuthGuard
    // only checks token *presence*, so it can't recover from a bad token alone.
    clearSession();
    if (!window.location.pathname.startsWith("/login")) {
      window.location.href = "/login";
    }
  }
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

export const listEntryPoints = () => request<NodeDTO[]>("/library/entry-points");

export const getFacets = () => request<Facets>("/browse/facets");

export interface ScoredNodeDTO {
  node: NodeDTO;
  score: number;
}

export function searchNodes(q: string, kinds?: string[]): Promise<ScoredNodeDTO[]> {
  const params = new URLSearchParams({ q });
  if (kinds?.length) params.set("kinds", kinds.join(","));
  return request<ScoredNodeDTO[]>(`/library/search?${params.toString()}`);
}

export function listNodes(kinds?: string[], limit = 60): Promise<NodeDTO[]> {
  const params = new URLSearchParams({ limit: String(limit) });
  if (kinds?.length) params.set("kinds", kinds.join(","));
  return request<NodeDTO[]>(`/graph/nodes?${params.toString()}`);
}

export interface SubgraphDTO {
  nodes: NodeDTO[];
  edges: EdgeDTO[];
}

export const getNodeSubgraph = (nodeId: string) =>
  request<SubgraphDTO>(`/graph/nodes/${nodeId}`);

export const getSpine = (spineId: string) =>
  request<SpineWithNodes>(`/graph/spines/${spineId}`);

export const createCheckout = (spineId: string | null, subject: string | null) =>
  request<Checkout>("/library/checkout", {
    method: "POST",
    body: JSON.stringify({ spine_id: spineId, subject }),
  });

export const getOverlay = (checkoutId: string) =>
  request<NodeState[]>(`/library/checkout/${checkoutId}`);

export const listCheckouts = () => request<CheckoutSummary[]>("/library/checkouts");

export const getConversation = (checkoutId: string) =>
  request<StreamEvent[]>(`/library/checkout/${checkoutId}/conversation`);

export const getVoiceConfig = () => request<VoiceConfig>("/voice/config");

export { ApiError };
