import "@testing-library/jest-dom/vitest";
import { vi } from "vitest";

// jsdom doesn't implement scrollTo; ScrollToTop calls it on every route mount.
window.scrollTo = vi.fn();

// jsdom doesn't implement matchMedia either; several components use it to react to viewport
// breakpoints (e.g. the top bar going compact).
// matches: false is an arbitrary but stable default -- individual tests can still override it.
window.matchMedia =
  window.matchMedia ||
  ((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  }));
