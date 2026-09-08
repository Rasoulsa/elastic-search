import "@testing-library/jest-dom/vitest";

// jsdom owns the DOM abort classes, while Node's Request performs strict realm checks.
// Keep the real router and jsdom's abort behavior, adapting only Request construction in tests.
const jsdomAbortController = window.AbortController;
const jsdomAbortSignal = window.AbortSignal;
const nativeRequest = globalThis.Request;

class CoherentTestRequest extends nativeRequest {
  constructor(input: RequestInfo | URL, init?: RequestInit) {
    const signal = init?.signal;
    super(input, signal ? { ...init, signal: undefined } : init);
    if (signal) {
      Object.defineProperty(this, "signal", {
        configurable: true,
        enumerable: true,
        value: signal,
      });
    }
  }
}

Object.assign(globalThis, {
  AbortController: jsdomAbortController,
  AbortSignal: jsdomAbortSignal,
  Request: CoherentTestRequest,
});
