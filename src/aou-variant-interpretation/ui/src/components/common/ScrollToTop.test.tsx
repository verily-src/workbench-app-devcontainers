import { render } from "@testing-library/react";
import { useEffect } from "react";
import { MemoryRouter, Route, Routes, useNavigate } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import ScrollToTop from "./ScrollToTop";

function renderWithPath(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <ScrollToTop />
    </MemoryRouter>,
  );
}

function NavigateOnMount({ to }: { to: string }) {
  const navigate = useNavigate();

  useEffect(() => {
    navigate(to);
  }, [navigate, to]);

  return null;
}

describe("ScrollToTop", () => {
  let scrollRestorationDescriptor: PropertyDescriptor | undefined;

  beforeEach(() => {
    vi.mocked(window.scrollTo).mockClear();
    scrollRestorationDescriptor = Object.getOwnPropertyDescriptor(window.history, "scrollRestoration");
  });

  afterEach(() => {
    if (scrollRestorationDescriptor) {
      Object.defineProperty(window.history, "scrollRestoration", scrollRestorationDescriptor);
    } else {
      Reflect.deleteProperty(window.history, "scrollRestoration");
    }
  });

  it("sets manual scroll restoration on mount when supported", () => {
    Object.defineProperty(window.history, "scrollRestoration", {
      configurable: true,
      writable: true,
      value: "auto",
    });

    renderWithPath("/");

    expect(window.history.scrollRestoration).toBe("manual");
  });

  it("scrolls to the top on initial render", () => {
    renderWithPath("/results");

    expect(window.scrollTo).toHaveBeenCalledWith(0, 0);
  });

  it("scrolls to the top again when the pathname changes", () => {
    render(
      <MemoryRouter initialEntries={["/"]}>
        <ScrollToTop />
        <Routes>
          <Route path="/" element={<NavigateOnMount to="/results" />} />
          <Route path="/results" element={null} />
        </Routes>
      </MemoryRouter>,
    );

    expect(window.scrollTo).toHaveBeenCalledTimes(2);
    expect(window.scrollTo).toHaveBeenNthCalledWith(1, 0, 0);
    expect(window.scrollTo).toHaveBeenNthCalledWith(2, 0, 0);
  });
});
