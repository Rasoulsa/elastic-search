import { Link } from "react-router-dom";

export function NotFoundPage() {
  return (
    <section className="route-status" aria-labelledby="not-found-heading">
      <h1 id="not-found-heading">Page not found</h1>
      <p>The page you requested does not exist.</p>
      <Link to="/">Return home</Link>
    </section>
  );
}
