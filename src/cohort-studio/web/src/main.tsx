import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import "./tokens.css";

let theme: string | null = null;
try { theme = window.localStorage.getItem("cohort-studio-theme"); } catch {}
document.documentElement.dataset.theme =
  theme === "dark" || theme === "light" ? theme : "system";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
