import { render, screen } from "@testing-library/react";

import { App } from "./App";

test("renders the application shell", () => {
  render(<App />);

  expect(screen.getByRole("heading", { name: "Find the right people." })).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Profile Search home" })).toHaveAttribute(
    "href",
    "/",
  );
});

