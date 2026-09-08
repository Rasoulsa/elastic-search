import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useRef, useState } from "react";

import {
  apiClient,
  type LoginInput,
  type RegistrationInput,
  type User,
} from "../api/client";
import { AuthContext, CURRENT_USER_QUERY_KEY, type AuthenticationStatus } from "./authContext";
import { tokenStore } from "./tokenStore";

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const queryClient = useQueryClient();
  const [user, setUser] = useState<User | null>(null);
  const [status, setStatus] = useState<AuthenticationStatus>("loading");
  const operation = useRef(0);
  const initializationStarted = useRef(false);

  const expireSession = useCallback(() => {
    operation.current += 1;
    if (tokenStore.getAccessToken() !== null || tokenStore.getRefreshToken() !== null) {
      tokenStore.clear();
    }
    setUser(null);
    setStatus("unauthenticated");
    queryClient.clear();
  }, [queryClient]);

  useEffect(() => {
    apiClient.setSessionExpiredHandler(expireSession);
    return () => apiClient.setSessionExpiredHandler(null);
  }, [expireSession]);

  useEffect(() => {
    if (initializationStarted.current) return;
    initializationStarted.current = true;

    const initialize = async () => {
      const currentOperation = ++operation.current;
      if (!tokenStore.getRefreshToken()) {
        tokenStore.clear();
        setStatus("unauthenticated");
        return;
      }

      try {
        await apiClient.refreshAccessToken();
        const currentUser = await apiClient.getCurrentUser(false);
        if (operation.current !== currentOperation) return;
        queryClient.setQueryData(CURRENT_USER_QUERY_KEY, currentUser);
        setUser(currentUser);
        setStatus("authenticated");
      } catch {
        if (operation.current !== currentOperation) return;
        tokenStore.clear();
        queryClient.clear();
        setUser(null);
        setStatus("unauthenticated");
      }
    };

    void initialize();
  }, [queryClient]);

  const login = useCallback(
    async (input: LoginInput) => {
      const currentOperation = ++operation.current;
      try {
        const tokens = await apiClient.login(input);
        if (operation.current !== currentOperation) return;
        tokenStore.replaceTokens(tokens.access, tokens.refresh);
        const currentUser = await apiClient.getCurrentUser(false);
        if (operation.current !== currentOperation) return;
        queryClient.setQueryData(CURRENT_USER_QUERY_KEY, currentUser);
        setUser(currentUser);
        setStatus("authenticated");
      } catch (error) {
        if (operation.current === currentOperation) {
          tokenStore.clear();
          queryClient.clear();
          setUser(null);
          setStatus("unauthenticated");
        }
        throw error;
      }
    },
    [queryClient],
  );

  const register = useCallback(async (input: RegistrationInput) => {
    await apiClient.register(input);
  }, []);

  const logout = useCallback(async () => {
    operation.current += 1;
    tokenStore.clear();
    setUser(null);
    setStatus("unauthenticated");
    await queryClient.cancelQueries();
    queryClient.clear();
  }, [queryClient]);

  return (
    <AuthContext.Provider value={{ user, status, login, register, logout }}>
      {children}
    </AuthContext.Provider>
  );
}
