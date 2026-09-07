import { createContext, useContext } from "react";

import type { LoginInput, RegistrationInput, User } from "../api/client";

export type AuthenticationStatus = "loading" | "authenticated" | "unauthenticated";

export interface AuthContextValue {
  user: User | null;
  status: AuthenticationStatus;
  login(input: LoginInput): Promise<void>;
  register(input: RegistrationInput): Promise<void>;
  logout(): Promise<void>;
}

export const CURRENT_USER_QUERY_KEY = ["current-user"] as const;

export const AuthContext = createContext<AuthContextValue | null>(null);

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth must be used within AuthProvider.");
  return context;
}
