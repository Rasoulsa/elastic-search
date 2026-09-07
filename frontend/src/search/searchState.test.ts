import {
  applyCriteria,
  defaultSearchState,
  normalizeValueKey,
  normalizeValues,
  searchStateFromParams,
  searchStateKey,
  searchStateToApiParams,
  searchStateToParams,
  withPage,
} from "./searchState";

test("reads and normalizes supported URL search state", () => {
  const state = searchStateFromParams(
    new URLSearchParams("q=%20backend%20%20engineer%20&skill=Python&job_title=Engineer&page=3&page_size=50"),
  );

  expect(state).toEqual({
    q: "backend engineer",
    skill: ["Python"],
    job_title: ["Engineer"],
    industry: [],
    country: [],
    company: [],
    page: 3,
    page_size: 50,
  });
});

test("writes deterministic repeated filter parameters", () => {
  const state = {
    ...defaultSearchState(),
    q: "engineer",
    skill: ["Python", "Django"],
    job_title: ["Backend Engineer", "Staff Engineer"],
    country: ["Finland"],
    page: 2,
    page_size: 50,
  };

  expect(searchStateToParams(state).toString()).toBe(
    "q=engineer&skill=Python&skill=Django&job_title=Backend+Engineer&job_title=Staff+Engineer&country=Finland&page=2&page_size=50",
  );
});

test("removes blanks and deduplicates repeated values", () => {
  const state = searchStateFromParams(
    new URLSearchParams("skill=%20&skill=Python&skill=python&skill=%20Django%20&country="),
  );
  expect(state.skill).toEqual(["Python", "Django"]);
  expect(state.country).toEqual([]);
});

test("deduplicates supported Unicode case-fold equivalents while preserving first spelling", () => {
  expect(normalizeValues(["Straße", "STRASSE", "École", "éCOLE"])).toEqual([
    "Straße",
    "École",
  ]);
  expect(normalizeValues(["ΟΣ", "οσ", "οϲ"])).toEqual(["ΟΣ"]);
  expect(normalizeValues(["東京", "東京", "東京大学", "Москва"])).toEqual([
    "東京",
    "東京大学",
    "Москва",
  ]);
  expect(normalizeValueKey("Straße")).toBe(normalizeValueKey("STRASSE"));
  expect(normalizeValueKey("ΟΣ")).toBe(normalizeValueKey("οσ"));
});

test.each([
  ["page=0", 1, 20],
  ["page=word", 1, 20],
  ["page_size=0", 1, 20],
  ["page_size=101", 1, 20],
  ["page=101&page_size=100", 1, 100],
  ["page=2&page=8&page_size=50&page_size=100", 2, 50],
])("normalizes invalid or repeated pagination using the first scalar value: %s", (query, page, pageSize) => {
  const state = searchStateFromParams(new URLSearchParams(query));
  expect(state.page).toBe(page);
  expect(state.page_size).toBe(pageSize);
});

test("criteria changes reset the page", () => {
  const current = { ...defaultSearchState(), q: "engineer", page: 4 };
  const next = applyCriteria(current, { ...current, q: "designer", page_size: 20 });
  expect(next.page).toBe(1);
  expect(next.q).toBe("designer");
});

test("reapplying unchanged criteria preserves the page", () => {
  const current = { ...defaultSearchState(), q: "engineer", page: 4 };
  const next = applyCriteria(current, {
    q: current.q,
    skill: current.skill,
    job_title: current.job_title,
    industry: current.industry,
    country: current.country,
    company: current.company,
    page_size: current.page_size,
  });
  expect(next.page).toBe(4);
});

test("page changes preserve criteria", () => {
  const current = { ...defaultSearchState(), q: "engineer", skill: ["Python"] };
  expect(withPage(current, 3)).toEqual({ ...current, page: 3 });
});

test("unknown and repeated scalar parameters are removed from canonical URL output", () => {
  const input = new URLSearchParams("q=first&q=second&unknown=secret&page=2&page=3");
  expect(searchStateToParams(searchStateFromParams(input)).toString()).toBe("q=first&page=2");
});

test("API parameters always include one page and page_size", () => {
  const params = searchStateToApiParams(defaultSearchState());
  expect(params.getAll("page")).toEqual(["1"]);
  expect(params.getAll("page_size")).toEqual(["20"]);
});

test("query keys contain only normalized public search state", () => {
  const key = JSON.stringify(searchStateKey({ ...defaultSearchState(), q: " engineer " }));
  expect(key).toContain("q=engineer");
  expect(key).not.toContain("access");
  expect(key).not.toContain("refresh");
});
