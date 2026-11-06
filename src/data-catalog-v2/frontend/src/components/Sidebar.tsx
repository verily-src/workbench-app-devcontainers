import { Link, useLocation } from "react-router-dom";

const navLinkBase: React.CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 10,
  padding: "10px 14px",
  borderRadius: "var(--wb-radius)",
  fontSize: 14,
  fontWeight: 500,
  color: "var(--wb-sidebar-text)",
  textDecoration: "none",
  transition: "background 0.12s",
};

function NavLink(props: { to: string; label: string; active: boolean; onClick?: () => void }) {
  return (
    <Link
      to={props.to}
      onClick={props.onClick}
      style={{
        ...navLinkBase,
        background: props.active ? "var(--wb-sidebar-active)" : "transparent",
      }}
      onMouseEnter={(e) => {
        if (!props.active) e.currentTarget.style.background = "var(--wb-sidebar-hover)";
      }}
      onMouseLeave={(e) => {
        if (!props.active) e.currentTarget.style.background = "transparent";
      }}
    >
      {props.label}
    </Link>
  );
}

export function Sidebar(props: {
  projectId: string;
  projectName?: string;
  onSettingsClick: () => void;
  onRefresh: () => void;
  onNavigate?: () => void;
}) {
  const location = useLocation();
  const path = location.pathname;

  return (
    <nav
      style={{
        width: "var(--wb-sidebar-width)",
        minWidth: "var(--wb-sidebar-width)",
        height: "100vh",
        background: "var(--wb-sidebar-bg)",
        display: "flex",
        flexDirection: "column",
        overflow: "hidden",
        position: "sticky",
        top: 0,
      }}
    >
      {/* Logo / brand */}
      <div style={{ padding: "20px 20px 12px" }}>
        <Link to="/" style={{ textDecoration: "none", color: "var(--wb-sidebar-text)" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none">
              <path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5" stroke="#fff" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
            <div>
              <div style={{ fontWeight: 700, fontSize: 16, lineHeight: 1.2 }}>workbench</div>
              <div style={{ fontSize: 12, color: "var(--wb-sidebar-muted)", lineHeight: 1.2 }}>Data Catalog v2</div>
            </div>
          </div>
        </Link>
      </div>

      {/* Project badge */}
      <div style={{ padding: "0 20px 12px" }}>
        {props.projectId ? (
          <div
            style={{
              background: "var(--wb-sidebar-active)",
              borderRadius: "var(--wb-radius)",
              padding: "8px 12px",
              fontSize: 13,
              color: "var(--wb-sidebar-text)",
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
            }}
          >
            <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", minWidth: 0 }}>
              {props.projectName ? (
                <span>
                  <span style={{ fontWeight: 600 }}>{props.projectName}</span>
                  <br />
                  <span style={{ fontSize: 11, color: "var(--wb-sidebar-muted)" }}>{props.projectId}</span>
                </span>
              ) : props.projectId}
            </span>
            <button
              type="button"
              onClick={props.onSettingsClick}
              style={{
                background: "none",
                border: "none",
                color: "var(--wb-sidebar-muted)",
                cursor: "pointer",
                fontSize: 14,
                padding: 2,
                lineHeight: 1,
              }}
              title="Settings"
            >
              ⚙
            </button>
          </div>
        ) : null}
      </div>

      {/* Global nav */}
      <div style={{ padding: "0 12px", display: "flex", flexDirection: "column", gap: 2, flex: 1 }}>
        <NavLink to="/" label="Data Catalog" active={path === "/" || path.startsWith("/table/")} onClick={props.onNavigate} />
        <NavLink to="/terminology" label="Terminology" active={path === "/terminology"} onClick={props.onNavigate} />
        <NavLink to="/cohorts" label="Cohort Builder" active={path === "/cohorts"} onClick={props.onNavigate} />
      </div>

      {/* Bottom toolbar */}
      <div
        style={{
          padding: "10px 20px",
          borderTop: "1px solid rgba(255,255,255,0.1)",
          display: "flex",
          gap: 8,
        }}
      >
        <button
          type="button"
          onClick={props.onRefresh}
          style={{
            flex: 1,
            padding: "6px 0",
            background: "var(--wb-sidebar-hover)",
            border: "none",
            borderRadius: "var(--wb-radius)",
            color: "var(--wb-sidebar-text)",
            cursor: "pointer",
            fontSize: 13,
            fontFamily: "var(--wb-font)",
          }}
        >
          Refresh
        </button>
        <button
          type="button"
          onClick={props.onSettingsClick}
          style={{
            flex: 1,
            padding: "6px 0",
            background: "var(--wb-sidebar-hover)",
            border: "none",
            borderRadius: "var(--wb-radius)",
            color: "var(--wb-sidebar-text)",
            cursor: "pointer",
            fontSize: 13,
            fontFamily: "var(--wb-font)",
          }}
        >
          Settings
        </button>
      </div>
    </nav>
  );
}
