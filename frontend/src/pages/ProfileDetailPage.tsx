import { useQuery } from "@tanstack/react-query";
import { Link, useParams, useSearchParams } from "react-router-dom";

import {
  getProfile,
  isSafeHttpUrl,
  MalformedResponseError,
  type Education,
  type Experience,
} from "../api/profiles";
import { ApiError } from "../api/client";
import { safeSearchDestination } from "./safeDestination";

function profileIdFrom(value: string | undefined): number | null {
  if (!value || !/^[1-9]\d*$/u.test(value)) return null;
  const id = Number(value);
  return Number.isSafeInteger(id) ? id : null;
}

function detailRetry(failureCount: number, error: Error): boolean {
  if (failureCount >= 1) return false;
  return error instanceof ApiError && error.kind === "network";
}

function dateRange(start: string | null, end: string | null): string | null {
  if (!start && !end) return null;
  return `${start ?? "Unknown start"} – ${end ?? "Present"}`;
}

function ExperienceItem({ experience }: { experience: Experience }) {
  const dates = dateRange(experience.started_at, experience.ended_at);
  return (
    <li className="timeline-item">
      <h3>{experience.title || "Role"}</h3>
      {experience.company ? <p className="timeline-organization">{experience.company}</p> : null}
      {experience.location || dates ? (
        <p className="timeline-meta">{[experience.location, dates].filter(Boolean).join(" · ")}</p>
      ) : null}
      {experience.description ? <p>{experience.description}</p> : null}
    </li>
  );
}

function EducationItem({ education }: { education: Education }) {
  const dates = dateRange(education.started_at, education.ended_at);
  return (
    <li className="timeline-item">
      <h3>{education.school || "Education"}</h3>
      {education.degree || education.field_of_study ? (
        <p className="timeline-organization">
          {[education.degree, education.field_of_study].filter(Boolean).join(", ")}
        </p>
      ) : null}
      {dates ? <p className="timeline-meta">{dates}</p> : null}
    </li>
  );
}

function DetailError({ error, retry }: { error: Error; retry: () => void }) {
  if (error instanceof ApiError && error.status === 404) {
    return (
      <div className="state-card error-state" role="alert">
        <h1>Profile not found</h1>
        <p>The requested profile does not exist or is no longer available.</p>
      </div>
    );
  }
  const malformed = error instanceof MalformedResponseError;
  const network = error instanceof ApiError && error.kind === "network";
  return (
    <div className="state-card error-state" role="alert">
      <h1>{malformed ? "Profile response could not be displayed" : network ? "Connection problem" : "Profile could not be loaded"}</h1>
      <p>
        {malformed
          ? "The service returned an unexpected response. Please try again."
          : network
            ? "We could not reach the service. Check your connection and try again."
            : "Something went wrong while loading this profile. Please try again."}
      </p>
      <button className="secondary-button" type="button" onClick={retry}>Retry</button>
    </div>
  );
}

export function ProfileDetailPage() {
  const { profileId: rawProfileId } = useParams();
  const [params] = useSearchParams();
  const profileId = profileIdFrom(rawProfileId);
  const returnTo = safeSearchDestination(params.get("return_to"));
  const query = useQuery({
    queryKey: ["profile-detail", profileId],
    queryFn: ({ signal }) => getProfile(profileId!, signal),
    enabled: profileId !== null,
    retry: detailRetry,
    retryDelay: 100,
  });

  return (
    <section className="detail-page">
      <Link className="back-link" to={returnTo}><span aria-hidden="true">←</span> Back to results</Link>
      {profileId === null ? (
        <div className="state-card error-state" role="alert">
          <h1>Invalid profile</h1>
          <p>The requested profile address is not valid.</p>
        </div>
      ) : null}
      {profileId !== null && query.isPending ? (
        <div className="detail-loading" role="status">
          <span>Loading profile…</span>
          <div className="skeleton-card detail-skeleton" aria-hidden="true" />
        </div>
      ) : null}
      {query.isError ? <DetailError error={query.error} retry={() => void query.refetch()} /> : null}
      {query.data ? (
        <article className="profile-detail">
          <header className="profile-hero">
            <p className="eyebrow">Profile</p>
            <h1>{query.data.full_name || "Unnamed profile"}</h1>
            {query.data.job_title || query.data.company ? (
              <p className="profile-role">{[query.data.job_title, query.data.company].filter(Boolean).join(" at ")}</p>
            ) : null}
            {query.data.location || query.data.country || query.data.industry ? (
              <p className="profile-meta">
                {[query.data.location, query.data.country, query.data.industry].filter(Boolean).join(" · ")}
              </p>
            ) : null}
            {query.data.profile_url ? (
              isSafeHttpUrl(query.data.profile_url) ? (
                <a className="external-link" href={query.data.profile_url} target="_blank" rel="noreferrer noopener">
                  View LinkedIn profile <span aria-hidden="true">↗</span>
                </a>
              ) : (
                <p className="unsafe-profile-url">Profile URL: {query.data.profile_url}</p>
              )
            ) : null}
          </header>

          {query.data.summary ? (
            <section className="detail-section" aria-labelledby="about-heading">
              <h2 id="about-heading">About</h2>
              <p className="profile-summary">{query.data.summary}</p>
            </section>
          ) : null}
          {query.data.skills.length > 0 ? (
            <section className="detail-section" aria-labelledby="skills-heading">
              <h2 id="skills-heading">Skills</h2>
              <ul className="skill-list detail-skills">
                {query.data.skills.map((skill) => <li key={skill}>{skill}</li>)}
              </ul>
            </section>
          ) : null}
          {query.data.experiences.length > 0 ? (
            <section className="detail-section" aria-labelledby="experience-heading">
              <h2 id="experience-heading">Experience</h2>
              <ol className="timeline-list">
                {query.data.experiences.map((experience, index) => (
                  <ExperienceItem experience={experience} key={`${experience.title}-${experience.company}-${index}`} />
                ))}
              </ol>
            </section>
          ) : null}
          {query.data.education.length > 0 ? (
            <section className="detail-section" aria-labelledby="education-heading">
              <h2 id="education-heading">Education</h2>
              <ol className="timeline-list">
                {query.data.education.map((education, index) => (
                  <EducationItem education={education} key={`${education.school}-${education.degree}-${index}`} />
                ))}
              </ol>
            </section>
          ) : null}
        </article>
      ) : null}
    </section>
  );
}
