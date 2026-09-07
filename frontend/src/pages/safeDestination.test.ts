import { safeDestination } from "./safeDestination";

test.each([
  ["/search", "/search"],
  ["/search?q=engineer&page=2", "/search?q=engineer&page=2"],
  ["https://evil.example/", "/search"],
  ["//evil.example", "/search"],
  ["/\\evil.example", "/search"],
  ["/search\\\\evil", "/search"],
  ["/%5C%5Cevil.example", "/search"],
  ["/%2F%2Fevil.example", "/search"],
  ["javascript:alert(1)", "/search"],
  ["data:text/html,evil", "/search"],
  ["/%", "/search"],
  ["", "/search"],
  [null, "/search"],
])("validates return destination %j", (value, expected) => {
  expect(safeDestination(value)).toBe(expected);
});
