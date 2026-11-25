# Assistant UI

The page people see when they open the app: the NVIDIA AI Research Assistant, a chat over the
OpenCode server that runs in the sandbox. It shows what the agent does as it does it: each tool
call with what was sent and returned, the MCP servers it is connected to, and every request for
the person's approval.

It is served at the app's root. OpenCode is the agent; this page and OpenCode's own web UI are
two windows onto the same server and the same sessions.

```
browser ──▶ Caddy :8080 ──▶ assistant-ui :9002 (server.py)
                               ├─ /            the page (static/)
                               ├─ /api/config  the chips and settings (demo.yaml, environment)
                               ├─ /oc/<path>   OpenCode's API, only the calls the page makes
                               └─ /events      OpenCode's event stream, over a websocket
                                                 │
                                                 ▼
                                    sandbox-broker:4096 ──▶ OpenCode in the sandbox
```

| File | What it is |
|---|---|
| `server.py` | The server: the page, the proxy to OpenCode, the event relay |
| `settings.py` | The calls the page may make, the chips file's checks, the event framing. No web framework, so the tests import it |
| `demo.yaml` | The default chips |
| `examples/ehr-genomics-chips.yaml` | Chips for the EHR-and-genomes synthetic data |
| `static/theme.css` | The brand: colours, fonts, radii. Nothing else |
| `static/app.js`, `style.css`, `index.html` | The page. No build step |
| `static/vendor/` | marked 15.0.12 and DOMPurify 3.4.17, copied from npm |
| `dev/` | Running it without the app (below) |

## What the page shows

- **Chips to start**: one per starter in `demo.yaml`. Picking one opens a session and sends its prompt.
- **Chips for what comes next**, above the text box once the assistant has answered: the Kumo
  forecast, running a registered workflow, and actions the sandbox refuses.
- **Tool calls** as cards: the server, the tool, how long it took; open one for what was sent
  and returned. Repeated `wait_for_reply` calls on a working designer fold into one card. A
  reply holding a `funnel` is drawn as bars.
- **Approvals**: when OpenCode asks before a call (the cohort designer's `respond_approval` and
  `answer_choices`), a card shows what the call sends, with Allow and Deny.
- **Questions**: when the model asks through OpenCode's `question` tool, a card with the options.
- **Side panel**: the MCP servers and their state, the tools used in this session, where the
  assistant runs.
- **Sessions**: the left rail lists them; New session starts a clean one.

## Who sees the page

With `ASSISTANT_ACCESS` set to the app's access state (the ai-policy README, "Access and
features"), a person the app does not admit gets a page that says why, in place of the chat:
not in the beta or alpha group, the check could not be made (retrying), the check has not run
yet, or the app's machine cannot run the model. The page asks again every 30 seconds and
reloads when the answer changes. The chat stays hidden until the settings arrive, so it does not
show before the page. The server enforces the same answer: while the state does not admit the
person, `/oc` answers 403 and `/events` closes, so the gate does not rest on the page alone.
Unset or empty, nobody does: the gate stays shut. `ASSISTANT_ACCESS=open` turns it off, for
local development (`dev/run-dev.sh` sets it).

## Chips

`demo.yaml` has two lists, `starters` and `next_steps`. Each chip is a `label`, a `prompt`
(sent as the person's message, word for word), an optional `hint` and an optional `feature`
(a name from `features.yaml`): such a chip appears only when the access state has that feature
on. An optional `source` is sent with the prompt as a synthetic part of the same message: the
agent reads it (an approved text to answer from, for example) and the page does not draw it. `about` is the text of
the side panel's last section. A chip without a label or a prompt stops the server at start.

The default chips name no condition, gene, dataset or workflow. `examples/ehr-genomics-chips.yaml`
holds chips for a workspace with the EHR-and-genomes synthetic data; the image carries it at
`/opt/assistant-ui/examples/ehr-genomics-chips.yaml`, so `ASSISTANT_DEMO` can point at that path.

## Settings

| Variable | Default | |
|---|---|---|
| `OPENCODE_URL` | `http://127.0.0.1:4096` | The OpenCode server. In the app, `http://sandbox-broker:4096` |
| `ASSISTANT_INPUT` | `free` | `chips` hides the text box, so only the chips send |
| `ASSISTANT_TITLE` | `NVIDIA AI Research Assistant` | The header and the tab |
| `ASSISTANT_DEMO` | `demo.yaml` beside the server | The chips file |
| `ASSISTANT_ACCESS` | unset (gate shut) | The access state ("Who sees the page"): a file path, or `open` to turn the gate off. In the app, `/ara/access.json` |
| `HOST`, `PORT` | `127.0.0.1`, `9002` | Where the server listens |

## Branding

`static/theme.css` holds every colour and font. Its values are the Verily Workbench style
guide's, with NVIDIA's public green as the accent. To change the look, edit that file. There
are no logo files: the header is text and a square drawn in CSS. To use logos, put them in
`static/` and change the header in `index.html`.

## Working on the UI

The app needs two H100s and an hour to start. The UI needs neither:

```sh
dev/run-dev.sh      # then open http://127.0.0.1:9002/
```

It starts three things and stops them together:

- `dev/stub_cohort_mcp.py`, a stand-in for the cohort designer: the seven tools the sandbox
  sees, the same names and reply shapes, one scripted conversation (choices, then an approval
  to lock, then a locked cohort). Its numbers are made up.
- OpenCode at the version the sandbox image pins, on Gemini through Vertex AI
  (`dev/opencode.dev.json`), with the designer's instructions from `cohort.yaml` and the same
  two tools behind the approval prompt.
- `server.py`.

In a Workbench app, open it through the app's proxy on port 9002. A change to `static/` shows on
reload; a change to `server.py` or `demo.yaml` needs the script restarted.

## What the server lets through

OpenCode's API includes shells, file reads and configuration changes. The page gets none of
them: `settings.py` lists the calls it makes (sessions, messages, sending, stopping, approvals,
questions, MCP status, the configuration for the model's name) and the server answers 404 to
the rest. A test checks every call in `app.js` is on the list. For a permission reply, only the replies
the page sends (`once`, `reject`) pass; `always` is refused with 400.

The calls are also guarded against other sites. A POST with a body must be `application/json`
(415 otherwise). A request the browser marks `Sec-Fetch-Site: cross-site` is refused on `/oc`
(403) and on `/events` (the websocket closes). No query string is passed on to OpenCode. The
server does not compare Origin with Host, because the proxies in front of it may rewrite Host.

Text from the model and from tools is untrusted. It reaches the page as text, or as markdown
through DOMPurify with an allow list: text formatting tags, links and tables, and the attributes
`href`, `title`, `colspan`, `rowspan` and `align`. Nothing that loads a URL (images, media, SVG,
frames, forms, `style`, `src`) survives. The server also sends a Content-Security-Policy that
allows scripts, styles, images and connections from the page's own origin only, so the browser
refuses a fetch to any other host even if the sanitizer missed one.

## Known limitations

- **A refused action** shows as a failed tool card, marked "blocked" when the error says
  denied, blocked, forbidden or policy. The sandbox's log of allowed and denied connections is
  not shown.
- **The Kumo and Parabricks chips** only send their prompts; they do something only when the agent
  has those tools.
- **The designer's artifacts** are shown only as far as tool replies carry them (the funnel).
  The designer's session files are not read.
- **The tools of each MCP server** are not listed, only the ones used: OpenCode's API does not
  return them, and the policy decides which the agent sees.
- **Approval and question prompts** are shown for the page's own session only. A prompt raised
  by a sub-session (a sub-agent's) is not shown.
- **Sessions cannot be renamed or deleted** from the page.

Tests: `python3 -m unittest discover -s tests/ai-research-assistant` (`test_assistant_ui.py`).
