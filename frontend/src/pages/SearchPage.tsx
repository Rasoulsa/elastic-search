import { useQuery } from "@tanstack/react-query";
import { type FormEvent, useEffect, useMemo, useRef, useState } from "react";
import { Link, useLocation, useSearchParams } from "react-router-dom";

import {
  MalformedResponseError,
  searchProfiles,
  type ProfileSearchResponse,
  type SearchResult,
} from "../api/profiles";
import { ApiError } from "../api/client";
import { FacetFilter } from "../search/FacetFilter";
import {
  FILTER_PARAMETERS,
  applyCriteria,
  defaultSearchState,
  searchStateFromParams,
  searchStateKey,
  searchStateToParams,
  withPage,
  type FilterParameter,
  type SearchCriteria,
} from "../search/searchState";

const FACET_BY_FILTER = {
  skill: "skills",
  job_title: "job_titles",
  industry: "industries",
  country: "countries",
  company: "companies",
} as const;

const FILTER_LABELS: Record<FilterParameter, string> = {
  skill: "Skills",
  job_title: "Job titles",
  industry: "Industries",
  country: "Countries",
  company: "Companies",
};

function criteriaFromState(state: ReturnType<typeof searchStateFromParams>): SearchCriteria {
  return {
    q: state.q,
    skill: state.skill,
    job_title: state.job_title,
    industry: state.industry,
    country: state.country,
    company: state.company,
    page_size: state.page_size,
  };
}

function retryable(failureCount: number, error: Error): boolean {
  if (failureCount >= 1) return false;
  return error instanceof ApiError && (error.kind === "network" || error.status === 503);
}

function SearchError({ error, retry }: { error: Error; retry: () => void }) {
  let heading = "Search could not be completed";
  let message = "Something went wrong while loading profiles. Please try again.";
  if (error instanceof ApiError && error.status === 400) {
    heading = "Invalid search";
    message = "One or more search values are invalid. Review the filters and try again.";
  } else if (error instanceof ApiError && error.status === 503) {
    heading = "Search is temporarily unavailable";
    message = "Profile search is temporarily unavailable. Please try again shortly.";
  } else if (error instanceof ApiError && error.kind === "network") {
    heading = "Connection problem";
    message = "We could not reach the service. Check your connection and try again.";
  } else if (error instanceof MalformedResponseError) {
    heading = "Search response could not be displayed";
    message = "The service returned an unexpected response. Please try again.";
  }
  return (
    <div className="state-card error-state" role="alert">
      <h2>{heading}</h2>
      <p>{message}</p>
      <button className="secondary-button" type="button" onClick={retry}>Retry</button>
    </div>
  );
}

function SearchSkeleton() {
  return (
    <div className="results-skeleton" role="status" aria-live="polite">
      <span>Loading profiles…</span>
      {[1, 2, 3].map((item) => <div className="skeleton-card" aria-hidden="true" key={item} />)}
    </div>
  );
}

function AdjustingPage() {
  return (
    <div className="results-skeleton page-adjusting" role="status" aria-live="polite">
      Adjusting results page…
    </div>
  );
}

function ResultCard({ result, returnTo }: { result: SearchResult; returnTo: string }) {
  const visibleSkills = result.skills.slice(0, 5);
  const remainingSkills = result.skills.length - visibleSkills.length;
  const title = result.full_name || "Unnamed profile";
  return (
    <article className="result-card">
      <h3>
        <Link to={`/profiles/${result.id}?return_to=${encodeURIComponent(returnTo)}`}>{title}</Link>
      </h3>
      {result.job_title || result.company ? (
        <p className="result-role">
          {[result.job_title, result.company].filter(Boolean).join(" at ")}
        </p>
      ) : null}
      {result.country || result.industry ? (
        <p className="result-meta">{[result.country, result.industry].filter(Boolean).join(" · ")}</p>
      ) : null}
      {visibleSkills.length > 0 ? (
        <ul className="skill-list" aria-label="Skills">
          {visibleSkills.map((skill) => <li key={skill}>{skill}</li>)}
          {remainingSkills > 0 ? <li className="skill-more">+{remainingSkills} more</li> : null}
        </ul>
      ) : null}
      {result.summary ? <p className="result-summary">{result.summary}</p> : null}
      <Link className="detail-link" to={`/profiles/${result.id}?return_to=${encodeURIComponent(returnTo)}`}>
        View profile <span aria-hidden="true">→</span>
      </Link>
    </article>
  );
}

function ActiveSearch({ state, remove }: {
  state: ReturnType<typeof searchStateFromParams>;
  remove: (parameter: "q" | FilterParameter, value?: string) => void;
}) {
  const hasActive = Boolean(state.q || FILTER_PARAMETERS.some((name) => state[name].length));
  if (!hasActive) return <p className="match-all-label">Showing all profiles</p>;
  return (
    <div className="active-search" aria-label="Active search filters">
      {state.q ? (
        <button type="button" className="filter-chip" onClick={() => remove("q")}>
          Keyword: {state.q} <span aria-hidden="true">×</span>
        </button>
      ) : null}
      {FILTER_PARAMETERS.flatMap((parameter) =>
        state[parameter].map((value) => (
          <button
            type="button"
            className="filter-chip"
            key={`${parameter}-${value}`}
            onClick={() => remove(parameter, value)}
          >
            {FILTER_LABELS[parameter]}: {value} <span aria-hidden="true">×</span>
          </button>
        )),
      )}
    </div>
  );
}

export function SearchPage() {
  const [urlParams, setUrlParams] = useSearchParams();
  const location = useLocation();
  const rawParams = urlParams.toString();
  const urlState = useMemo(
    () => searchStateFromParams(new URLSearchParams(rawParams)),
    [rawParams],
  );
  const canonicalParams = useMemo(() => searchStateToParams(urlState).toString(), [urlState]);
  const [draft, setDraft] = useState<SearchCriteria>(() => criteriaFromState(urlState));
  const resultsHeading = useRef<HTMLHeadingElement>(null);
  const focusAfterPageChange = useRef(false);

  useEffect(() => {
    if (rawParams !== canonicalParams) {
      setUrlParams(new URLSearchParams(canonicalParams), { replace: true });
    }
  }, [canonicalParams, rawParams, setUrlParams]);

  useEffect(() => {
    setDraft(criteriaFromState(urlState));
  }, [canonicalParams, urlState]);

  const query = useQuery({
    queryKey: searchStateKey(urlState),
    queryFn: ({ signal }) => searchProfiles(urlState, signal),
    retry: retryable,
    retryDelay: 100,
  });

  useEffect(() => {
    if (focusAfterPageChange.current && query.data?.page === urlState.page) {
      focusAfterPageChange.current = false;
      resultsHeading.current?.focus({ preventScroll: true });
      const reducedMotion = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
      resultsHeading.current?.scrollIntoView?.({
        behavior: reducedMotion ? "auto" : "smooth",
        block: "start",
      });
    }
  }, [query.data, urlState.page]);

  useEffect(() => {
    if (!query.data) return;
    const lastPage = Math.max(1, query.data.total_pages);
    if (query.data.page > lastPage || urlState.page > lastPage) {
      setUrlParams(searchStateToParams(withPage(urlState, lastPage)), { replace: true });
    }
  }, [query.data, setUrlParams, urlState]);

  const writeState = (state: typeof urlState) => setUrlParams(searchStateToParams(state));
  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    writeState(applyCriteria(urlState, draft));
  };
  const clear = () => {
    const cleared = defaultSearchState();
    setDraft(criteriaFromState(cleared));
    writeState(cleared);
  };
  const updateFilter = (name: FilterParameter, values: string[]) => {
    setDraft((current) => ({ ...current, [name]: values }));
  };
  const removeActive = (parameter: "q" | FilterParameter, value?: string) => {
    const next = { ...urlState, page: 1 };
    if (parameter === "q") next.q = "";
    else next[parameter] = next[parameter].filter((item) => item !== value);
    writeState(next);
  };
  const goToPage = (page: number) => {
    const maximum = query.data?.total_pages ?? 0;
    if (page < 1 || page > maximum || page === urlState.page) return;
    focusAfterPageChange.current = true;
    writeState(withPage(urlState, page));
  };

  const facets = query.data?.facets;
  const adjustingPage = Boolean(
    query.data && query.data.page > Math.max(query.data.total_pages, 1),
  );
  const returnTo = `${location.pathname}${canonicalParams ? `?${canonicalParams}` : ""}`;

  return (
    <section className="search-page" aria-labelledby="search-heading">
      <header className="search-intro">
        <p className="eyebrow">LinkedIn profile discovery</p>
        <h1 id="search-heading">Profile search</h1>
        <p>Find people by keyword, skills, role, industry, country, or company.</p>
      </header>

      <form className="search-form" onSubmit={submit}>
        <div className="keyword-control">
          <label htmlFor="search-keyword">Keywords</label>
          <div className="keyword-row">
            <input
              id="search-keyword"
              name="q"
              type="search"
              maxLength={500}
              value={draft.q}
              onChange={(event) => setDraft((current) => ({ ...current, q: event.target.value }))}
              placeholder="Name, title, skill, or summary"
            />
            <button className="primary-button" type="submit">Search</button>
          </div>
        </div>

        <div className="search-layout">
          <aside className="filter-panel" aria-label="Search filters">
            <div className="filter-panel-heading">
              <h2>Filters</h2>
              <button className="text-button" type="button" onClick={clear}>Clear filters</button>
            </div>
            {FILTER_PARAMETERS.map((parameter) => (
              <FacetFilter
                key={parameter}
                legend={FILTER_LABELS[parameter]}
                name={parameter}
                options={facets?.[FACET_BY_FILTER[parameter]] ?? []}
                selected={draft[parameter]}
                onChange={(values) => updateFilter(parameter, values)}
              />
            ))}
            <label className="page-size-label" htmlFor="page-size">Results per page</label>
            <select
              id="page-size"
              value={draft.page_size}
              onChange={(event) => setDraft((current) => ({
                ...current,
                page_size: Number(event.target.value),
              }))}
            >
              {[10, 20, 50, 100].map((size) => <option key={size} value={size}>{size}</option>)}
            </select>
            <button className="primary-button apply-button" type="submit">Apply filters</button>
          </aside>

          <div className="results-column">
            <ActiveSearch state={urlState} remove={removeActive} />
            {query.isFetching && query.data ? (
              <p className="updating-status" role="status">Updating results…</p>
            ) : null}
            {query.isPending ? <SearchSkeleton /> : null}
            {query.isError ? <SearchError error={query.error} retry={() => void query.refetch()} /> : null}
            {adjustingPage ? <AdjustingPage /> : null}
            {query.data && !adjustingPage ? (
              <SearchResults
                data={query.data}
                returnTo={returnTo}
                headingRef={resultsHeading}
                clear={clear}
                goToPage={goToPage}
              />
            ) : null}
          </div>
        </div>
      </form>
    </section>
  );
}

function SearchResults({ data, returnTo, headingRef, clear, goToPage }: {
  data: ProfileSearchResponse;
  returnTo: string;
  headingRef: React.RefObject<HTMLHeadingElement | null>;
  clear: () => void;
  goToPage: (page: number) => void;
}) {
  const profileLabel = `${data.count.toLocaleString()} ${data.count === 1 ? "profile" : "profiles"}`;
  return (
    <section className="results-section" aria-labelledby="results-heading">
      <div className="results-heading-row">
        <h2 id="results-heading" ref={headingRef} tabIndex={-1}>{profileLabel}</h2>
        {data.total_pages > 1 ? <span>Page {data.page} of {data.total_pages}</span> : null}
      </div>
      {data.results.length === 0 ? (
        <div className="state-card no-results">
          <h3>No profiles found</h3>
          <p>Try broader keywords or remove one or more filters.</p>
          <button className="secondary-button" type="button" onClick={clear}>Clear filters</button>
        </div>
      ) : (
        <div className="result-list">
          {data.results.map((result) => (
            <ResultCard result={result} returnTo={returnTo} key={result.id} />
          ))}
        </div>
      )}
      <nav className="pagination" aria-label="Search results pages">
        <button
          className="secondary-button"
          type="button"
          disabled={data.page <= 1}
          onClick={() => goToPage(data.page - 1)}
        >Previous</button>
        <span aria-live="polite" aria-current="page">Page {data.page} of {data.total_pages || 1}</span>
        <button
          className="secondary-button"
          type="button"
          disabled={data.total_pages === 0 || data.page >= data.total_pages}
          onClick={() => goToPage(data.page + 1)}
        >Next</button>
      </nav>
    </section>
  );
}
