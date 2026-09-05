import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createBrowserRouter, RouterProvider } from "react-router-dom";

import { ApplicationShell } from "./ApplicationShell";

const queryClient = new QueryClient();
const router = createBrowserRouter([
  { path: "/", element: <ApplicationShell /> },
  { path: "*", element: <ApplicationShell /> },
]);

export function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  );
}

