import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider } from "react-router-dom";

import { ApiError, apiClient } from "../api/client";
import * as profilesApi from "../api/profiles";
import type { ProfileSearchResponse } from "../api/profiles";
import { tokenStore } from "../auth/tokenStore";
import { appRoutes } from "../routes";
import { deferred, jsonResponse } from "../test-helpers";

vi.mock("../api/profiles", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api/profiles")>();
  return { ...actual, searchProfiles: vi.fn() };
});

const searchMock = vi.mocked(profilesApi.searchProfiles);

function response(overrides: Partial<ProfileSearchResponse> = {}): ProfileSearchResponse {
  return {
    count: 1,
    page: 1,
    page_size: 20,
    total_pages: 1,
    results: [{
      id: 7,
      full_name: "Example Person",
      job_title: "Backend Engineer",
      company: "Example Company",
      industry: "Software",
      country: "Finland",
      skills: ["Python", "Django"],
      summary: "Builds reliable search systems.",
    }],
    facets: {
      skills: [{ value: "Python", count: 42 }, { value: "Django", count: 24 }],
      job_titles: [{ value: "Backend Engineer", count: 12 }],
      industries: [{ value: "Software", count: 18 }],
      countries: [{ value: "Finland", count: 8 }],
      companies: [{ value: "Example Company", count: 6 }],
    },
    ...overrides,
  };
}

function renderApp(path = "/search") {
  const queryClient = new QueryClient({ defaultOptions: { queries: { gcTime: Infinity } } });
  const router = createMemoryRouter(appRoutes, { initialEntries: [path] });
  const result = render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
  return { ...result, queryClient, router };
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
  searchMock.mockReset();
  searchMock.mockResolvedValue(response());
});

afterEach(() => {
  vi.unstubAllGlobals();
});

test("loads the initial match-all page and facets", async () => {
  renderApp();
  expect(await screen.findByRole("heading", { name: "1 profile" })).toBeInTheDocument();
  expect(searchMock).toHaveBeenCalledWith(expect.objectContaining({ q: "", page: 1, page_size: 20 }), expect.any(AbortSignal));
  expect(screen.getByRole("checkbox", { name: /Python.*42/ })).toBeInTheDocument();
});

test("URL values initialize controls and repeated filters", async () => {
  renderApp("/search?q=engineer&skill=Python&skill=Django&job_title=Backend+Engineer");
  await screen.findByRole("heading", { name: "1 profile" });
  expect(screen.getByLabelText("Keywords")).toHaveValue("engineer");
  expect(screen.getByRole("checkbox", { name: /Python/ })).toBeChecked();
  expect(screen.getByRole("checkbox", { name: /Django/ })).toBeChecked();
  expect(screen.getByRole("checkbox", { name: /Backend Engineer/ })).toBeChecked();
});

test("keyword submission updates the URL and request only on submit", async () => {
  const { router } = renderApp();
  await screen.findByRole("heading", { name: "1 profile" });
  const user = userEvent.setup();
  await user.clear(screen.getByLabelText("Keywords"));
  await user.type(screen.getByLabelText("Keywords"), "  platform   engineer  ");
  expect(searchMock).toHaveBeenCalledOnce();
  await user.click(screen.getByRole("button", { name: "Search" }));
  await waitFor(() => expect(router.state.location.search).toBe("?q=platform+engineer"));
  expect(searchMock).toHaveBeenLastCalledWith(expect.objectContaining({ q: "platform engineer", page: 1 }), expect.any(AbortSignal));
});

test("Enter submits a filter-only search with repeated filters", async () => {
  const { router } = renderApp();
  await screen.findByRole("heading", { name: "1 profile" });
  const user = userEvent.setup();
  await user.click(screen.getByRole("checkbox", { name: /Python/ }));
  await user.click(screen.getByRole("checkbox", { name: /Django/ }));
  await user.click(screen.getByRole("checkbox", { name: /Backend Engineer/ }));
  fireEvent.submit(screen.getByLabelText("Keywords").closest("form")!);
  await waitFor(() => expect(router.state.location.search).toContain("skill=Python&skill=Django"));
  expect(router.state.location.search).toContain("job_title=Backend+Engineer");
  expect(searchMock).toHaveBeenLastCalledWith(
    expect.objectContaining({ q: "", skill: ["Python", "Django"], job_title: ["Backend Engineer"] }),
    expect.any(AbortSignal),
  );
});

test("Apply filters combines all supported categories and resets page", async () => {
  searchMock.mockImplementation((state) => Promise.resolve(response({
    page: state.page,
    count: 41,
    total_pages: 3,
  })));
  const { router } = renderApp("/search?q=engineer&page=3");
  await screen.findByRole("heading", { name: "41 profiles" });
  const user = userEvent.setup();
  for (const name of [/Python/, /Backend Engineer/, /Software/, /Finland/, /Example Company/]) {
    await user.click(screen.getByRole("checkbox", { name }));
  }
  await user.click(screen.getByRole("button", { name: "Apply filters" }));
  await waitFor(() => expect(router.state.location.search).not.toContain("page=3"));
  expect(router.state.location.search).toBe("?q=engineer&skill=Python&job_title=Backend+Engineer&industry=Software&country=Finland&company=Example+Company");
});

test("clear filters returns to the documented default state", async () => {
  const { router } = renderApp("/search?q=engineer&skill=Python&page=2&page_size=50");
  await screen.findByRole("heading", { name: "1 profile" });
  await userEvent.setup().click(screen.getByRole("button", { name: "Clear filters" }));
  await waitFor(() => expect(router.state.location.search).toBe(""));
  expect(screen.getByLabelText("Keywords")).toHaveValue("");
  expect(searchMock).toHaveBeenLastCalledWith(expect.objectContaining({ q: "", skill: [], page: 1, page_size: 20 }), expect.any(AbortSignal));
});

test("router navigation restores form controls and results", async () => {
  const { router } = renderApp("/search?q=first");
  await screen.findByRole("heading", { name: "1 profile" });
  await act(() => router.navigate("/search?q=second&country=Finland&page=2"));
  await waitFor(() => expect(screen.getByLabelText("Keywords")).toHaveValue("second"));
  expect(screen.getByRole("checkbox", { name: /Finland/ })).toBeChecked();
  expect(searchMock).toHaveBeenLastCalledWith(expect.objectContaining({ q: "second", country: ["Finland"], page: 2 }), expect.any(AbortSignal));
});

test("unknown parameters and invalid pagination are canonicalized safely", async () => {
  const { router } = renderApp("/search?token=secret&page=0&page_size=999&q=test&q=ignored");
  await screen.findByRole("heading", { name: "1 profile" });
  await waitFor(() => expect(router.state.location.search).toBe("?q=test"));
  expect(router.state.location.search).not.toContain("token");
});

test("renders exact count, result fields, safe text, and truncated skills", async () => {
  searchMock.mockResolvedValue(response({
    count: 21,
    total_pages: 2,
    results: [{
      id: 9,
      full_name: "Profile Name",
      job_title: "Principal Engineer",
      company: "Company",
      country: "Canada",
      industry: "Technology",
      skills: ["One", "Two", "Three", "Four", "Five", "Six", "Seven"],
      summary: "<img src=x onerror=alert(1)> summary",
    }],
  }));
  renderApp();
  expect(await screen.findByRole("heading", { name: "21 profiles" })).toBeInTheDocument();
  expect(screen.getByText("Principal Engineer at Company")).toBeInTheDocument();
  expect(screen.getByText("Canada · Technology")).toBeInTheDocument();
  expect(screen.getByText("+2 more")).toBeInTheDocument();
  expect(screen.getByText("<img src=x onerror=alert(1)> summary")).toBeInTheDocument();
  expect(document.querySelector("img")).toBeNull();
});

test("handles missing optional result fields without empty labels", async () => {
  searchMock.mockResolvedValue(response({ results: [{
    id: 7, full_name: "", job_title: "", company: "", industry: "", country: "", skills: [], summary: "",
  }] }));
  renderApp();
  expect(await screen.findByRole("heading", { name: "Unnamed profile" })).toBeInTheDocument();
  expect(screen.queryByText(/^at$/)).not.toBeInTheDocument();
});

test("preserves selected values that are absent from current facets", async () => {
  renderApp("/search?skill=Rare+Skill");
  await screen.findByRole("heading", { name: "1 profile" });
  expect(screen.getByRole("checkbox", { name: /Rare Skill.*selected/ })).toBeChecked();
});

test("shows initial loading without results and then renders data", async () => {
  const pending = deferred<ProfileSearchResponse>();
  searchMock.mockReturnValue(pending.promise);
  renderApp();
  expect(await screen.findByText("Loading profiles…")).toBeInTheDocument();
  expect(screen.queryByRole("heading", { name: "1 profile" })).not.toBeInTheDocument();
  pending.resolve(response());
  expect(await screen.findByRole("heading", { name: "1 profile" })).toBeInTheDocument();
});

test("marks same-search background refreshes as updating", async () => {
  const { queryClient } = renderApp();
  await screen.findByRole("heading", { name: "1 profile" });
  const pending = deferred<ProfileSearchResponse>();
  searchMock.mockReturnValue(pending.promise);
  act(() => {
    void queryClient.invalidateQueries({ queryKey: ["profile-search"] });
  });
  expect(await screen.findByRole("status")).toHaveTextContent("Updating results");
  expect(screen.getByRole("heading", { name: "1 profile" })).toBeInTheDocument();
  await act(async () => {
    pending.resolve(response());
    await pending.promise;
  });
  await waitFor(() => expect(screen.queryByText("Updating results…")).not.toBeInTheDocument());
});

test("renders no-results state with controls retained", async () => {
  searchMock.mockResolvedValue(response({ count: 0, total_pages: 0, results: [] }));
  renderApp("/search?q=nobody");
  expect(await screen.findByRole("heading", { name: "0 profiles" })).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "No profiles found" })).toBeInTheDocument();
  expect(screen.getByLabelText("Keywords")).toHaveValue("nobody");
  expect(screen.getByRole("button", { name: "Next" })).toBeDisabled();
});

test("corrects an out-of-range page without rendering the invalid page or no-results state", async () => {
  searchMock.mockImplementation((state) => {
    if (state.page === 4) {
      return Promise.resolve(response({
        count: 41,
        page: 4,
        total_pages: 3,
        results: [],
      }));
    }
    return Promise.resolve(response({
      count: 41,
      page: state.page,
      total_pages: 3,
    }));
  });
  const { router } = renderApp("/search?q=engineer&skill=Python&page=4&page_size=20");

  expect(screen.queryByText("Page 4 of 3")).not.toBeInTheDocument();
  expect(screen.queryByRole("heading", { name: "No profiles found" })).not.toBeInTheDocument();
  await waitFor(() => expect(router.state.location.search).toBe("?q=engineer&skill=Python&page=3"));
  expect(await screen.findByRole("heading", { name: "41 profiles" })).toBeInTheDocument();
  expect(searchMock).toHaveBeenCalledTimes(2);
});

test("corrects an out-of-range zero-result page to page one while preserving criteria", async () => {
  searchMock.mockImplementation((state) => Promise.resolve(response({
    count: 0,
    page: state.page,
    page_size: 50,
    total_pages: 0,
    results: [],
  })));
  const { router } = renderApp("/search?q=nobody&country=Finland&page=2&page_size=50");

  expect(screen.queryByText("Page 2 of 1")).not.toBeInTheDocument();
  await waitFor(() => expect(router.state.location.search).toBe("?q=nobody&country=Finland&page_size=50"));
  expect(await screen.findByRole("heading", { name: "0 profiles" })).toBeInTheDocument();
  expect(searchMock).toHaveBeenCalledTimes(2);
});

test("a superseded search cannot replace the newer result and each query owns its signal", async () => {
  const requests: Array<{
    state: Parameters<typeof searchMock>[0];
    signal: AbortSignal;
    pending: ReturnType<typeof deferred<ProfileSearchResponse>>;
  }> = [];
  searchMock.mockImplementation((state, signal) => {
    const pending = deferred<ProfileSearchResponse>();
    requests.push({ state, signal: signal!, pending });
    return pending.promise;
  });
  const { router } = renderApp("/search?q=first");
  await waitFor(() => expect(requests).toHaveLength(1));

  await act(async () => {
    await router.navigate("/search?q=second");
  });
  await waitFor(() => expect(requests).toHaveLength(2));
  requests[1].pending.resolve(response({
    results: [{ ...response().results[0], id: 8, full_name: "Second Result" }],
  }));
  expect(await screen.findByRole("heading", { name: "1 profile" })).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "Second Result" })).toBeInTheDocument();
  expect(requests[0].signal).not.toBe(requests[1].signal);
  expect(requests[0].signal.aborted).toBe(true);

  requests[0].pending.resolve(response({
    results: [{ ...response().results[0], id: 9, full_name: "First Result" }],
  }));
  await waitFor(() => expect(screen.queryByRole("heading", { name: "First Result" })).not.toBeInTheDocument());
  expect(screen.getByRole("heading", { name: "Second Result" })).toBeInTheDocument();
});

test.each([
  [new ApiError("raw validation", "validation", 400), "Invalid search"],
  [new ApiError("private server", "server", 500), "Search could not be completed"],
  [new ApiError("private network", "network"), "Connection problem"],
  [new profilesApi.MalformedResponseError(), "Search response could not be displayed"],
])("renders a stable error for %p", async (error, heading) => {
  searchMock.mockRejectedValue(error);
  renderApp();
  expect(await screen.findByRole("heading", { name: heading })).toBeInTheDocument();
  expect(screen.queryByText(/private|raw validation/)).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
});

test("503 is distinct and manual retry recovers", async () => {
  searchMock.mockRejectedValue(new ApiError("private", "server", 503));
  renderApp();
  expect(await screen.findByRole("heading", { name: "Search is temporarily unavailable" })).toBeInTheDocument();
  expect(searchMock).toHaveBeenCalledTimes(2);
  searchMock.mockResolvedValue(response());
  await userEvent.setup().click(screen.getByRole("button", { name: "Retry" }));
  expect(await screen.findByRole("heading", { name: "1 profile" })).toBeInTheDocument();
});

test("pagination enforces boundaries and preserves search criteria", async () => {
  searchMock.mockImplementation((state) => Promise.resolve(response({ page: state.page, count: 41, total_pages: 3 })));
  const { router } = renderApp("/search?q=engineer&skill=Python");
  expect((await screen.findAllByText("Page 1 of 3")).length).toBeGreaterThan(0);
  expect(screen.getByRole("button", { name: "Previous" })).toBeDisabled();
  await userEvent.setup().click(screen.getByRole("button", { name: "Next" }));
  await waitFor(() => expect(router.state.location.search).toBe("?q=engineer&skill=Python&page=2"));
  expect((await screen.findAllByText("Page 2 of 3")).length).toBeGreaterThan(0);
  expect(searchMock).toHaveBeenLastCalledWith(expect.objectContaining({ q: "engineer", skill: ["Python"], page: 2 }), expect.any(AbortSignal));
});

test("result links preserve the full canonical search return destination", async () => {
  searchMock.mockResolvedValue(response({ page: 2, count: 11, page_size: 10, total_pages: 2 }));
  renderApp("/search?q=engineer&skill=Python&page=2&page_size=10");
  const card = (await screen.findByRole("heading", { name: "Example Person" })).closest("article")!;
  const link = within(card).getByRole("link", { name: "Example Person" });
  expect(link).toHaveAttribute("href", expect.stringContaining("return_to=%2Fsearch%3Fq%3Dengineer%26skill%3DPython%26page%3D2%26page_size%3D10"));
});

test("query cache keys never contain authentication tokens", async () => {
  const { queryClient } = renderApp();
  await screen.findByRole("heading", { name: "1 profile" });
  const keys = JSON.stringify(queryClient.getQueryCache().getAll().map((query) => query.queryKey));
  expect(keys).not.toContain("test-access");
  expect(keys).not.toContain("test-refresh");
});

test("a terminal search 401 uses the existing session-expiry redirect", async () => {
  vi.mocked(fetch).mockImplementation((input: RequestInfo | URL) => {
    const url = String(input);
    if (url.includes("/token/refresh/")) {
      return Promise.resolve(jsonResponse({ access: "fresh-access" }));
    }
    if (url.includes("/auth/me/")) {
      return Promise.resolve(jsonResponse({ id: 1, username: "reviewer", email: "" }));
    }
    if (url.includes("/profiles/search/")) {
      return Promise.resolve(jsonResponse({ detail: "expired" }, 401));
    }
    return Promise.reject(new Error("Unexpected fetch"));
  });
  searchMock.mockImplementation((_state, signal) =>
    apiClient.protectedRequest<ProfileSearchResponse>(
      "/api/v1/profiles/search/?page=1&page_size=20",
      { signal },
    ),
  );
  const { router } = renderApp();
  expect(await screen.findByRole("heading", { name: "Sign in" })).toBeInTheDocument();
  expect(router.state.location.pathname).toBe("/login");
  expect(tokenStore.getAccessToken()).toBeNull();
  expect(tokenStore.getRefreshToken()).toBeNull();
});
