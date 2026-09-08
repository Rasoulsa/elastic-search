import { Link, Outlet, useNavigate } from "react-router-dom";

import { useAuth } from "./auth/authContext";

export function ApplicationShell() {
  const { logout, status, user } = useAuth();
  const navigate = useNavigate();

  const handleLogout = async () => {
    await logout();
    navigate("/login", { replace: true });
  };

  return (
    <div className="app-shell">
      <header className="app-header">
        <Link className="brand" to="/" aria-label="Profile Search home">
          Profile Search
        </Link>
        {status === "authenticated" && user ? (
          <div className="session-controls">
            <span className="current-user">Signed in as {user.username}</span>
            <button className="secondary-button" type="button" onClick={handleLogout}>
              Sign out
            </button>
          </div>
        ) : null}
      </header>
      <main className="content" id="main-content">
        <Outlet />
      </main>
    </div>
  );
}
