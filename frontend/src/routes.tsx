import { Navigate, type RouteObject } from "react-router-dom";

import { LoginPage } from "./pages/LoginPage";
import { NotFoundPage } from "./pages/NotFoundPage";
import { RegisterPage } from "./pages/RegisterPage";
import { SearchPlaceholderPage } from "./pages/SearchPlaceholderPage";
import { ProtectedRoute, PublicOnlyRoute, RootLayout } from "./RouteLayouts";

export const appRoutes: RouteObject[] = [
  {
    path: "/",
    element: <RootLayout />,
    children: [
      { index: true, element: <Navigate to="/search" replace /> },
      {
        element: <PublicOnlyRoute />,
        children: [
          { path: "login", element: <LoginPage /> },
          { path: "register", element: <RegisterPage /> },
        ],
      },
      {
        element: <ProtectedRoute />,
        children: [{ path: "search", element: <SearchPlaceholderPage /> }],
      },
      { path: "*", element: <NotFoundPage /> },
    ],
  },
];
