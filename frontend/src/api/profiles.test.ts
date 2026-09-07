import {
  MalformedResponseError,
  getProfile,
  parseProfileDetail,
  parseSearchResponse,
  searchProfiles,
} from "./profiles";
import { apiClient } from "./client";
import { defaultSearchState } from "../search/searchState";

const validSearch = {
  count: 1,
  page: 1,
  page_size: 20,
  total_pages: 1,
  results: [{
    id: 7,
    full_name: "Example Person",
    job_title: "Engineer",
    company: "Example Company",
    industry: "Software",
    country: "Finland",
    skills: ["Python"],
    summary: "Summary",
  }],
  facets: {
    skills: [{ value: "python", count: 1 }],
    job_titles: [],
    industries: [],
    countries: [],
    companies: [],
  },
};

const validDetail = {
  id: 7,
  linkedin_id: null,
  linkedin_username: null,
  profile_url: null,
  full_name: "Example Person",
  job_title: "Engineer",
  company: "Example Company",
  industry: "Software",
  location: "Helsinki",
  country: "Finland",
  summary: "Summary",
  skills: ["Python"],
  experiences: [{
    title: "Engineer",
    company: "Example Company",
    location: "Helsinki",
    description: "Description",
    started_at: "2020-01-01",
    ended_at: null,
  }],
  education: [{
    school: "Example University",
    degree: "MSc",
    field_of_study: "Computer Science",
    started_at: null,
    ended_at: null,
  }],
};

test("accepts the complete backend search response contract", () => {
  expect(parseSearchResponse(validSearch, { page: 1, page_size: 20 })).toEqual(validSearch);
});

test.each([
  { ...validSearch, count: -1 },
  { ...validSearch, page: 0 },
  { ...validSearch, page_size: 101 },
  { ...validSearch, total_pages: 1.5 },
  { ...validSearch, results: {} },
  { ...validSearch, results: [{ ...validSearch.results[0], id: "7" }] },
  { ...validSearch, results: [{ ...validSearch.results[0], full_name: null }] },
  { ...validSearch, results: [{ ...validSearch.results[0], skills: ["Python", 3] }] },
  { ...validSearch, facets: { ...validSearch.facets, skills: [{ value: "", count: 1 }] } },
  { ...validSearch, facets: { ...validSearch.facets, skills: [{ value: "python", count: -1 }] } },
  { ...validSearch, count: 1, total_pages: 0 },
  { ...validSearch, count: 41, total_pages: 3, results: [] },
  { ...validSearch, page: 2 },
  { ...validSearch, page_size: 50 },
  { ...validSearch, count: 0, total_pages: 0, results: [validSearch.results[0]] },
])("rejects a malformed search success response", (value) => {
  expect(() => parseSearchResponse(value, { page: 1, page_size: 20 })).toThrow(MalformedResponseError);
});

test.each([
  [
    "middle page with too few results",
    { count: 41, page: 2, page_size: 20, total_pages: 3, resultCount: 19 },
  ],
  [
    "final page with too many results",
    { count: 41, page: 3, page_size: 20, total_pages: 3, resultCount: 2 },
  ],
])("rejects an inconsistent %s", (_name, metadata) => {
  const results = Array.from({ length: metadata.resultCount }, (_, index) => ({
    ...validSearch.results[0],
    id: index + 7,
  }));
  expect(() => parseSearchResponse({ ...validSearch, ...metadata, results }, metadata)).toThrow(
    MalformedResponseError,
  );
});

test("accepts a legitimate empty response for a requested page beyond the final page", () => {
  const response = {
    ...validSearch,
    count: 41,
    page: 4,
    page_size: 20,
    total_pages: 3,
    results: [],
  };
  expect(parseSearchResponse(response, { page: 4, page_size: 20 })).toEqual(response);
});

test("accepts the complete backend detail response contract", () => {
  expect(parseProfileDetail(validDetail)).toEqual(validDetail);
});

afterEach(() => {
  vi.restoreAllMocks();
});

test("searchProfiles builds the authenticated repeated-parameter URL and forwards its signal", async () => {
  const request = vi.spyOn(apiClient, "protectedRequest").mockResolvedValue(validSearch);
  const signal = new AbortController().signal;
  await searchProfiles({
    ...defaultSearchState(),
    q: "backend engineer",
    skill: ["Python", "Django"],
    page: 1,
    page_size: 20,
  }, signal);

  expect(request).toHaveBeenCalledWith(
    "/api/v1/profiles/search/?q=backend+engineer&skill=Python&skill=Django&page=1&page_size=20",
    { signal },
  );
  const path = String(request.mock.calls[0][0]);
  expect(new URLSearchParams(path.split("?", 2)[1])).toEqual(
    new URLSearchParams("q=backend+engineer&skill=Python&skill=Django&page=1&page_size=20"),
  );
  expect(path).not.toContain("access");
  expect(path).not.toContain("refresh");
  expect(path).not.toContain("unknown");
});

test("getProfile validates IDs, uses the authenticated detail path, and forwards its signal", async () => {
  const request = vi.spyOn(apiClient, "protectedRequest").mockResolvedValue(validDetail);
  const signal = new AbortController().signal;
  await getProfile(7, signal);

  expect(request).toHaveBeenCalledWith("/api/v1/profiles/7/", { signal });
  await expect(getProfile(0)).rejects.toMatchObject({ kind: "validation", status: 400 });
  expect(request).toHaveBeenCalledOnce();
});

test.each([
  { ...validDetail, id: 0 },
  { ...validDetail, profile_url: 42 },
  { ...validDetail, summary: null },
  { ...validDetail, skills: "Python" },
  { ...validDetail, experiences: [{ ...validDetail.experiences[0], started_at: 2020 }] },
  { ...validDetail, education: [{ ...validDetail.education[0], school: null }] },
])("rejects a malformed detail success response", (value) => {
  expect(() => parseProfileDetail(value)).toThrow(MalformedResponseError);
});
