import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { api, clearTokens, getAccessToken, setTokens, type TokenResponse, type User } from "../api/client";

type AuthState = {
  user: User | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  register: (fullName: string, email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  refreshUser: () => Promise<void>;
};

const AuthContext = createContext<AuthState | null>(null);

function storeSession(payload: TokenResponse): User {
  setTokens(payload.access_token, payload.refresh_token);
  return payload.user;
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  async function refreshUser() {
    const me = await api<User>("/api/v1/auth/me");
    setUser(me);
  }

  useEffect(() => {
    if (!getAccessToken()) {
      setLoading(false);
      return;
    }
    refreshUser()
      .catch(() => clearTokens())
      .finally(() => setLoading(false));
  }, []);

  const value = useMemo<AuthState>(
    () => ({
      user,
      loading,
      refreshUser,
      async login(email, password) {
        const payload = await api<TokenResponse>("/api/v1/auth/login", {
          method: "POST",
          body: { email, password },
        });
        setUser(storeSession(payload));
      },
      async register(fullName, email, password) {
        const payload = await api<TokenResponse>("/api/v1/auth/register", {
          method: "POST",
          body: { full_name: fullName, email, password },
        });
        setUser(storeSession(payload));
      },
      async logout() {
        const refresh = localStorage.getItem("agentforge_refresh_token");
        try {
          if (refresh) {
            await api("/api/v1/auth/logout", { method: "POST", body: { refresh_token: refresh } });
          }
        } finally {
          clearTokens();
          setUser(null);
        }
      },
    }),
    [user, loading],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const value = useContext(AuthContext);
  if (!value) throw new Error("AuthProvider is missing");
  return value;
}
