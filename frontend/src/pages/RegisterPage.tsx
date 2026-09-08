import { type FormEvent, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { ApiError, type FieldErrors } from "../api/client";
import { useAuth } from "../auth/authContext";

function FieldError({ errors, field }: { errors: FieldErrors; field: string }) {
  const messages = errors[field];
  if (!messages) return null;
  return (
    <ul className="field-errors" id={`${field}-errors`}>
      {messages.map((message) => (
        <li key={message}>{message}</li>
      ))}
    </ul>
  );
}

export function RegisterPage() {
  const { register } = useAuth();
  const navigate = useNavigate();
  const [username, setUsername] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = useState<FieldErrors>({});
  const [submitting, setSubmitting] = useState(false);
  const submissionInFlight = useRef(false);

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (submissionInFlight.current) return;
    if (!username.trim() || !password) {
      setError("Enter a username and password.");
      return;
    }

    submissionInFlight.current = true;
    setSubmitting(true);
    setError(null);
    setFieldErrors({});
    try {
      await register({
        username: username.trim(),
        password,
        ...(email.trim() ? { email: email.trim() } : {}),
      });
      navigate("/login", { replace: true, state: { registered: true } });
    } catch (requestError) {
      setPassword("");
      if (requestError instanceof ApiError) {
        setError(requestError.message);
        setFieldErrors(requestError.fields);
      } else {
        setError("Unable to register. Please try again.");
      }
    } finally {
      submissionInFlight.current = false;
      setSubmitting(false);
    }
  };

  return (
    <section className="auth-card" aria-labelledby="register-heading">
      <p className="eyebrow">Create an account</p>
      <h1 id="register-heading">Register</h1>
      {error ? (
        <p className="notice error" role="alert">
          {error}
        </p>
      ) : null}
      <form onSubmit={handleSubmit} noValidate>
        <label htmlFor="register-username">Username</label>
        <input
          id="register-username"
          name="username"
          autoComplete="username"
          aria-describedby={fieldErrors.username ? "username-errors" : undefined}
          aria-invalid={Boolean(fieldErrors.username)}
          required
          value={username}
          onChange={(event) => setUsername(event.target.value)}
        />
        <FieldError errors={fieldErrors} field="username" />

        <label htmlFor="register-email">Email <span className="optional">(optional)</span></label>
        <input
          id="register-email"
          name="email"
          type="email"
          autoComplete="email"
          aria-describedby={fieldErrors.email ? "email-errors" : undefined}
          aria-invalid={Boolean(fieldErrors.email)}
          value={email}
          onChange={(event) => setEmail(event.target.value)}
        />
        <FieldError errors={fieldErrors} field="email" />

        <label htmlFor="register-password">Password</label>
        <input
          id="register-password"
          name="password"
          type="password"
          autoComplete="new-password"
          aria-describedby={fieldErrors.password ? "password-errors" : undefined}
          aria-invalid={Boolean(fieldErrors.password)}
          required
          value={password}
          onChange={(event) => setPassword(event.target.value)}
        />
        <FieldError errors={fieldErrors} field="password" />

        <button type="submit" disabled={submitting}>
          {submitting ? "Creating account…" : "Create account"}
        </button>
      </form>
      <p className="auth-alternative">
        Already registered? <Link to="/login">Sign in</Link>
      </p>
    </section>
  );
}
