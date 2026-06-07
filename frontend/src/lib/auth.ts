// Token + identity storage. Dev-grade: the JWT lives in localStorage and is
// attached to API calls and the WS handshake. (Per comet conventions this is the
// single place auth state is read/written.)
import type { Role } from "./types";

const TOKEN_KEY = "axon.token";
const USER_KEY = "axon.user";

export interface Session {
  token: string;
  userId: string;
  role: Role;
}

export function saveSession(s: Session): void {
  if (typeof window === "undefined") return;
  localStorage.setItem(TOKEN_KEY, s.token);
  localStorage.setItem(USER_KEY, JSON.stringify({ userId: s.userId, role: s.role }));
}

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(TOKEN_KEY);
}

export function getSession(): Session | null {
  if (typeof window === "undefined") return null;
  const token = localStorage.getItem(TOKEN_KEY);
  const raw = localStorage.getItem(USER_KEY);
  if (!token || !raw) return null;
  try {
    const { userId, role } = JSON.parse(raw);
    return { token, userId, role };
  } catch {
    return null;
  }
}

export function clearSession(): void {
  if (typeof window === "undefined") return;
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(USER_KEY);
}
