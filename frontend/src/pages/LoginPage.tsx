import { type FormEvent, useRef, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";

import { ApiError } from "../api/client";
import { useAuth } from "../auth/authContext";
import { safeDestination } from "./safeDestination";

export function LoginPage() {
  const { login } = useAuth();
  const location = useLocation();
  const navigate = useNavigate();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const submissionInFlight = useRef(false);
  const routeState = location.state as { from?: unknown; registered?: boolean } | null;

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (submissionInFlight.current) return;
    if (!username.trim() || !password) {
      setError("Enter your username and password.");
      return;
    }

    submissionInFlight.current = true;
    setSubmitting(true);
    setError(null);
    try {
      await login({ username: username.trim(), password });
      navigate(safeDestination(routeState?.from), { replace: true });
    } catch (requestError) {
      setPassword("");
      setError(
        requestError instanceof ApiError
          ? requestError.message
          : "Unable to sign in. Please try again.",
      );
    } finally {
      submissionInFlight.current = false;
      setSubmitting(false);
    }
  };

  return (
    <section className="auth-card" aria-labelledby="login-heading">
      <p className="eyebrow">Welcome back</p>
      <h1 id="login-heading">Sign in</h1>
      {routeState?.registered ? (
        <p className="notice success" role="status">
          Registration complete. Sign in with your new account.
        </p>
      ) : null}
      {error ? (
        <p className="notice error" role="alert">
          {error}
        </p>
      ) : null}
      <form onSubmit={handleSubmit} noValidate>
        <label htmlFor="login-username">Username</label>
        <input
          id="login-username"
          name="username"
          autoComplete="username"
          required
          value={username}
          onChange={(event) => setUsername(event.target.value)}
        />
        <label htmlFor="login-password">Password</label>
        <input
          id="login-password"
          name="password"
          type="password"
          autoComplete="current-password"
          required
          value={password}
          onChange={(event) => setPassword(event.target.value)}
        />
        <button type="submit" disabled={submitting}>
          {submitting ? "Signing in…" : "Sign in"}
        </button>
      </form>
      <p className="auth-alternative">
        Need an account? <Link to="/register">Register</Link>
      </p>
    </section>
  );
}
