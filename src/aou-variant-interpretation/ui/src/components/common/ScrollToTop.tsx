import { useEffect } from "react";
import { useLocation } from "react-router-dom";

// BrowserRouter navigation uses history.pushState, which (unlike a full page
// load) doesn't reset scroll position on its own.
export default function ScrollToTop() {
  const { pathname } = useLocation();

  useEffect(() => {
    // The browser's own scroll restoration on back/forward navigation runs
    // after this effect and would otherwise override the reset below.
    if ("scrollRestoration" in window.history) {
      window.history.scrollRestoration = "manual";
    }
  }, []);

  useEffect(() => {
    window.scrollTo(0, 0);
  }, [pathname]);

  return null;
}
