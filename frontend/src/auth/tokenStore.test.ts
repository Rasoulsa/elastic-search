import { createTokenStore } from "./tokenStore";

const TOKEN_KEY = "profile-search.refresh-token";

function storageMock(overrides: Partial<Storage> = {}): Storage {
  return {
    clear: vi.fn(),
    getItem: vi.fn(() => null),
    key: vi.fn(() => null),
    length: 0,
    removeItem: vi.fn(),
    setItem: vi.fn(),
    ...overrides,
  } as Storage;
}

afterEach(() => vi.restoreAllMocks());

test("a successful sessionStorage write does not leave a memory duplicate", () => {
  const storage = sessionStorage;
  const store = createTokenStore(storage);

  store.replaceTokens("access", "refresh");
  storage.removeItem(TOKEN_KEY);

  expect(store.getRefreshToken()).toBeNull();
});

test("a sessionStorage property getter failure uses memory for the lifecycle", () => {
  vi.spyOn(window, "sessionStorage", "get").mockImplementation(() => {
    throw new Error("blocked");
  });
  const store = createTokenStore();

  expect(() => store.replaceTokens("access", "refresh")).not.toThrow();
  expect(store.getRefreshToken()).toBe("refresh");
  expect(() => store.clear()).not.toThrow();
  expect(store.getRefreshToken()).toBeNull();
});

test("a getItem failure returns no token when no fallback exists", () => {
  const storage = storageMock({
    getItem: vi.fn(() => {
      throw new Error("blocked");
    }),
  });
  const store = createTokenStore(storage);

  expect(() => store.getRefreshToken()).not.toThrow();
  expect(store.getRefreshToken()).toBeNull();
});

test("a setItem failure uses the new token as the memory fallback", () => {
  const storage = storageMock({
    getItem: vi.fn(() => "old-refresh"),
    setItem: vi.fn(() => {
      throw new Error("blocked");
    }),
  });
  const store = createTokenStore(storage);

  store.replaceTokens("access", "new-refresh");

  expect(store.getRefreshToken()).toBe("new-refresh");
});

test("a removeItem failure suppresses the stale stored token immediately", () => {
  const storage = storageMock({
    getItem: vi.fn(() => "stale-refresh"),
    removeItem: vi.fn(() => {
      throw new Error("blocked");
    }),
  });
  const store = createTokenStore(storage);

  expect(store.getRefreshToken()).toBe("stale-refresh");
  store.clear();

  expect(store.getRefreshToken()).toBeNull();
});

test("a later login replaces the logical session after failed removal", () => {
  let stored = "stale-refresh";
  const storage = storageMock({
    getItem: vi.fn(() => stored),
    removeItem: vi.fn(() => {
      throw new Error("blocked");
    }),
    setItem: vi.fn((_key, value) => {
      stored = value;
    }),
  });
  const store = createTokenStore(storage);

  store.clear();
  store.replaceTokens("new-access", "new-refresh");

  expect(store.getRefreshToken()).toBe("new-refresh");
  expect(stored).toBe("new-refresh");
});

test("an unavailable store supports login and logout without crashing", () => {
  const storage = storageMock({
    getItem: vi.fn(() => {
      throw new Error("blocked");
    }),
    removeItem: vi.fn(() => {
      throw new Error("blocked");
    }),
    setItem: vi.fn(() => {
      throw new Error("blocked");
    }),
  });
  const store = createTokenStore(storage);

  store.replaceTokens("access", "refresh");
  expect(store.getRefreshToken()).toBe("refresh");
  expect(() => store.clear()).not.toThrow();
  expect(store.getAccessToken()).toBeNull();
  expect(store.getRefreshToken()).toBeNull();
});

test("token storage never touches localStorage", () => {
  const localStorageGetter = vi.spyOn(window, "localStorage", "get").mockImplementation(() => {
    throw new Error("localStorage must not be used");
  });
  const store = createTokenStore(sessionStorage);

  store.replaceTokens("access", "refresh");
  store.clear();

  expect(localStorageGetter).not.toHaveBeenCalled();
});
