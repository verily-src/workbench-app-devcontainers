# Verily Workbench Style Guide

A reference stylesheet and component library for building custom Workbench apps with consistent Verily branding.

## When to use this

Workbench supports several app types. Most — like **JupyterLab**, **VS Code**, and **RStudio** — come with their own built-in UI and don't need custom styling. This style guide is for the remaining custom apps that serve their own web UI

| App type | Has its own UI? | Use this style guide? |
|---|---|---|
| JupyterLab (`jupyter-template`, `jupyter-aou`, `custom-workbench-jupyter-template`) | Yes (JupyterLab UI) | No |
| VS Code (`vscode`, `vscode-with-llm`, `vscode-docker`) | Yes (code-server UI) | No |
| R Analysis (`r-analysis`, `r-analysis-aou`) | Yes (RStudio UI) | No |
| pgweb | Yes (pgweb UI) | No |
| **Custom web apps** (`playground`, `example`, or any Flask/FastAPI/Node app) | **You build it** | **Yes** |

If you're building a custom app for external customers that renders HTML in the browser — a Flask dashboard, data analysis tool, etc. — this style guide ensures that the appearance of these custom apps is consistent with each other and the Workbench platform.

## What's in the style guide

The file `verily-workbench-style-guide.html` is a self-contained reference page containing:

- **CSS custom properties** (variables) for all brand tokens — colors, fonts, spacing, radii, shadows
- **Component classes** — buttons, cards, badges, hero banners, navbar, footer, search inputs, grid system
- **Live rendered examples** of every component
- **Copy-paste code blocks** next to each component

Open the file in a browser to see everything rendered.

## Quick start

### Option 1: Copy the CSS variables into your app

Copy the entire `verily-workbench-style-guide.html` into your app. This gives you the variables plus all the pre-built component classes (`.btn-primary`, `.card`, `.badge`, `.hero-banner`, `.navbar`, `.footer`, etc.). When you use these variables and classes in your HTML, your UI will automatically adopt the Verily brand styling.

### Option 2: Give it to Claude as a reference when building your app

When prompting Claude (or any LLM) to build a custom Workbench app, include the style guide as context. For example:

> Build me a Flask app that [does X]. For the UI, follow the Verily Workbench style guide in `verily-workbench-style-guide.html` — use its CSS variables, color palette, fonts (Open Sans for body, Poppins for headings), and component patterns (buttons, cards, etc.).

Or attach the file directly and tell Claude to adhere to its design tokens.

## Brand reference

### Colors

| Token | Value | Usage |
|---|---|---|
| `--primary-teal` | `#087a6a` | Links, primary buttons, brand accent |
| `--dark-teal` | `#074D43` | Hero backgrounds, dark sections |
| `--hover-teal` | `#054f45` | Button and link hover states |
| `--lighter-teal` | `#84bdb5` | Input focus borders |
| `--light-gray-bg` | `#F5F6F7` | Card backgrounds, secondary surfaces |
| `--dark-bg` | `#1A1A1A` | Footer background |
| `--primary-text` | `#212529` | Body text |
| `--secondary-text` | `rgba(0,0,0,0.6)` | Muted text, timestamps |

### Typography

| Element | Font family | Weight | Size |
|---|---|---|---|
| Body text | Open Sans | 400 | 1rem (16px) |
| Headings | Open Sans | 600 | 1rem – 2.5rem |
| Hero display | Poppins | 500 | 5rem |
| Hero lead | Poppins | 400 | 2rem |

### Components

| Component | Class | Notes |
|---|---|---|
| Primary button | `.btn .btn-primary` | Teal background, white text, darkens on hover |
| Outline button | `.btn .btn-outline` | Teal border, fills teal on hover |
| Arrow button | `.btn .btn-with-arrow` | Inline-flex with arrow icon that swaps on hover |
| Card | `.card` | Light gray background, `1rem` border radius, flexbox layout |
| Badge | `.badge .badge-light` / `.badge-primary` / `.badge-success` | Small labels for tags and status |
| Hero banner | `.hero-banner` | Dark teal background, Poppins text, full-width section |
| Navbar | `.navbar` | Teal background, white links |
| Footer | `.footer` | Dark background (#1A1A1A), small muted links |
| Search input | `.search-input` | Full-width input with teal focus ring |
| Grid | `.grid .grid-3` | 3-column responsive grid (collapses at 992px and 768px) |

## Responsive behavior

The style guide includes two breakpoints:

- **< 992px (tablet):** 3-column grid becomes 2 columns, hero text scales down
- **< 768px (mobile):** Grid becomes single column, container padding reduces

## File structure recommendation

For a custom Workbench app using this style guide:

```
your-app/
├── devcontainer-template.json
├── docker-compose.yaml
├── Dockerfile
├── app.py                  # (or server.js, main.go, etc.)
├── static/
│   └── style.css           # paste the :root block + any component classes you need
├── templates/
│   └── index.html          # reference the CSS variables in your markup
└── verily-workbench-style-guide.html   # keep for reference
```
