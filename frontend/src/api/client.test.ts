import { ApiClient, ApiError } from "./client";
import { createTokenStore } from "../auth/tokenStore";
import { deferred, jsonResponse } from "../test-helpers";

function setup() {
  sessionStorage.clear();
  const tokens = createTokenStore(sessionStorage);
  tokens.replaceTokens("access-one", "refresh-one");
  const fetchFn = vi.fn<typeof fetch>();
  const client = new ApiClient({ baseUrl: "https://api.example", fetchFn, tokens });
  return { client, fetchFn, tokens };
}

describe("ApiClient authentication", () => {
  test("does not attach bearer tokens to login", async () => {
    const { client, fetchFn } = setup();
    fetchFn.mockResolvedValue(jsonResponse({ access: "access-two", refresh: "refresh-two" }));

    await client.login({ username: "reviewer", password: "password" });

    const headers = fetchFn.mock.calls[0][1]?.headers as Headers;
    expect(headers.get("Authorization")).toBeNull();
  });

  test("attaches the access token to protected requests", async () => {
    const { client, fetchFn } = setup();
    fetchFn.mockResolvedValue(jsonResponse({ ok: true }));

    await client.protectedRequest("/protected/");

    const headers = fetchFn.mock.calls[0][1]?.headers as Headers;
    expect(headers.get("Authorization")).toBe("Bearer access-one");
  });

  test("joins a configured base URL without adding a double slash", async () => {
    const { fetchFn, tokens } = setup();
    const client = new ApiClient({
      baseUrl: "https://api.example/",
      fetchFn,
      tokens,
    });
    fetchFn.mockResolvedValue(jsonResponse({ ok: true }));

    await client.protectedRequest("/api/v1/profiles/7/");

    expect(fetchFn.mock.calls[0][0]).toBe("https://api.example/api/v1/profiles/7/");
  });

  test("one 401 performs one refresh and retries once", async () => {
    const { client, fetchFn, tokens } = setup();
    fetchFn
      .mockResolvedValueOnce(jsonResponse({ detail: "expired" }, 401))
      .mockResolvedValueOnce(jsonResponse({ access: "access-two" }))
      .mockResolvedValueOnce(jsonResponse({ ok: true }));

    await expect(client.protectedRequest("/protected/")).resolves.toEqual({ ok: true });

    expect(fetchFn).toHaveBeenCalledTimes(3);
    expect(fetchFn.mock.calls[1][0]).toBe("https://api.example/api/v1/auth/token/refresh/");
    expect(tokens.getAccessToken()).toBe("access-two");
    const retryHeaders = fetchFn.mock.calls[2][1]?.headers as Headers;
    expect(retryHeaders.get("Authorization")).toBe("Bearer access-two");
  });

  test("concurrent 401 responses share one in-flight refresh", async () => {
    const { client, fetchFn } = setup();
    const refresh = deferred<Response>();
    let protectedCalls = 0;
    let refreshCalls = 0;
    fetchFn.mockImplementation((input) => {
      if (String(input).endsWith("/token/refresh/")) {
        refreshCalls += 1;
        return refresh.promise;
      }
      protectedCalls += 1;
      return Promise.resolve(
        protectedCalls <= 2
          ? jsonResponse({ detail: "expired" }, 401)
          : jsonResponse({ ok: true }),
      );
    });

    const first = client.protectedRequest("/first/");
    const second = client.protectedRequest("/second/");
    await vi.waitFor(() => expect(refreshCalls).toBe(1));
    refresh.resolve(jsonResponse({ access: "access-two" }));

    await expect(Promise.all([first, second])).resolves.toEqual([{ ok: true }, { ok: true }]);
    expect(refreshCalls).toBe(1);
    expect(protectedCalls).toBe(4);
  });

  test("failed refresh clears the session", async () => {
    const { client, fetchFn, tokens } = setup();
    const expired = vi.fn();
    client.setSessionExpiredHandler(expired);
    fetchFn
      .mockResolvedValueOnce(jsonResponse({ detail: "expired" }, 401))
      .mockResolvedValueOnce(jsonResponse({ detail: "invalid" }, 401));

    await expect(client.protectedRequest("/protected/")).rejects.toBeInstanceOf(ApiError);

    expect(tokens.getAccessToken()).toBeNull();
    expect(tokens.getRefreshToken()).toBeNull();
    expect(expired).toHaveBeenCalledOnce();
  });

  test("a retried 401 does not start another refresh loop", async () => {
    const { client, fetchFn } = setup();
    fetchFn
      .mockResolvedValueOnce(jsonResponse({ detail: "expired" }, 401))
      .mockResolvedValueOnce(jsonResponse({ access: "access-two" }))
      .mockResolvedValueOnce(jsonResponse({ detail: "still unauthorized" }, 401));

    await expect(client.protectedRequest("/protected/")).rejects.toMatchObject({
      kind: "unauthorized",
    });
    expect(fetchFn).toHaveBeenCalledTimes(3);
  });

  test("clearing tokens during refresh prevents the response from restoring access", async () => {
    const { client, fetchFn, tokens } = setup();
    const refresh = deferred<Response>();
    fetchFn.mockReturnValue(refresh.promise);

    const request = client.refreshAccessToken();
    tokens.clear();
    refresh.resolve(jsonResponse({ access: "late-access" }));

    await expect(request).rejects.toThrow();
    expect(tokens.getAccessToken()).toBeNull();
    expect(tokens.getRefreshToken()).toBeNull();
  });

  test("does not refresh when the original request is already aborted", async () => {
    const { client, fetchFn } = setup();
    const controller = new AbortController();
    controller.abort();
    fetchFn.mockResolvedValue(jsonResponse({ detail: "expired" }, 401));

    await expect(
      client.protectedRequest("/protected/", { signal: controller.signal }),
    ).rejects.toMatchObject({ name: "AbortError" });
    expect(fetchFn).toHaveBeenCalledOnce();
  });

  test("an aborted caller stops waiting without canceling shared refresh", async () => {
    const { client, fetchFn } = setup();
    const refresh = deferred<Response>();
    const controller = new AbortController();
    fetchFn.mockImplementation((input) => {
      if (String(input).endsWith("/token/refresh/")) return refresh.promise;
      return Promise.resolve(jsonResponse({ detail: "expired" }, 401));
    });

    const request = client.protectedRequest("/protected/", { signal: controller.signal });
    await vi.waitFor(() => expect(fetchFn).toHaveBeenCalledTimes(2));
    controller.abort();
    await expect(request).rejects.toMatchObject({ name: "AbortError" });
    refresh.resolve(jsonResponse({ access: "access-two" }));
    await vi.waitFor(() => expect(fetchFn).toHaveBeenCalledTimes(2));
  });

  test("one aborted concurrent caller does not stop another caller", async () => {
    const { client, fetchFn } = setup();
    const refresh = deferred<Response>();
    const firstController = new AbortController();
    let protectedCalls = 0;
    let refreshCalls = 0;
    fetchFn.mockImplementation((input) => {
      if (String(input).endsWith("/token/refresh/")) {
        refreshCalls += 1;
        return refresh.promise;
      }
      protectedCalls += 1;
      return Promise.resolve(
        protectedCalls <= 2
          ? jsonResponse({ detail: "expired" }, 401)
          : jsonResponse({ ok: true }),
      );
    });

    const first = client.protectedRequest("/first/", { signal: firstController.signal });
    const second = client.protectedRequest("/second/");
    await vi.waitFor(() => expect(refreshCalls).toBe(1));
    firstController.abort();
    refresh.resolve(jsonResponse({ access: "access-two" }));

    await expect(first).rejects.toMatchObject({ name: "AbortError" });
    await expect(second).resolves.toEqual({ ok: true });
    expect(refreshCalls).toBe(1);
    expect(protectedCalls).toBe(3);
  });

  test("an abort after refresh resolution prevents the retry", async () => {
    const { client, fetchFn } = setup();
    const controller = new AbortController();
    const refreshResponse = deferred<Response>();
    fetchFn.mockImplementation((input) => {
      if (String(input).endsWith("/token/refresh/")) {
        refreshResponse.promise.then(() => controller.abort());
        return refreshResponse.promise;
      }
      return Promise.resolve(jsonResponse({ detail: "expired" }, 401));
    });

    const request = client.protectedRequest("/protected/", { signal: controller.signal });
    await vi.waitFor(() => expect(fetchFn).toHaveBeenCalledTimes(2));
    refreshResponse.resolve(jsonResponse({ access: "access-two" }));

    await expect(request).rejects.toMatchObject({ name: "AbortError" });
    expect(fetchFn).toHaveBeenCalledTimes(2);
  });

  test("retries with the original AbortSignal", async () => {
    const { client, fetchFn } = setup();
    const controller = new AbortController();
    fetchFn
      .mockResolvedValueOnce(jsonResponse({ detail: "expired" }, 401))
      .mockResolvedValueOnce(jsonResponse({ access: "access-two" }))
      .mockResolvedValueOnce(jsonResponse({ ok: true }));

    await expect(
      client.protectedRequest("/protected/", { signal: controller.signal }),
    ).resolves.toEqual({ ok: true });
    expect(fetchFn.mock.calls[0][1]?.signal).toBe(controller.signal);
    expect(fetchFn.mock.calls[2][1]?.signal).toBe(controller.signal);
  });

  test("preserves AbortError instead of converting it to a network error", async () => {
    const { client, fetchFn } = setup();
    fetchFn.mockRejectedValue(new DOMException("aborted", "AbortError"));

    await expect(client.protectedRequest("/protected/")).rejects.toMatchObject({
      name: "AbortError",
    });
  });

  test.each([
    [{ access: "", refresh: "refresh" }],
    [{ access: "access", refresh: "" }],
    [{ access: 12, refresh: "refresh" }],
  ])("rejects malformed login token response %j", async (body) => {
    const { client, fetchFn, tokens } = setup();
    fetchFn.mockResolvedValue(jsonResponse(body));

    await expect(client.login({ username: "reviewer", password: "password" })).rejects.toMatchObject({
      kind: "unexpected",
    });
    expect(tokens.getAccessToken()).toBe("access-one");
  });

  test("rejects a malformed refresh response and clears the session", async () => {
    const { client, fetchFn, tokens } = setup();
    fetchFn.mockResolvedValue(jsonResponse({ access: "" }));

    await expect(client.refreshAccessToken()).rejects.toMatchObject({ kind: "unexpected" });
    expect(tokens.getAccessToken()).toBeNull();
    expect(tokens.getRefreshToken()).toBeNull();
  });

  test.each([
    [{ id: 7, username: "reviewer" }],
    [{ id: "7", username: "reviewer", email: "reviewer@example.com" }],
  ])("rejects malformed current-user response %j", async (body) => {
    const { client, fetchFn } = setup();
    fetchFn.mockResolvedValue(jsonResponse(body));

    await expect(client.getCurrentUser(false)).rejects.toMatchObject({ kind: "unexpected" });
  });

  test.each([
    [{ id: 7, username: "reviewer" }],
    [{ id: 7, username: 12, email: "reviewer@example.com" }],
  ])("rejects malformed registration response %j", async (body) => {
    const { client, fetchFn, tokens } = setup();
    fetchFn.mockResolvedValue(jsonResponse(body, 201));

    await expect(
      client.register({ username: "reviewer", password: "password" }),
    ).rejects.toMatchObject({ kind: "unexpected" });
    expect(tokens.getAccessToken()).toBe("access-one");
  });

  test("concurrent retried 401 responses expire one generation once", async () => {
    const { client, fetchFn, tokens } = setup();
    const expired = vi.fn();
    client.setSessionExpiredHandler(expired);
    let protectedCalls = 0;
    fetchFn.mockImplementation((input) => {
      if (String(input).endsWith("/token/refresh/")) {
        return Promise.resolve(jsonResponse({ access: "access-two" }));
      }
      protectedCalls += 1;
      return Promise.resolve(
        protectedCalls <= 2
          ? jsonResponse({ detail: "expired" }, 401)
          : jsonResponse({ detail: "still expired" }, 401),
      );
    });

    const results = await Promise.allSettled([
      client.protectedRequest("/first/"),
      client.protectedRequest("/second/"),
    ]);

    expect(results.every((result) => result.status === "rejected")).toBe(true);
    expect(expired).toHaveBeenCalledOnce();
    expect(tokens.getAccessToken()).toBeNull();
  });
});
