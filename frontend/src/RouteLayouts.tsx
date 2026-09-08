import { Navigate, Outlet, useLocation } from "react-router-dom";

import { useAuth } from "./auth/authContext";
import { AuthProvider } from "./auth/AuthProvider";
import { ApplicationShell } from "./ApplicationShell";

function LoadingRoute() {
  return (
    <div className="route-status" role="status">
      Checking your session…
    </div>
  );
}

export function ProtectedRoute() {
  const { status } = useAuth();
  const location = useLocation();

  if (status === "loading") return <LoadingRoute />;
  if (status === "unauthenticated") {
    return <Navigate to="/login" replace state={{ from: location.pathname + location.search }} />;
  }
  return <Outlet />;
}

export function PublicOnlyRoute() {
  const { status } = useAuth();

  if (status === "loading") return <LoadingRoute />;
  if (status === "authenticated") return <Navigate to="/search" replace />;
  return <Outlet />;
}

export function RootLayout() {
  return (
    <AuthProvider>
      <ApplicationShell />
    </AuthProvider>
  );
}
