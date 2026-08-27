import { useCallback, useEffect, useState } from "react";

export interface Session {
  userId: number;
  githubUsername: string;
  installationId: number | null;
}

const STORAGE_KEY = "sera.session";

// No real login system exists in this research-prototype dashboard --
// identity is bootstrapped from the GitHub App installation redirect
// (see ConnectCallbackPage) and then just kept in localStorage. This is
// fine for a demo/single-browser flow; it is NOT a substitute for real
// session auth (signed cookies, expiry, CSRF protection) in a real
// deployment. Documented, not hidden -- see README "Known limitations".
export function loadSession(): Session | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? (JSON.parse(raw) as Session) : null;
  } catch {
    return null;
  }
}

export function saveSession(session: Session): void {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(session));
}

export function clearSession(): void {
  localStorage.removeItem(STORAGE_KEY);
}

export function useSession() {
  const [session, setSessionState] = useState<Session | null>(() => loadSession());

  useEffect(() => {
    const onStorage = () => setSessionState(loadSession());
    window.addEventListener("storage", onStorage);
    return () => window.removeEventListener("storage", onStorage);
  }, []);

  const setSession = useCallback((s: Session) => {
    saveSession(s);
    setSessionState(s);
  }, []);

  const logOut = useCallback(() => {
    clearSession();
    setSessionState(null);
  }, []);

  return { session, setSession, logOut };
}
