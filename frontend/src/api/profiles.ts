import { ApiError, apiClient } from "./client";
import { searchStateToApiParams, type SearchState } from "../search/searchState";

export interface FacetEntry {
  value: string;
  count: number;
}

export interface SearchResult {
  id: number;
  full_name: string;
  job_title: string;
  company: string;
  industry: string;
  country: string;
  skills: string[];
  summary: string;
}

export interface SearchFacets {
  skills: FacetEntry[];
  job_titles: FacetEntry[];
  industries: FacetEntry[];
  countries: FacetEntry[];
  companies: FacetEntry[];
}

export interface ProfileSearchResponse {
  count: number;
  page: number;
  page_size: number;
  total_pages: number;
  results: SearchResult[];
  facets: SearchFacets;
}

export interface SearchPaginationRequest {
  page: number;
  page_size: number;
}

export interface Experience {
  title: string;
  company: string;
  location: string;
  description: string;
  started_at: string | null;
  ended_at: string | null;
}

export interface Education {
  school: string;
  degree: string;
  field_of_study: string;
  started_at: string | null;
  ended_at: string | null;
}

export interface ProfileDetail {
  id: number;
  linkedin_id: string | null;
  linkedin_username: string | null;
  profile_url: string | null;
  full_name: string;
  job_title: string;
  company: string;
  industry: string;
  location: string;
  country: string;
  summary: string;
  skills: string[];
  experiences: Experience[];
  education: Education[];
}

export class MalformedResponseError extends Error {
  constructor() {
    super("The server returned an unexpected response.");
    this.name = "MalformedResponseError";
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isInteger(value: unknown, minimum: number, maximum?: number): value is number {
  return (
    typeof value === "number" &&
    Number.isSafeInteger(value) &&
    Number.isInteger(value) &&
    value >= minimum &&
    (maximum === undefined || value <= maximum)
  );
}

function isText(value: unknown): value is string {
  return typeof value === "string";
}

function isNullableText(value: unknown): value is string | null {
  return value === null || isText(value);
}

function isTextArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every(isText);
}

function isFacetArray(value: unknown): value is FacetEntry[] {
  return (
    Array.isArray(value) &&
    value.every(
      (entry) =>
        isRecord(entry) &&
        isText(entry.value) &&
        entry.value.length > 0 &&
        isInteger(entry.count, 0),
    )
  );
}

function isSearchResult(value: unknown): value is SearchResult {
  return (
    isRecord(value) &&
    isInteger(value.id, 1) &&
    isText(value.full_name) &&
    isText(value.job_title) &&
    isText(value.company) &&
    isText(value.industry) &&
    isText(value.country) &&
    isTextArray(value.skills) &&
    isText(value.summary)
  );
}

export function parseSearchResponse(
  value: unknown,
  expectedPagination?: SearchPaginationRequest,
): ProfileSearchResponse {
  if (
    !isRecord(value) ||
    !isInteger(value.count, 0) ||
    !isInteger(value.page, 1) ||
    !isInteger(value.page_size, 1, 100) ||
    !isInteger(value.total_pages, 0) ||
    !Array.isArray(value.results) ||
    !value.results.every(isSearchResult) ||
    !isRecord(value.facets) ||
    !isFacetArray(value.facets.skills) ||
    !isFacetArray(value.facets.job_titles) ||
    !isFacetArray(value.facets.industries) ||
    !isFacetArray(value.facets.countries) ||
    !isFacetArray(value.facets.companies)
  ) {
    throw new MalformedResponseError();
  }

  const { count, page, page_size: pageSize, total_pages: totalPages, results } = value;
  const expectedTotalPages = count === 0 ? 0 : Math.ceil(count / pageSize);
  if (totalPages !== expectedTotalPages || results.length > pageSize) {
    throw new MalformedResponseError();
  }
  if (count === 0 && results.length !== 0) {
    throw new MalformedResponseError();
  }
  if (expectedPagination) {
    if (
      pageSize !== expectedPagination.page_size ||
      page !== expectedPagination.page
    ) {
      throw new MalformedResponseError();
    }
  }

  const inRange = page <= Math.max(totalPages, 1);
  if (inRange) {
    const expectedResultCount = Math.min(pageSize, count - (page - 1) * pageSize);
    if (expectedResultCount < 0 || results.length !== expectedResultCount) {
      throw new MalformedResponseError();
    }
  } else if (results.length !== 0) {
    throw new MalformedResponseError();
  }
  return value as unknown as ProfileSearchResponse;
}

function isExperience(value: unknown): value is Experience {
  return (
    isRecord(value) &&
    isText(value.title) &&
    isText(value.company) &&
    isText(value.location) &&
    isText(value.description) &&
    isNullableText(value.started_at) &&
    isNullableText(value.ended_at)
  );
}

function isEducation(value: unknown): value is Education {
  return (
    isRecord(value) &&
    isText(value.school) &&
    isText(value.degree) &&
    isText(value.field_of_study) &&
    isNullableText(value.started_at) &&
    isNullableText(value.ended_at)
  );
}

export function parseProfileDetail(value: unknown): ProfileDetail {
  if (
    !isRecord(value) ||
    !isInteger(value.id, 1) ||
    !isNullableText(value.linkedin_id) ||
    !isNullableText(value.linkedin_username) ||
    !isNullableText(value.profile_url) ||
    !isText(value.full_name) ||
    !isText(value.job_title) ||
    !isText(value.company) ||
    !isText(value.industry) ||
    !isText(value.location) ||
    !isText(value.country) ||
    !isText(value.summary) ||
    !isTextArray(value.skills) ||
    !Array.isArray(value.experiences) ||
    !value.experiences.every(isExperience) ||
    !Array.isArray(value.education) ||
    !value.education.every(isEducation)
  ) {
    throw new MalformedResponseError();
  }
  return value as unknown as ProfileDetail;
}

export async function searchProfiles(
  state: SearchState,
  signal?: AbortSignal,
): Promise<ProfileSearchResponse> {
  const params = searchStateToApiParams(state);
  const body = await apiClient.protectedRequest<unknown>(
    `/api/v1/profiles/search/?${params.toString()}`,
    { signal },
  );
  return parseSearchResponse(body, { page: state.page, page_size: state.page_size });
}

export async function getProfile(profileId: number, signal?: AbortSignal): Promise<ProfileDetail> {
  if (!Number.isSafeInteger(profileId) || profileId < 1) {
    throw new ApiError("The requested profile is invalid.", "validation", 400);
  }
  const body = await apiClient.protectedRequest<unknown>(`/api/v1/profiles/${profileId}/`, {
    signal,
  });
  return parseProfileDetail(body);
}

export function isSafeHttpUrl(value: string | null): boolean {
  if (!value) return false;
  try {
    const url = new URL(value);
    return url.protocol === "http:" || url.protocol === "https:";
  } catch {
    return false;
  }
}
