import { tokenStore, type TokenStore } from "../auth/tokenStore";

export interface User {
  id: number;
  username: string;
  email: string;
}

export interface LoginInput {
  username: string;
  password: string;
}

export interface RegistrationInput extends LoginInput {
  email?: string;
}

export type ApiErrorKind =
  | "credentials"
  | "network"
  | "server"
  | "unauthorized"
  | "validation"
  | "unexpected";

export type FieldErrors = Record<string, string[]>;

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly kind: ApiErrorKind,
    public readonly status?: number,
    public readonly fields: FieldErrors = {},
  ) {
    super(message);
    this.name = "ApiError";
  }
}

class AuthSessionChangedError extends Error {}

interface ApiClientOptions {
  baseUrl: string;
  fetchFn?: typeof fetch;
  tokens?: TokenStore;
}

interface RequestOptions extends RequestInit {
  protected?: boolean;
  retryUnauthorized?: boolean;
}

export interface TokenPair {
  access: string;
  refresh: string;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function fieldErrorsFrom(value: unknown): FieldErrors {
  if (!isRecord(value)) return {};

  return Object.fromEntries(
    Object.entries(value).flatMap(([field, messages]) => {
      if (typeof messages === "string") return [[field, [messages]]];
      if (Array.isArray(messages)) {
        const safeMessages = messages.filter(
          (message): message is string => typeof message === "string",
        );
        return safeMessages.length > 0 ? [[field, safeMessages]] : [];
      }
      return [];
    }),
  );
}

async function parseResponseBody(response: Response): Promise<unknown> {
  let text: string;
  try {
    text = await response.text();
  } catch (error: unknown) {
    if (isAbortError(error)) throw error;
    return null;
  }
  if (!text) return null;

  try {
    return JSON.parse(text) as unknown;
  } catch {
    return null;
  }
}

function errorFromResponse(response: Response, body: unknown, credentialsRequest = false): ApiError {
  const fields = fieldErrorsFrom(body);
  if (credentialsRequest && response.status === 401) {
    return new ApiError("Incorrect username or password.", "credentials", response.status);
  }
  if (response.status === 400 && Object.keys(fields).length > 0) {
    return new ApiError("Please correct the highlighted fields.", "validation", response.status, fields);
  }
  if (response.status === 401) {
    return new ApiError("Your session has expired. Please sign in again.", "unauthorized", 401);
  }
  if (response.status >= 500) {
    return new ApiError("The service is temporarily unavailable. Please try again.", "server", response.status);
  }

  const detail = isRecord(body) && typeof body.detail === "string" ? body.detail : null;
  return new ApiError(detail ?? "The request could not be completed.", "unexpected", response.status, fields);
}

function isNonEmptyString(value: unknown): value is string {
  return typeof value === "string" && value.trim().length > 0;
}

function isUser(value: unknown): value is User {
  return (
    isRecord(value) &&
    typeof value.id === "number" &&
    Number.isInteger(value.id) &&
    typeof value.username === "string" &&
    typeof value.email === "string"
  );
}

function parseUser(body: unknown): User {
  if (!isUser(body)) {
    throw new ApiError("The server returned an unexpected response.", "unexpected");
  }
  return body;
}

function parseTokenPair(body: unknown): TokenPair {
  if (!isRecord(body) || !isNonEmptyString(body.access) || !isNonEmptyString(body.refresh)) {
    throw new ApiError("The server returned an unexpected response.", "unexpected");
  }
  return { access: body.access, refresh: body.refresh };
}

function parseRefreshResponse(body: unknown): string {
  if (!isRecord(body) || !isNonEmptyString(body.access)) {
    throw new ApiError("The server returned an unexpected response.", "unexpected");
  }
  return body.access;
}

function isAbortError(error: unknown): boolean {
  return isRecord(error) && error.name === "AbortError";
}

function abortError(signal?: AbortSignal | null): unknown {
  const reason = signal?.reason;
  if (isAbortError(reason)) return reason;
  return new DOMException("The operation was aborted.", "AbortError");
}

function throwIfAborted(signal?: AbortSignal | null): void {
  if (signal?.aborted) throw abortError(signal);
}

function waitForRefresh<T>(promise: Promise<T>, signal?: AbortSignal | null): Promise<T> {
  if (!signal) return promise;
  if (signal.aborted) return Promise.reject(abortError(signal));

  return new Promise<T>((resolve, reject) => {
    const onAbort = () => {
      cleanup();
      reject(abortError(signal));
    };
    const cleanup = () => signal.removeEventListener("abort", onAbort);
    signal.addEventListener("abort", onAbort, { once: true });
    promise.then(
      (value) => {
        cleanup();
        resolve(value);
      },
      (error: unknown) => {
        cleanup();
        reject(error);
      },
    );
  });
}

export class ApiClient {
  private readonly baseUrl: string;
  private readonly fetchFn: typeof fetch;
  private readonly tokens: TokenStore;
  private refreshPromise: { generation: number; promise: Promise<string> } | null = null;
  private sessionExpiredHandler: (() => void) | null = null;
  private expiredGeneration: number | null = null;

  constructor({ baseUrl, fetchFn, tokens = tokenStore }: ApiClientOptions) {
    this.baseUrl = baseUrl.replace(/\/$/, "");
    this.fetchFn = fetchFn ?? ((input, init) => fetch(input, init));
    this.tokens = tokens;
  }

  setSessionExpiredHandler(handler: (() => void) | null) {
    this.sessionExpiredHandler = handler;
  }

  async login(input: LoginInput): Promise<TokenPair> {
    const body = await this.request<unknown>("/api/v1/auth/token/", {
      method: "POST",
      body: JSON.stringify(input),
      credentialsRequest: true,
    });
    return parseTokenPair(body);
  }

  async register(input: RegistrationInput): Promise<User> {
    return parseUser(
      await this.request("/api/v1/auth/register/", {
        method: "POST",
        body: JSON.stringify(input),
      }),
    );
  }

  async getCurrentUser(retryUnauthorized = true): Promise<User> {
    return parseUser(
      await this.request("/api/v1/auth/me/", {
        protected: true,
        retryUnauthorized,
      }),
    );
  }

  protectedRequest<T>(path: string, options: RequestInit = {}): Promise<T> {
    return this.request<T>(path, { ...options, protected: true });
  }

  refreshAccessToken(): Promise<string> {
    const generation = this.tokens.getGeneration();
    if (this.refreshPromise?.generation === generation) return this.refreshPromise.promise;

    const refreshToken = this.tokens.getRefreshToken();
    if (!refreshToken) {
      this.expireSession(generation);
      return Promise.reject(new ApiError("Your session has expired. Please sign in again.", "unauthorized", 401));
    }

    const refreshOperation = this.request<unknown>("/api/v1/auth/token/refresh/", {
      method: "POST",
      body: JSON.stringify({ refresh: refreshToken }),
    })
      .then((body) => {
        const accessToken = parseRefreshResponse(body);
        if (!this.tokens.setAccessToken(accessToken, generation)) {
          throw new AuthSessionChangedError();
        }
        return accessToken;
      })
      .catch((error: unknown) => {
        if (this.tokens.getGeneration() === generation) {
          this.expireSession(generation);
        }
        throw error;
      })
      .finally(() => {
        if (this.refreshPromise?.promise === promise) this.refreshPromise = null;
      });
    const promise = refreshOperation;
    this.refreshPromise = { generation, promise };
    void promise.catch(() => undefined);

    return promise;
  }

  private expireSession(generation: number): void {
    if (this.expiredGeneration === generation || this.tokens.getGeneration() !== generation) return;
    this.expiredGeneration = generation;
    this.tokens.clear();
    if (this.sessionExpiredHandler) {
      this.sessionExpiredHandler();
    }
  }

  private async request<T>(
    path: string,
    options: RequestOptions & { credentialsRequest?: boolean } = {},
  ): Promise<T> {
    const {
      protected: isProtected = false,
      retryUnauthorized = true,
      credentialsRequest = false,
      headers,
      ...requestInit
    } = options;

    const perform = async (): Promise<Response> => {
      const requestHeaders = new Headers(headers);
      requestHeaders.set("Accept", "application/json");
      if (requestInit.body !== undefined) requestHeaders.set("Content-Type", "application/json");
      if (isProtected) {
        const accessToken = this.tokens.getAccessToken();
        if (accessToken) requestHeaders.set("Authorization", `Bearer ${accessToken}`);
      }

      try {
        return await this.fetchFn(`${this.baseUrl}${path}`, { ...requestInit, headers: requestHeaders });
      } catch (error: unknown) {
        if (isAbortError(error)) throw error;
        throw new ApiError("Unable to reach the service. Check your connection and try again.", "network");
      }
    };

    const requestGeneration = this.tokens.getGeneration();
    let response = await perform();
    if (isProtected && retryUnauthorized && response.status === 401) {
      throwIfAborted(requestInit.signal);
      if (this.tokens.getGeneration() !== requestGeneration) {
        throw new AuthSessionChangedError();
      }
      await waitForRefresh(this.refreshAccessToken(), requestInit.signal);
      throwIfAborted(requestInit.signal);
      if (this.tokens.getGeneration() !== requestGeneration) {
        throw new AuthSessionChangedError();
      }
      response = await perform();
      if (response.status === 401) {
        this.expireSession(requestGeneration);
      }
    }

    const body = await parseResponseBody(response);
    if (!response.ok) throw errorFromResponse(response, body, credentialsRequest);
    return body as T;
  }
}

export const apiClient = new ApiClient({
  baseUrl: import.meta.env.VITE_API_BASE_URL ?? "",
});
