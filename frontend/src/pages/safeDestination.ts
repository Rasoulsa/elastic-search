export function safeDestination(value: unknown): string {
  if (
    typeof value !== "string" ||
    value.length === 0 ||
    !value.startsWith("/") ||
    value.startsWith("//")
  ) {
    return "/search";
  }
  if (value.includes("\\")) return "/search";

  let decodedValue: string;
  try {
    decodedValue = decodeURIComponent(value);
  } catch {
    return "/search";
  }
  if (decodedValue.includes("\\") || decodedValue.startsWith("//")) return "/search";

  try {
    const parsed = new URL(value, window.location.origin);
    if (
      parsed.origin !== window.location.origin ||
      !parsed.pathname.startsWith("/") ||
      parsed.pathname.startsWith("//") ||
      parsed.pathname.includes("\\")
    ) {
      return "/search";
    }
    return `${parsed.pathname}${parsed.search}${parsed.hash}`;
  } catch {
    return "/search";
  }
}
