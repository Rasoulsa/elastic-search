const REFRESH_TOKEN_KEY = "profile-search.refresh-token";

export interface TokenStore {
  clear(): void;
  getAccessToken(): string | null;
  getGeneration(): number;
  getRefreshToken(): string | null;
  replaceTokens(accessToken: string, refreshToken: string): void;
  setAccessToken(accessToken: string, generation?: number): boolean;
}

function sessionStorageOrNull(): Storage | null {
  try {
    return typeof window === "undefined" ? null : window.sessionStorage;
  } catch {
    return null;
  }
}

export function createTokenStore(storage?: Storage): TokenStore {
  let accessToken: string | null = null;
  let refreshTokenFallback: string | null = null;
  let refreshTokenSuppressed = false;
  let generation = 0;

  const getStorage = () => storage ?? sessionStorageOrNull();

  return {
    clear() {
      generation += 1;
      accessToken = null;
      refreshTokenFallback = null;
      refreshTokenSuppressed = true;
      try {
        getStorage()?.removeItem(REFRESH_TOKEN_KEY);
      } catch {
        // Memory is still cleared if browser storage is unavailable.
      }
    },

    getAccessToken() {
      return accessToken;
    },

    getGeneration() {
      return generation;
    },

    getRefreshToken() {
      if (refreshTokenSuppressed) return null;
      if (refreshTokenFallback !== null) return refreshTokenFallback;
      try {
        return getStorage()?.getItem(REFRESH_TOKEN_KEY) ?? null;
      } catch {
        return null;
      }
    },

    replaceTokens(nextAccessToken, nextRefreshToken) {
      generation += 1;
      accessToken = nextAccessToken;
      refreshTokenSuppressed = false;
      refreshTokenFallback = null;
      try {
        const currentStorage = getStorage();
        if (!currentStorage) throw new Error("sessionStorage unavailable");
        currentStorage.setItem(REFRESH_TOKEN_KEY, nextRefreshToken);
      } catch {
        // The in-memory fallback still supports the current page lifecycle.
        refreshTokenFallback = nextRefreshToken;
      }
    },

    setAccessToken(nextAccessToken, expectedGeneration) {
      if (expectedGeneration !== undefined && expectedGeneration !== generation) {
        return false;
      }
      accessToken = nextAccessToken;
      return true;
    },
  };
}

export const tokenStore = createTokenStore();
