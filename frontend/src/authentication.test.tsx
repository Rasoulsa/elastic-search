import { StrictMode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider } from "react-router-dom";

import { CURRENT_USER_QUERY_KEY, useAuth } from "./auth/authContext";
import { AuthProvider } from "./auth/AuthProvider";
import { createTokenStore, tokenStore } from "./auth/tokenStore";
import { appRoutes } from "./routes";
import { deferred, jsonResponse } from "./test-helpers";

function renderRoute(path: string, queryClient = new QueryClient()) {
  const router = createMemoryRouter(appRoutes, { initialEntries: [path] });
  const result = render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
  return { ...result, queryClient, router };
}

function LogoutHarness() {
  const { logout, status, user } = useAuth();
  return (
    <div>
      <span data-testid="auth-status">{status}</span>
      <span>{user?.username}</span>
      <button type="button" onClick={() => void logout()}>
        Force logout
      </button>
    </div>
  );
}

function renderLogoutHarness() {
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <AuthProvider>
        <LogoutHarness />
      </AuthProvider>
    </QueryClientProvider>,
  );
}

function AuthActionsHarness() {
  const { login, logout, status, user } = useAuth();
  const startLogin = (username: string) => {
    void login({ username, password: "password" }).catch(() => undefined);
  };
  return (
    <div>
      <span data-testid="auth-status">{status}</span>
      <span>{user?.username}</span>
      <button type="button" onClick={() => startLogin("first")}>Start first login</button>
      <button type="button" onClick={() => startLogin("second")}>Start second login</button>
      <button type="button" onClick={() => void logout()}>Force logout</button>
    </div>
  );
}

function renderAuthActions() {
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <AuthProvider>
        <AuthActionsHarness />
      </AuthProvider>
    </QueryClientProvider>,
  );
}

async function completeLogin(fetchMock: ReturnType<typeof vi.fn>) {
  fetchMock
    .mockResolvedValueOnce(jsonResponse({ access: "access-value", refresh: "refresh-value" }))
    .mockResolvedValueOnce(
      jsonResponse({ id: 7, username: "reviewer", email: "reviewer@example.com" }),
    );
  const user = userEvent.setup();
  await user.type(screen.getByLabelText("Username"), "reviewer");
  await user.type(screen.getByLabelText("Password"), "correct-password");
  await user.click(screen.getByRole("button", { name: "Sign in" }));
}

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  tokenStore.clear();
  sessionStorage.clear();
  fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

test("unauthenticated search redirects to login and preserves the destination", async () => {
  const { router } = renderRoute("/search");

  expect(await screen.findByRole("heading", { name: "Sign in" })).toBeInTheDocument();
  expect(router.state.location.pathname).toBe("/login");
  expect(router.state.location.state).toEqual({ from: "/search" });
});

test("startup without a refresh token makes no authentication request", async () => {
  const { router } = renderRoute("/search");

  expect(await screen.findByRole("heading", { name: "Sign in" })).toBeInTheDocument();
  expect(fetchMock).not.toHaveBeenCalled();
  expect(router.state.location.pathname).toBe("/login");
});

test("authentication loading does not render protected content", async () => {
  tokenStore.replaceTokens("old-access", "refresh-value");
  const refresh = deferred<Response>();
  fetchMock.mockReturnValue(refresh.promise);

  renderRoute("/search");

  expect(screen.getByRole("status")).toHaveTextContent("Checking your session");
  expect(screen.queryByRole("heading", { name: "Profile search" })).not.toBeInTheDocument();
  refresh.resolve(jsonResponse({ detail: "invalid" }, 401));
  expect(await screen.findByRole("heading", { name: "Sign in" })).toBeInTheDocument();
});

test("successful login stores tokens, establishes the user, and redirects to search", async () => {
  renderRoute("/search");
  await screen.findByRole("heading", { name: "Sign in" });

  await completeLogin(fetchMock);

  expect(await screen.findByRole("heading", { name: "Profile search" })).toBeInTheDocument();
  expect(screen.getByText("Signed in as reviewer")).toBeInTheDocument();
  expect(tokenStore.getAccessToken()).toBe("access-value");
  expect(tokenStore.getRefreshToken()).toBe("refresh-value");
  expect(createTokenStore(sessionStorage).getAccessToken()).toBeNull();
  expect(createTokenStore(sessionStorage).getRefreshToken()).toBe("refresh-value");
});

test("invalid credentials show a stable message and clear the password", async () => {
  fetchMock.mockResolvedValue(jsonResponse({ detail: "No active account" }, 401));
  renderRoute("/login");
  await screen.findByRole("heading", { name: "Sign in" });
  const user = userEvent.setup();
  await user.type(screen.getByLabelText("Username"), "reviewer");
  await user.type(screen.getByLabelText("Password"), "wrong-password");
  await user.click(screen.getByRole("button", { name: "Sign in" }));

  expect(await screen.findByRole("alert")).toHaveTextContent("Incorrect username or password.");
  expect(screen.getByLabelText("Password")).toHaveValue("");
});

test("login validates required fields without making a request", async () => {
  renderRoute("/login");
  await screen.findByRole("heading", { name: "Sign in" });

  fireEvent.submit(screen.getByRole("button", { name: "Sign in" }).closest("form")!);

  expect(await screen.findByRole("alert")).toHaveTextContent("Enter your username and password.");
  expect(fetchMock).not.toHaveBeenCalled();
});

test("a network failure is distinct from a server response", async () => {
  fetchMock.mockRejectedValue(new TypeError("connection failed"));
  renderRoute("/login");
  await screen.findByRole("heading", { name: "Sign in" });
  const user = userEvent.setup();
  await user.type(screen.getByLabelText("Username"), "reviewer");
  await user.type(screen.getByLabelText("Password"), "password");
  await user.click(screen.getByRole("button", { name: "Sign in" }));

  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Unable to reach the service. Check your connection and try again.",
  );
  expect(screen.queryByText("connection failed")).not.toBeInTheDocument();
});

test("a malformed server error is handled safely", async () => {
  fetchMock.mockResolvedValue(new Response("upstream failure", { status: 503 }));
  renderRoute("/login");
  await screen.findByRole("heading", { name: "Sign in" });
  const user = userEvent.setup();
  await user.type(screen.getByLabelText("Username"), "reviewer");
  await user.type(screen.getByLabelText("Password"), "password");
  await user.click(screen.getByRole("button", { name: "Sign in" }));

  expect(await screen.findByRole("alert")).toHaveTextContent(
    "The service is temporarily unavailable. Please try again.",
  );
  expect(screen.queryByText("upstream failure")).not.toBeInTheDocument();
});

test("login prevents duplicate submissions", async () => {
  const response = deferred<Response>();
  fetchMock.mockReturnValue(response.promise);
  renderRoute("/login");
  await screen.findByRole("heading", { name: "Sign in" });
  const user = userEvent.setup();
  await user.type(screen.getByLabelText("Username"), "reviewer");
  await user.type(screen.getByLabelText("Password"), "password");
  const form = screen.getByRole("button", { name: "Sign in" }).closest("form")!;

  fireEvent.submit(form);
  fireEvent.submit(form);

  expect(fetchMock).toHaveBeenCalledOnce();
  expect(screen.getByRole("button", { name: "Signing in…" })).toBeDisabled();
  response.resolve(jsonResponse({ detail: "invalid" }, 401));
  await screen.findByRole("alert");
});

test("successful registration redirects to login with feedback", async () => {
  fetchMock.mockResolvedValue(
    jsonResponse({ id: 7, username: "reviewer", email: "reviewer@example.com" }, 201),
  );
  const { router } = renderRoute("/register");
  await screen.findByRole("heading", { name: "Register" });
  const user = userEvent.setup();
  await user.type(screen.getByLabelText("Username"), "reviewer");
  await user.type(screen.getByLabelText(/Email/), "reviewer@example.com");
  await user.type(screen.getByLabelText("Password"), "strong-password");
  await user.click(screen.getByRole("button", { name: "Create account" }));

  expect(await screen.findByRole("heading", { name: "Sign in" })).toBeInTheDocument();
  expect(screen.getByRole("status")).toHaveTextContent("Registration complete");
  expect(router.state.location.pathname).toBe("/login");
  expect(tokenStore.getRefreshToken()).toBeNull();
  expect(JSON.parse(String(fetchMock.mock.calls[0][1]?.body))).toEqual({
    username: "reviewer",
    email: "reviewer@example.com",
    password: "strong-password",
  });
});

test("a malformed registration success is reported without creating auth state", async () => {
  fetchMock.mockResolvedValue(jsonResponse({ id: 7, username: "reviewer" }, 201));
  renderRoute("/register");
  await screen.findByRole("heading", { name: "Register" });
  const user = userEvent.setup();
  await user.type(screen.getByLabelText("Username"), "reviewer");
  await user.type(screen.getByLabelText("Password"), "strong-password");
  await user.click(screen.getByRole("button", { name: "Create account" }));

  expect(await screen.findByRole("alert")).toHaveTextContent(
    "The server returned an unexpected response.",
  );
  expect(tokenStore.getAccessToken()).toBeNull();
  expect(tokenStore.getRefreshToken()).toBeNull();
});

test("registration validates required fields without making a request", async () => {
  renderRoute("/register");
  await screen.findByRole("heading", { name: "Register" });

  fireEvent.submit(screen.getByRole("button", { name: "Create account" }).closest("form")!);

  expect(await screen.findByRole("alert")).toHaveTextContent("Enter a username and password.");
  expect(fetchMock).not.toHaveBeenCalled();
});

test("registration displays backend field errors", async () => {
  fetchMock.mockResolvedValue(
    jsonResponse(
      {
        username: ["A user with that username already exists."],
        password: ["This password is too common."],
      },
      400,
    ),
  );
  renderRoute("/register");
  await screen.findByRole("heading", { name: "Register" });
  const user = userEvent.setup();
  await user.type(screen.getByLabelText("Username"), "reviewer");
  await user.type(screen.getByLabelText("Password"), "password");
  await user.click(screen.getByRole("button", { name: "Create account" }));

  expect(await screen.findByText("A user with that username already exists.")).toBeInTheDocument();
  expect(screen.getByText("This password is too common.")).toBeInTheDocument();
  expect(screen.getByLabelText("Username")).toHaveAttribute("aria-invalid", "true");
});

test.each(["/login", "/register"])(
  "authenticated users are redirected away from %s",
  async (path) => {
    tokenStore.replaceTokens("old-access", "refresh-value");
    fetchMock
      .mockResolvedValueOnce(jsonResponse({ access: "new-access" }))
      .mockResolvedValueOnce(
        jsonResponse({ id: 7, username: "reviewer", email: "reviewer@example.com" }),
      );
    const { router } = renderRoute(path);

    expect(await screen.findByRole("heading", { name: "Profile search" })).toBeInTheDocument();
    expect(router.state.location.pathname).toBe("/search");
  },
);

test("startup refreshes once and then loads the current user", async () => {
  tokenStore.replaceTokens("stale-access", "refresh-value");
  fetchMock
    .mockResolvedValueOnce(jsonResponse({ access: "fresh-access" }))
    .mockResolvedValueOnce(
      jsonResponse({ id: 7, username: "reviewer", email: "reviewer@example.com" }),
    );
  renderRoute("/search");

  expect(await screen.findByText("Signed in as reviewer")).toBeInTheDocument();
  expect(fetchMock).toHaveBeenCalledTimes(2);
  expect(String(fetchMock.mock.calls[0][0])).toContain("/api/v1/auth/token/refresh/");
  expect(String(fetchMock.mock.calls[1][0])).toContain("/api/v1/auth/me/");
  const meHeaders = fetchMock.mock.calls[1][1]?.headers as Headers;
  expect(meHeaders.get("Authorization")).toBe("Bearer fresh-access");
});

test("a successful refresh followed by a failed current-user request stays unauthenticated", async () => {
  tokenStore.replaceTokens("stale-access", "refresh-value");
  fetchMock
    .mockResolvedValueOnce(jsonResponse({ access: "fresh-access" }))
    .mockResolvedValueOnce(jsonResponse({ detail: "unavailable" }, 503));
  renderRoute("/search");

  expect(await screen.findByRole("heading", { name: "Sign in" })).toBeInTheDocument();
  expect(screen.queryByText("Signed in as reviewer")).not.toBeInTheDocument();
  expect(tokenStore.getAccessToken()).toBeNull();
  expect(tokenStore.getRefreshToken()).toBeNull();
});

test("a malformed current-user response cannot establish authentication", async () => {
  tokenStore.replaceTokens("stale-access", "refresh-value");
  fetchMock
    .mockResolvedValueOnce(jsonResponse({ access: "fresh-access" }))
    .mockResolvedValueOnce(jsonResponse({ id: "7", username: "reviewer" }));
  renderRoute("/search");

  expect(await screen.findByRole("heading", { name: "Sign in" })).toBeInTheDocument();
  expect(tokenStore.getAccessToken()).toBeNull();
  expect(tokenStore.getRefreshToken()).toBeNull();
});

test("StrictMode startup keeps refresh and current-user loading single-flight", async () => {
  tokenStore.replaceTokens("stale-access", "refresh-value");
  fetchMock
    .mockResolvedValueOnce(jsonResponse({ access: "fresh-access" }))
    .mockResolvedValueOnce(
      jsonResponse({ id: 7, username: "reviewer", email: "reviewer@example.com" }),
    );
  const router = createMemoryRouter(appRoutes, { initialEntries: ["/search"] });
  render(
    <StrictMode>
      <QueryClientProvider client={new QueryClient()}>
        <RouterProvider router={router} />
      </QueryClientProvider>
    </StrictMode>,
  );

  expect(await screen.findByText("Signed in as reviewer")).toBeInTheDocument();
  expect(fetchMock).toHaveBeenCalledTimes(2);
});

test("a late login response after logout cannot restore authentication", async () => {
  const loginResponse = deferred<Response>();
  fetchMock.mockReturnValue(loginResponse.promise);
  renderAuthActions();
  const user = userEvent.setup();

  await user.click(screen.getByRole("button", { name: "Start first login" }));
  await waitFor(() => expect(fetchMock).toHaveBeenCalledOnce());
  await user.click(screen.getByRole("button", { name: "Force logout" }));
  loginResponse.resolve(jsonResponse({ access: "late-access", refresh: "late-refresh" }));

  await waitFor(() => expect(screen.getByTestId("auth-status")).toHaveTextContent("unauthenticated"));
  expect(fetchMock).toHaveBeenCalledOnce();
  expect(tokenStore.getAccessToken()).toBeNull();
  expect(tokenStore.getRefreshToken()).toBeNull();
});

test("a late login response after a newer authentication attempt is ignored", async () => {
  const firstLogin = deferred<Response>();
  const secondLogin = deferred<Response>();
  fetchMock
    .mockReturnValueOnce(firstLogin.promise)
    .mockReturnValueOnce(secondLogin.promise)
    .mockResolvedValueOnce(
      jsonResponse({ id: 8, username: "second", email: "second@example.com" }),
    );
  renderAuthActions();
  const user = userEvent.setup();

  await user.click(screen.getByRole("button", { name: "Start first login" }));
  await user.click(screen.getByRole("button", { name: "Start second login" }));
  firstLogin.resolve(jsonResponse({ access: "first-access", refresh: "first-refresh" }));
  await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
  secondLogin.resolve(jsonResponse({ access: "second-access", refresh: "second-refresh" }));

  expect(await screen.findByText("second")).toBeInTheDocument();
  expect(tokenStore.getAccessToken()).toBe("second-access");
  expect(tokenStore.getRefreshToken()).toBe("second-refresh");
  expect(fetchMock).toHaveBeenCalledTimes(3);
});

test("logout clears tokens, current user, and query state", async () => {
  tokenStore.replaceTokens("stale-access", "refresh-value");
  fetchMock
    .mockResolvedValueOnce(jsonResponse({ access: "fresh-access" }))
    .mockResolvedValueOnce(
      jsonResponse({ id: 7, username: "reviewer", email: "reviewer@example.com" }),
    );
  const queryClient = new QueryClient();
  queryClient.setQueryData(["protected-profiles"], [{ id: 1 }]);
  const { router } = renderRoute("/search", queryClient);
  const user = userEvent.setup();
  await screen.findByText("Signed in as reviewer");

  await user.click(screen.getByRole("button", { name: "Sign out" }));

  expect(await screen.findByRole("heading", { name: "Sign in" })).toBeInTheDocument();
  expect(router.state.location.pathname).toBe("/login");
  expect(tokenStore.getAccessToken()).toBeNull();
  expect(tokenStore.getRefreshToken()).toBeNull();
  expect(queryClient.getQueryData(["protected-profiles"])).toBeUndefined();
  expect(queryClient.getQueryData(CURRENT_USER_QUERY_KEY)).toBeUndefined();
});

test("logout during an in-flight refresh cannot restore the session", async () => {
  tokenStore.replaceTokens("stale-access", "refresh-value");
  const refresh = deferred<Response>();
  fetchMock.mockReturnValue(refresh.promise);
  renderLogoutHarness();
  const user = userEvent.setup();
  await waitFor(() => expect(fetchMock).toHaveBeenCalledOnce());

  await user.click(screen.getByRole("button", { name: "Force logout" }));
  refresh.resolve(jsonResponse({ access: "late-access" }));

  await waitFor(() => expect(screen.getByTestId("auth-status")).toHaveTextContent("unauthenticated"));
  expect(tokenStore.getAccessToken()).toBeNull();
  expect(fetchMock).toHaveBeenCalledOnce();
});

test("logout during an in-flight current-user request cannot restore the session", async () => {
  tokenStore.replaceTokens("stale-access", "refresh-value");
  const currentUser = deferred<Response>();
  fetchMock
    .mockResolvedValueOnce(jsonResponse({ access: "fresh-access" }))
    .mockReturnValueOnce(currentUser.promise);
  renderLogoutHarness();
  const user = userEvent.setup();
  await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));

  await user.click(screen.getByRole("button", { name: "Force logout" }));
  currentUser.resolve(
    jsonResponse({ id: 7, username: "reviewer", email: "reviewer@example.com" }),
  );

  await waitFor(() => expect(screen.getByTestId("auth-status")).toHaveTextContent("unauthenticated"));
  expect(screen.queryByText("reviewer")).not.toBeInTheDocument();
  expect(tokenStore.getAccessToken()).toBeNull();
});
