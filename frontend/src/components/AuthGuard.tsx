"use client";
import { useRouter } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";
import { getSession } from "@/lib/auth";

/** Client-side guard: redirect to /login when there is no session. */
export function AuthGuard({ children }: { children: ReactNode }) {
  const router = useRouter();
  const [ok, setOk] = useState(false);

  useEffect(() => {
    if (getSession()) setOk(true);
    else router.replace("/login");
  }, [router]);

  if (!ok) return null;
  return <>{children}</>;
}
