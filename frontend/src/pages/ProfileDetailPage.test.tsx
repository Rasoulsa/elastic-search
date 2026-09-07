import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider } from "react-router-dom";

import { ApiError, apiClient } from "../api/client";
import * as profilesApi from "../api/profiles";
import type { ProfileDetail } from "../api/profiles";
import { tokenStore } from "../auth/tokenStore";
import { appRoutes } from "../routes";
import { deferred, jsonResponse } from "../test-helpers";

vi.mock("../api/profiles", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api/profiles")>();
  return { ...actual, getProfile: vi.fn() };
});

const detailMock = vi.mocked(profilesApi.getProfile);

function profile(overrides: Partial<ProfileDetail> = {}): ProfileDetail {
  return {
    id: 7,
    linkedin_id: "synthetic-id",
    linkedin_username: "example-profile",
    profile_url: "https://www.linkedin.com/in/example-profile",
    full_name: "Example Person",
    job_title: "Principal Engineer",
    company: "Example Company",
    industry: "Software",
    location: "Helsinki",
    country: "Finland",
    summary: "Builds reliable systems.",
    skills: ["Django", "Python"],
    experiences: [{
      title: "Backend Engineer",
      company: "Example Company",
      location: "Helsinki",
      description: "Built APIs.",
      started_at: "2022-01-01",
      ended_at: null,
    }],
    education: [{
      school: "Example University",
      degree: "MSc",
      field_of_study: "Computer Science",
      started_at: "2018-01-01",
      ended_at: "2020-01-01",
    }],
    ...overrides,
  };
}

function renderApp(path = "/profiles/7") {
  const queryClient = new QueryClient();
  const router = createMemoryRouter(appRoutes, { initialEntries: [path] });
  render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
  return { queryClient, router };
}

beforeEach(() => {
  tokenStore.clear();
  sessionStorage.clear();
  tokenStore.replaceTokens("test-access", "test-refresh");
  vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => {
    const url = String(input);
    if (url.includes("/token/refresh/")) return Promise.resolve(jsonResponse({ access: "fresh-access" }));
    if (url.includes("/auth/me/")) {
      return Promise.resolve(jsonResponse({ id: 1, username: "reviewer", email: "" }));
    }
    return Promise.reject(new Error("Unexpected fetch"));
  }));
  detailMock.mockReset();
  detailMock.mockResolvedValue(profile());
});

afterEach(() => {
  vi.unstubAllGlobals();
});

test("renders public profile fields and deterministic nested sections", async () => {
  renderApp();
  expect(await screen.findByRole("heading", { name: "Example Person" })).toBeInTheDocument();
  expect(screen.getByText("Principal Engineer at Example Company")).toBeInTheDocument();
  expect(screen.getByText("Helsinki · Finland · Software")).toBeInTheDocument();
  expect(screen.getByText("Builds reliable systems.")).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "Experience" })).toBeInTheDocument();
  expect(screen.getByText("Built APIs.")).toBeInTheDocument();
  expect(screen.getByText("Helsinki · 2022-01-01 – Present")).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "Education" })).toBeInTheDocument();
  expect(screen.getByText("MSc, Computer Science")).toBeInTheDocument();
  expect(screen.getByText("Django")).toBeInTheDocument();
});

test("shows loading state", async () => {
  const pending = deferred<ProfileDetail>();
  detailMock.mockReturnValue(pending.promise);
  renderApp();
  expect(await screen.findByText("Loading profile…")).toBeInTheDocument();
  pending.resolve(profile());
  expect(await screen.findByRole("heading", { name: "Example Person" })).toBeInTheDocument();
});

test("shows a distinct not-found state", async () => {
  detailMock.mockRejectedValue(new ApiError("raw detail", "unexpected", 404));
  renderApp();
  expect(await screen.findByRole("heading", { name: "Profile not found" })).toBeInTheDocument();
  expect(detailMock).toHaveBeenCalledOnce();
  expect(screen.queryByText("raw detail")).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Retry" })).not.toBeInTheDocument();
});

test.each([
  [new ApiError("private network", "network"), "Connection problem"],
  [new ApiError("private server", "server", 500), "Profile could not be loaded"],
  [new profilesApi.MalformedResponseError(), "Profile response could not be displayed"],
])("renders a recoverable stable error for %p", async (error, heading) => {
  detailMock.mockRejectedValue(error);
  renderApp();
  expect(await screen.findByRole("heading", { name: heading })).toBeInTheDocument();
  expect(screen.queryByText(/private/)).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
});

test("manual retry recovers", async () => {
  detailMock.mockRejectedValue(new ApiError("failure", "server", 500));
  renderApp();
  await screen.findByRole("heading", { name: "Profile could not be loaded" });
  detailMock.mockResolvedValue(profile());
  await userEvent.setup().click(screen.getByRole("button", { name: "Retry" }));
  expect(await screen.findByRole("heading", { name: "Example Person" })).toBeInTheDocument();
  expect(detailMock).toHaveBeenCalledTimes(2);
});

test("detail network failures retry once, while server failures do not retry automatically", async () => {
  detailMock.mockRejectedValue(new ApiError("private network", "network"));
  renderApp();
  await screen.findByRole("heading", { name: "Connection problem" });
  expect(detailMock).toHaveBeenCalledTimes(2);

  detailMock.mockReset();
  detailMock.mockRejectedValue(new ApiError("private server", "server", 503));
  renderApp();
  await screen.findAllByRole("heading", { name: "Profile could not be loaded" });
  expect(detailMock).toHaveBeenCalledOnce();
});

test("detail 401 uses the existing session-expiry flow without a query retry", async () => {
  vi.mocked(fetch).mockImplementation((input: RequestInfo | URL) => {
    const url = String(input);
    if (url.includes("/token/refresh/")) {
      return Promise.resolve(jsonResponse({ access: "fresh-access" }));
    }
    if (url.includes("/auth/me/")) {
      return Promise.resolve(jsonResponse({ id: 1, username: "reviewer", email: "" }));
    }
    if (url.includes("/profiles/7/")) {
      return Promise.resolve(jsonResponse({ detail: "expired" }, 401));
    }
    return Promise.reject(new Error("Unexpected fetch"));
  });
  detailMock.mockImplementation((_profileId, signal) =>
    apiClient.protectedRequest<ProfileDetail>("/api/v1/profiles/7/", { signal }),
  );

  const { router } = renderApp();
  expect(await screen.findByRole("heading", { name: "Sign in" })).toBeInTheDocument();
  expect(router.state.location.pathname).toBe("/login");
  expect(detailMock).toHaveBeenCalledOnce();
  expect(vi.mocked(fetch).mock.calls.filter(([url]) => String(url).includes("/profiles/7/"))).toHaveLength(2);
});

test.each([
  [new ApiError("expired", "unauthorized", 401), "Profile could not be loaded"],
  [new profilesApi.MalformedResponseError(), "Profile response could not be displayed"],
  [new DOMException("aborted", "AbortError"), "Profile could not be loaded"],
])("detail %p is not automatically retried", async (error, heading) => {
  detailMock.mockRejectedValue(error);
  renderApp();
  expect(await screen.findAllByRole("heading", { name: heading })).not.toHaveLength(0);
  expect(detailMock).toHaveBeenCalledOnce();
});

test("renders safe external profile URLs with protective attributes", async () => {
  renderApp();
  const link = await screen.findByRole("link", { name: /View LinkedIn profile/ });
  expect(link).toHaveAttribute("href", "https://www.linkedin.com/in/example-profile");
  expect(link).toHaveAttribute("target", "_blank");
  expect(link).toHaveAttribute("rel", "noreferrer noopener");
});

test("renders an unsafe external URL as text instead of a link", async () => {
  detailMock.mockResolvedValue(profile({ profile_url: "javascript:alert(1)" }));
  renderApp();
  expect(await screen.findByText("Profile URL: javascript:alert(1)")).toBeInTheDocument();
  expect(screen.queryByRole("link", { name: /LinkedIn profile/ })).not.toBeInTheDocument();
});

test("preserves a safe search return destination", async () => {
  renderApp("/profiles/7?return_to=%2Fsearch%3Fq%3Dengineer%26skill%3DPython%26page%3D2");
  const back = await screen.findByRole("link", { name: /Back to results/ });
  expect(back).toHaveAttribute("href", "/search?q=engineer&skill=Python&page=2");
});

test.each([
  "/profiles/7?return_to=https%3A%2F%2Fevil.example",
  "/profiles/7?return_to=%2Flogin",
  "/profiles/7?return_to=%2Fprofiles%2F8",
])("falls back to search for an unsafe or non-search return destination", async (path) => {
  renderApp(path);
  const back = await screen.findByRole("link", { name: /Back to results/ });
  expect(back).toHaveAttribute("href", "/search");
});

test.each(["abc", "0", "-1", "1.5", "999999999999999999999999"])(
  "malformed profile id %s fails safely without a request",
  async (id) => {
    renderApp(`/profiles/${id}`);
    expect(await screen.findByRole("heading", { name: "Invalid profile" })).toBeInTheDocument();
    expect(detailMock).not.toHaveBeenCalled();
  },
);

test("does not render raw or internal fields", async () => {
  detailMock.mockResolvedValue({
    ...profile(),
    raw_payload: "private",
    source_order: "internal",
  } as ProfileDetail);
  renderApp();
  await screen.findByRole("heading", { name: "Example Person" });
  expect(screen.queryByText("private")).not.toBeInTheDocument();
  expect(screen.queryByText("internal")).not.toBeInTheDocument();
});
