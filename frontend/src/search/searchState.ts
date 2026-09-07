export const DEFAULT_PAGE = 1;
export const DEFAULT_PAGE_SIZE = 20;
export const MAX_PAGE_SIZE = 100;
export const MAX_RESULT_WINDOW = 10_000;

export const FILTER_PARAMETERS = [
  "skill",
  "job_title",
  "industry",
  "country",
  "company",
] as const;

export type FilterParameter = (typeof FILTER_PARAMETERS)[number];

export interface SearchState {
  q: string;
  skill: string[];
  job_title: string[];
  industry: string[];
  country: string[];
  company: string[];
  page: number;
  page_size: number;
}

export type SearchCriteria = Omit<SearchState, "page">;

export function defaultSearchState(): SearchState {
  return {
    q: "",
    skill: [],
    job_title: [],
    industry: [],
    country: [],
    company: [],
    page: DEFAULT_PAGE,
    page_size: DEFAULT_PAGE_SIZE,
  };
}

export function normalizeText(value: string): string {
  return value.normalize("NFKC").trim().replace(/\s+/gu, " ");
}

/**
 * Frontend comparison policy: NFKD, accent removal, lower casing, and the
 * backend's practically relevant case-folding equivalents. The first input
 * spelling remains the display value; this key is only for comparison.
 */
export function normalizeValueKey(value: string): string {
  return normalizeText(value)
    .normalize("NFKD")
    .replace(/\p{M}/gu, "")
    .toLowerCase()
    .replace(/ß/gu, "ss")
    .replace(/ς/gu, "σ");
}

export function normalizeValues(values: readonly string[]): string[] {
  const normalized: string[] = [];
  const seen = new Set<string>();
  for (const value of values) {
    const cleanValue = normalizeText(value);
    const key = normalizeValueKey(cleanValue);
    if (cleanValue && !seen.has(key)) {
      seen.add(key);
      normalized.push(cleanValue);
    }
  }
  return normalized;
}

function positiveInteger(value: string | null, fallback: number, maximum?: number): number {
  if (value === null || !/^\d+$/u.test(value)) return fallback;
  const parsed = Number(value);
  if (!Number.isSafeInteger(parsed) || parsed < 1 || (maximum !== undefined && parsed > maximum)) {
    return fallback;
  }
  return parsed;
}

export function searchStateFromParams(params: URLSearchParams): SearchState {
  const state = defaultSearchState();
  state.q = normalizeText(params.get("q") ?? "");
  for (const parameter of FILTER_PARAMETERS) {
    state[parameter] = normalizeValues(params.getAll(parameter));
  }
  state.page = positiveInteger(params.get("page"), DEFAULT_PAGE);
  state.page_size = positiveInteger(params.get("page_size"), DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE);
  if ((state.page - 1) * state.page_size + state.page_size > MAX_RESULT_WINDOW) {
    state.page = DEFAULT_PAGE;
  }
  return state;
}

export function searchStateToParams(state: SearchState): URLSearchParams {
  const normalized = normalizeSearchState(state);
  const params = new URLSearchParams();
  if (normalized.q) params.set("q", normalized.q);
  for (const parameter of FILTER_PARAMETERS) {
    for (const value of normalized[parameter]) params.append(parameter, value);
  }
  if (normalized.page !== DEFAULT_PAGE) params.set("page", String(normalized.page));
  if (normalized.page_size !== DEFAULT_PAGE_SIZE) {
    params.set("page_size", String(normalized.page_size));
  }
  return params;
}

export function searchStateToApiParams(state: SearchState): URLSearchParams {
  const normalized = normalizeSearchState(state);
  const params = new URLSearchParams();
  if (normalized.q) params.set("q", normalized.q);
  for (const parameter of FILTER_PARAMETERS) {
    for (const value of normalized[parameter]) params.append(parameter, value);
  }
  params.set("page", String(normalized.page));
  params.set("page_size", String(normalized.page_size));
  return params;
}

export function normalizeSearchState(state: SearchState): SearchState {
  const normalized = defaultSearchState();
  normalized.q = normalizeText(state.q);
  for (const parameter of FILTER_PARAMETERS) {
    normalized[parameter] = normalizeValues(state[parameter]);
  }
  normalized.page = positiveInteger(String(state.page), DEFAULT_PAGE);
  normalized.page_size = positiveInteger(
    String(state.page_size),
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
  );
  if (
    (normalized.page - 1) * normalized.page_size + normalized.page_size > MAX_RESULT_WINDOW
  ) {
    normalized.page = DEFAULT_PAGE;
  }
  return normalized;
}

export function applyCriteria(current: SearchState, criteria: SearchCriteria): SearchState {
  const next = normalizeSearchState({ ...criteria, page: DEFAULT_PAGE });
  const currentCriteria = searchStateToParams({ ...current, page: DEFAULT_PAGE }).toString();
  const nextCriteria = searchStateToParams(next).toString();
  return { ...next, page: currentCriteria === nextCriteria ? current.page : DEFAULT_PAGE };
}

export function withPage(state: SearchState, page: number): SearchState {
  return normalizeSearchState({ ...state, page });
}

export function searchStateKey(state: SearchState): readonly ["profile-search", string] {
  return ["profile-search", searchStateToApiParams(state).toString()];
}
