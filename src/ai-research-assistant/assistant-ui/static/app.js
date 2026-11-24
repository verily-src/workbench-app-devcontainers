// The page of the Research Assistant (../README.md). It talks to OpenCode through
// this app's server: oc/<path> is OpenCode's HTTP API, events is a websocket carrying its
// event stream. Every path is relative, because Workbench serves the app under a proxy path.
//
// Text from the model and from tools is untrusted: it reaches the page through textContent,
// or as markdown through DOMPurify.
(function () {
  "use strict";

  var $ = function (id) { return document.getElementById(id); };
  var el = function (tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text != null) node.textContent = text;
    return node;
  };

  var state = {
    config: { starters: [], next_steps: [], about: [], input: "free" },
    sid: null,               // the session shown
    messages: new Map(),     // message id -> { info, parts: Map(part id -> part) }
    nodes: new Map(),        // message id -> its element
    dirty: new Set(),        // message ids to draw again
    open: new Set(),         // ids of the details the person opened
    permissions: new Map(),  // request id -> request, this session's
    questions: new Map(),
    servers: {},             // MCP server name -> status
    busy: false,
    frame: 0,
  };

  // ---- OpenCode ---------------------------------------------------------------------------

  function oc(path, body) {
    // no-store: a session read once while it was empty was otherwise shown empty again.
    var init = body === undefined ? { cache: "no-store" } : {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
      cache: "no-store",
    };
    return fetch("oc/" + path, init).then(function (response) {
      return response.text().then(function (text) {
        var data = null;
        try { data = text ? JSON.parse(text) : null; } catch (e) { data = null; }
        if (!response.ok) {
          throw new Error((data && (data.error || data.message)) || ("The request failed (" + response.status + ")."));
        }
        return data;
      });
    });
  }

  function connect() {
    var url = new URL("events", location.href);
    url.protocol = location.protocol === "https:" ? "wss:" : "ws:";
    var ws = new WebSocket(url.href);
    var pill = $("conn-pill");
    ws.onopen = function () {
      pill.textContent = "connected"; pill.className = "pill pill-status ok";
      // Whatever happened while the stream was down is read again.
      refreshServers(); refreshSessions();
      if (state.sid) loadSession(state.sid);
    };
    ws.onmessage = function (message) {
      var event;
      try { event = JSON.parse(message.data); } catch (e) { return; }
      handle(event);
    };
    ws.onclose = function () {
      pill.textContent = "reconnecting"; pill.className = "pill pill-status bad";
      setTimeout(connect, 2000);
    };
  }

  function handle(event) {
    var p = event.properties || {};
    var type = event.type;
    if (type === "session.created" || type === "session.updated" || type === "session.deleted") {
      return refreshSessionsSoon();
    }
    if (type === "mcp.tools.changed") return refreshServers();
    var sid = p.sessionID || (p.info && p.info.sessionID) || (p.part && p.part.sessionID);
    if (!state.sid || sid !== state.sid) return;

    if (type === "message.updated") {
      message(p.info.id).info = p.info;
      touch(p.info.id);
    } else if (type === "message.removed") {
      state.messages.delete(p.messageID); touch(p.messageID);
    } else if (type === "message.part.updated") {
      message(p.part.messageID).parts.set(p.part.id, p.part);
      touch(p.part.messageID, p.part.type === "tool");
    } else if (type === "message.part.delta") {
      var parts = message(p.messageID).parts;
      var part = parts.get(p.partID);
      if (!part) { part = { id: p.partID, messageID: p.messageID, type: "text" }; parts.set(p.partID, part); }
      part[p.field] = (part[p.field] || "") + p.delta;
      touch(p.messageID);
    } else if (type === "message.part.removed") {
      message(p.messageID).parts.delete(p.partID); touch(p.messageID);
    } else if (type === "session.status") {
      setBusy(p.status && p.status.type !== "idle");
    } else if (type === "session.idle") {
      setBusy(false);
    } else if (type === "session.error") {
      showError(errorText(p.error));
    } else if (type === "permission.asked") {
      state.permissions.set(p.id, p); drawPrompts();
    } else if (type === "question.asked") {
      state.questions.set(p.id, p); drawPrompts();
    } else if (type.indexOf("permission.") === 0 || type.indexOf("question.") === 0) {
      refreshPrompts();
    }
  }

  function errorText(error) {
    if (!error) return "The assistant stopped with an error.";
    var data = error.data || {};
    return data.message || error.message || error.name || "The assistant stopped with an error.";
  }

  // ---- State ------------------------------------------------------------------------------

  function message(id) {
    var entry = state.messages.get(id);
    if (!entry) { entry = { info: { id: id, role: "assistant" }, parts: new Map() }; state.messages.set(id, entry); }
    return entry;
  }

  // Marks a message to be drawn again. A tool change can alter how its neighbours are drawn
  // (the repeated waits fold into one card), so then every message with a tool is drawn again.
  function touch(id, toolChanged) {
    state.dirty.add(id);
    if (toolChanged) {
      state.messages.forEach(function (entry, key) {
        entry.parts.forEach(function (part) { if (part.type === "tool") state.dirty.add(key); });
      });
    }
    if (!state.frame) state.frame = requestAnimationFrame(draw);
  }

  function ordered() {
    return Array.from(state.messages.values()).sort(function (a, b) {
      var ta = (a.info.time && a.info.time.created) || 0, tb = (b.info.time && b.info.time.created) || 0;
      return ta - tb || (a.info.id < b.info.id ? -1 : 1);
    });
  }

  function partsOf(entry) {
    return Array.from(entry.parts.values()).sort(function (a, b) { return a.id < b.id ? -1 : 1; });
  }

  function setBusy(busy) {
    state.busy = !!busy;
    $("working").hidden = !state.busy;
    $("stop").hidden = !state.busy;
    $("send").disabled = state.busy;
    drawChips();
    // The designer's decision buttons show only while the agent waits on the person.
    if (!state.frame) state.frame = requestAnimationFrame(draw);
  }

  function showError(text) {
    $("error").textContent = text || "";
    $("error").hidden = !text;
  }

  function resetSession(sid) {
    state.sid = sid; state.view = (state.view || 0) + 1;
    state.messages.clear(); state.nodes.clear(); state.dirty.clear(); state.open.clear();
    state.permissions.clear(); state.questions.clear();
    $("messages").replaceChildren();
    showError(""); setBusy(false); drawPrompts(); drawUsed(); drawSessions();
  }

  function loadSession(sid, retried) {
    var view = state.view;
    if (!state.messages.size) $("messages").replaceChildren(el("div", "muted loading", "Loading the session\u2026"));
    return oc("session/" + sid + "/message").then(function (list) {
      if (state.sid !== sid || state.view !== view) return;
      state.messages.clear();
      (list || []).forEach(function (item) {
        var entry = message(item.info.id);
        entry.info = item.info;
        (item.parts || []).forEach(function (part) { entry.parts.set(part.id, part); });
      });
      state.nodes.clear(); $("messages").replaceChildren();
      state.messages.forEach(function (_, id) { state.dirty.add(id); });
      draw(); scrollDown(true);
      if (!$("messages").childNodes.length) {
        $("messages").append(el("div", "muted loading", "This session has no messages yet."));
      }
      return Promise.all([refreshPrompts(), oc("session/status").then(function (all) {
        var status = all && all[sid];
        setBusy(status && status.type !== "idle");
      })]);
    }).catch(function (error) {
      if (state.sid !== sid || state.view !== view) return;
      // One more try before saying so: Workbench's proxy drops a request now and then.
      if (!retried) return loadSession(sid, true);
      $("messages").replaceChildren(el("div", "muted loading", "This session could not be loaded. Pick it again to retry."));
      showError(error.message);
    });
  }

  function refreshPrompts() {
    return Promise.all([oc("permission"), oc("question")]).then(function (found) {
      state.permissions.clear(); state.questions.clear();
      (found[0] || []).forEach(function (r) { if (r.sessionID === state.sid) state.permissions.set(r.id, r); });
      (found[1] || []).forEach(function (r) { if (r.sessionID === state.sid) state.questions.set(r.id, r); });
      drawPrompts();
    }).catch(function () {});
  }

  function refreshServers() {
    return oc("mcp").then(function (servers) { state.servers = servers || {}; drawServers(); })
      .catch(function () { state.servers = {}; drawServers(); });
  }

  var sessionsTimer = 0, sessions = [];
  function refreshSessionsSoon() {
    clearTimeout(sessionsTimer); sessionsTimer = setTimeout(refreshSessions, 400);
  }
  function refreshSessions() {
    return oc("session").then(function (list) {
      sessions = (list || []).filter(function (s) { return !s.parentID; }).sort(function (a, b) {
        return ((b.time && b.time.updated) || 0) - ((a.time && a.time.updated) || 0);
      }).slice(0, 20);
      drawSessions();
    }).catch(function () {});
  }

  // ---- Sending ----------------------------------------------------------------------------

  function send(text, title) {
    text = (text || "").trim();
    if (!text || state.busy) return;
    showError(""); setBusy(true);
    var view = state.view;
    var ready = state.sid ? Promise.resolve(state.sid) : oc("session", { title: (title || text).slice(0, 60) })
      .then(function (session) {
        // Shown only if the person is still on the new session's page: one who picked another
        // session meanwhile was pulled back to this one.
        if (state.view === view) { resetSession(session.id); setBusy(true); }
        refreshSessionsSoon(); return session.id;
      });
    ready.then(function (sid) {
      return oc("session/" + sid + "/prompt_async", { parts: [{ type: "text", text: text }] });
    }).catch(function (error) { setBusy(false); showError(error.message); });
  }

  // ---- Drawing ----------------------------------------------------------------------------

  // What chat markdown needs, and nothing that makes the browser fetch a URL by itself: no
  // media, image, SVG, form or frame tags, and no style, src, srcset, poster or background.
  var MARKDOWN_TAGS = ["p", "br", "strong", "b", "em", "i", "del", "s", "code", "pre", "blockquote",
    "ul", "ol", "li", "h1", "h2", "h3", "h4", "h5", "h6", "hr", "a", "table", "thead", "tbody", "tr",
    "th", "td", "span", "div", "sup", "sub"];
  var MARKDOWN_ATTRS = ["href", "title", "colspan", "rowspan", "align"];

  function markdown(text) {
    var html = window.marked.parse(text || "", { breaks: true, gfm: true });
    var box = el("div", "text");
    box.innerHTML = window.DOMPurify.sanitize(html, {
      ALLOWED_TAGS: MARKDOWN_TAGS,
      ALLOWED_ATTR: MARKDOWN_ATTRS,
      ALLOW_DATA_ATTR: false
    });
    box.querySelectorAll("a").forEach(function (a) { a.target = "_blank"; a.rel = "noopener noreferrer"; });
    return box;
  }

  function keepOpen(details, id) {
    details.open = state.open.has(id);
    details.addEventListener("toggle", function () {
      if (details.open) state.open.add(id); else state.open.delete(id);
    });
    return details;
  }

  // "cohort_send_message" is the cohort server's send_message; a tool of no server is OpenCode's own.
  function toolName(tool) {
    var names = Object.keys(state.servers).sort(function (a, b) { return b.length - a.length; });
    for (var i = 0; i < names.length; i++) {
      if (tool.indexOf(names[i] + "_") === 0) return { server: names[i], name: tool.slice(names[i].length + 1) };
    }
    return { server: null, name: tool };
  }

  function parseJson(text) {
    if (typeof text !== "string") return undefined;
    var trimmed = text.trim();
    if (!trimmed || "{[".indexOf(trimmed[0]) < 0) return undefined;
    try { return JSON.parse(trimmed); } catch (e) { return undefined; }
  }

  function pretty(value) {
    var parsed = typeof value === "string" ? parseJson(value) : value;
    if (parsed === undefined) return String(value == null ? "" : value);
    return JSON.stringify(parsed, null, 2);
  }

  function isWait(part) { return /(^|_)wait_for_reply$/.test(part.tool || ""); }

  // Repeated waits on a working designer fold into the last one. Returns part id -> the number
  // of waits it stands for, and the ids folded away.
  function foldWaits() {
    var hidden = new Set(), counts = new Map(), run = [];
    var close = function () {
      if (run.length > 1) {
        run.slice(0, -1).forEach(function (part) { hidden.add(part.id); });
        counts.set(run[run.length - 1].id, run.length);
      }
      run = [];
    };
    ordered().forEach(function (entry) {
      if (entry.info.role === "user") return close();
      partsOf(entry).forEach(function (part) {
        if (part.type === "tool" && isWait(part)) return run.push(part);
        if (part.type === "tool" || (part.type === "text" && (part.text || "").trim())) close();
      });
    });
    close();
    return { hidden: hidden, counts: counts };
  }

  function funnel(rows) {
    if (!Array.isArray(rows) || !rows.length) return null;
    var items = rows.map(function (row) {
      if (!row || typeof row !== "object") return null;
      var n = [row.n, row.count, row.remaining, row.people].find(function (v) { return typeof v === "number"; });
      var label = [row.step, row.label, row.name, row.criterion].find(function (v) { return typeof v === "string"; });
      return n === undefined || !label ? null : { n: n, label: label };
    });
    if (items.indexOf(null) >= 0) return null;
    var top = Math.max.apply(null, items.map(function (i) { return i.n; })) || 1;
    var box = el("div", "funnel");
    items.forEach(function (item) {
      var row = el("div", "funnel-row"), bar = el("div", "funnel-bar"), fill = el("i");
      fill.style.width = Math.max(1, (100 * item.n) / top) + "%";
      bar.append(fill, el("span", null, item.label));
      row.append(bar, el("div", "funnel-n", item.n.toLocaleString()));
      box.append(row);
    });
    return box;
  }

  function toolCard(part, count) {
    var s = part.state || {}, named = toolName(part.tool || "");
    var card = keepOpen(el("details", "tool" + (s.status === "error" ? " error" : "")), part.id);
    var summary = el("summary");
    summary.append(el("span", "tool-server" + (named.server ? "" : " builtin"), named.server || "built-in"),
      el("span", "tool-name", named.name));

    var output = s.status === "completed" ? parseJson(s.output) : undefined;
    var note = "";
    if (output && typeof output === "object" && typeof output.status === "string") note = output.status.replace(/_/g, " ");
    else if (s.input) {
      var first = Object.values(s.input).find(function (v) { return typeof v === "string" && v; });
      if (first) note = first;
    }
    if (count > 1) note = (note ? note + " · " : "") + "waited " + count + " times";
    summary.append(el("span", "tool-note", note));

    var stateBox = el("span", "tool-state");
    if (s.status === "pending" || s.status === "running") {
      stateBox.append(el("span", "spinner"), document.createTextNode("running"));
    } else if (s.status === "error") {
      stateBox.className += " err";
      stateBox.textContent = /denied|blocked|forbidden|not allowed|policy/i.test(s.error || "") ? "blocked" : "failed";
    } else {
      stateBox.className += " ok";
      var ms = s.time && s.time.end ? s.time.end - s.time.start : null;
      stateBox.textContent = ms == null ? "done" : (ms < 1000 ? ms + " ms" : (ms / 1000).toFixed(1) + " s");
    }
    summary.append(stateBox);
    card.append(summary);

    var body = el("div", "tool-body");
    if (s.input && Object.keys(s.input).length) body.append(el("h4", null, "Sent"), el("pre", null, pretty(s.input)));
    if (s.status === "error") body.append(el("h4", null, "Error"), el("pre", null, s.error || ""));
    if (s.status === "completed") body.append(el("h4", null, "Returned"), el("pre", null, pretty(s.output)));
    card.append(body);

    var chart = output && typeof output === "object" ? funnel(output.funnel) : null;
    if (!chart) return card;
    var wrap = el("div");
    wrap.append(card, chart);
    return wrap;
  }

  function drawMessage(entry, fold) {
    var node = el("div", "msg msg-" + (entry.info.role || "assistant"));
    var parts = partsOf(entry);
    if (entry.info.role === "user") {
      var text = parts.filter(function (p) { return p.type === "text" && !p.synthetic; })
        .map(function (p) { return p.text || ""; }).join("\n").trim();
      if (!text) return null;
      node.append(el("div", "bubble", text));
      return node;
    }
    parts.forEach(function (part) {
      if (part.type === "text" && (part.text || "").trim()) {
        node.append(markdown(part.text));
      } else if (part.type === "reasoning" && (part.text || "").trim()) {
        var details = keepOpen(el("details", "thinking"), part.id);
        details.append(el("summary", null, "Thinking"), markdown(part.text));
        node.append(details);
      } else if (part.type === "tool" && !fold.hidden.has(part.id)) {
        node.append(toolCard(part, fold.counts.get(part.id) || 1));
      }
    });
    if (entry.info.error) node.append(el("div", "error", errorText(entry.info.error)));
    return node.childNodes.length ? node : null;
  }

  function nearBottom() {
    var box = $("scroll");
    return box.scrollHeight - box.scrollTop - box.clientHeight < 120;
  }
  function scrollDown(force) {
    var box = $("scroll");
    if (force || nearBottom()) box.scrollTop = box.scrollHeight;
  }

  function draw() {
    state.frame = 0;
    var stick = nearBottom(), fold = foldWaits(), list = $("messages");
    var order = ordered();
    state.dirty.forEach(function (id) {
      var old = state.nodes.get(id), entry = state.messages.get(id);
      var fresh = entry ? drawMessage(entry, fold) : null;
      if (fresh) fresh.dataset.id = id;
      if (old && fresh) old.replaceWith(fresh);
      else if (old) old.remove();
      else if (fresh) {
        // Placed before the first later message already on the page.
        var index = order.indexOf(entry), next = null;
        for (var i = index + 1; i < order.length && !next; i++) next = state.nodes.get(order[i].info.id) || null;
        list.insertBefore(fresh, next);
      }
      if (fresh) state.nodes.set(id, fresh); else state.nodes.delete(id);
    });
    state.dirty.clear();
    var decision = state.busy || state.permissions.size ? null : pendingDecision();
    if ((state.permissions.size && promptInputs() !== state.shownInputs) ||
        (decision ? decision.key : "") !== (state.shownDecision || "")) drawPrompts();
    drawChips(); drawUsed();
    if (stick) scrollDown(true);
  }

  function chip(item, onPick) {
    var button = el("button", "chip");
    button.type = "button";
    button.append(el("span", "chip-label", item.label));
    if (item.hint) button.append(el("span", "chip-hint", item.hint));
    button.addEventListener("click", function () { onPick(item); });
    return button;
  }

  function drawChips() {
    var started = state.messages.size > 0;
    var waiting = state.busy || state.permissions.size > 0 || state.questions.size > 0;
    $("welcome").hidden = started || state.busy;
    var answered = Array.from(state.messages.values()).some(function (e) { return e.info.role === "assistant"; });
    var next = $("next-steps");
    next.hidden = !answered || !state.config.next_steps.length;
    next.querySelectorAll("button").forEach(function (b) { b.disabled = waiting; });
    var working = "Working";
    if (state.permissions.size) working = "Waiting for your approval";
    else if (state.questions.size) working = "Waiting for your answer";
    $("working-text").textContent = working;
  }

  function findTool(callID) {
    var found = null;
    state.messages.forEach(function (entry) {
      entry.parts.forEach(function (part) { if (part.type === "tool" && part.callID === callID) found = part; });
    });
    return found;
  }

  // What the calls awaiting approval send, as one string: the cards are drawn again when a
  // call's input arrives after its request.
  function promptInputs() {
    return JSON.stringify(Array.from(state.permissions.values()).map(function (request) {
      var part = request.tool && findTool(request.tool.callID);
      return (part && part.state && part.state.input) || null;
    }));
  }

  function drawPrompts() {
    var box = $("prompts");
    box.replaceChildren();
    state.shownInputs = promptInputs();
    state.permissions.forEach(function (request) {
      var card = el("div", "ask");
      var named = toolName(request.permission || "");
      card.append(el("h3", null, "Approval needed"));
      card.append(el("p", null, "The assistant wants to call " + named.name +
        (named.server ? " on the " + named.server + " server" : "") + ". It runs only if you allow it."));
      var part = request.tool && findTool(request.tool.callID);
      var input = (part && part.state && part.state.input) || null;
      if (input && Object.keys(input).length) card.append(el("pre", null, pretty(input)));
      var actions = el("div", "ask-actions");
      var allow = el("button", "btn btn-primary", "Allow"), deny = el("button", "btn btn-deny", "Deny");
      var reply = function (answer) {
        allow.disabled = deny.disabled = true;
        oc("permission/" + request.id + "/reply", { reply: answer })
          .then(function () { state.permissions.delete(request.id); drawPrompts(); })
          .catch(function (error) { showError(error.message); refreshPrompts(); });
      };
      allow.addEventListener("click", function () { reply("once"); });
      deny.addEventListener("click", function () { reply("reject"); });
      actions.append(allow, deny);
      card.append(actions);
      box.append(card);
    });
    state.questions.forEach(function (request) {
      var card = el("div", "ask");
      card.append(el("h3", null, "The assistant has a question"));
      var groups = (request.questions || []).map(function (question, index) {
        var group = el("div", "q");
        group.append(el("div", "q-title", question.question || question.header || ""));
        (question.options || []).forEach(function (option) {
          var label = el("label"), input = el("input");
          input.type = question.multiple ? "checkbox" : "radio";
          input.name = request.id + "-" + index; input.value = option.label;
          label.append(input, document.createTextNode(" " + option.label));
          if (option.description) label.append(el("small", null, option.description));
          group.append(label);
        });
        card.append(group);
        return group;
      });
      var actions = el("div", "ask-actions");
      var answer = el("button", "btn btn-primary", "Answer"), skip = el("button", "btn btn-outline", "Skip");
      answer.addEventListener("click", function () {
        var answers = groups.map(function (group) {
          return Array.from(group.querySelectorAll("input:checked")).map(function (i) { return i.value; });
        });
        if (answers.some(function (a) { return !a.length; })) return showError("Pick an answer for each question.");
        showError(""); answer.disabled = skip.disabled = true;
        oc("question/" + request.id + "/reply", { answers: answers })
          .then(function () { state.questions.delete(request.id); drawPrompts(); })
          .catch(function (error) { showError(error.message); refreshPrompts(); });
      });
      skip.addEventListener("click", function () {
        answer.disabled = skip.disabled = true;
        oc("question/" + request.id + "/reject", {})
          .then(function () { state.questions.delete(request.id); drawPrompts(); })
          .catch(function (error) { showError(error.message); refreshPrompts(); });
      });
      actions.append(answer, skip);
      card.append(actions);
      box.append(card);
    });
    drawDecision(box);
    drawChips(); scrollDown(box.childNodes.length > 0);
  }

  // The designer's latest decision for the person: the last cohort call of the session, when it
  // is a wait_for_reply that came back awaiting approval or with choices, and the person has not
  // answered since. Its buttons send the answer as the person's message; the agent relays it.
  function pendingDecision() {
    var order = ordered();
    for (var i = order.length - 1; i >= 0; i--) {
      var entry = order[i];
      if (entry.info.role === "user") return null;
      var parts = partsOf(entry);
      for (var j = parts.length - 1; j >= 0; j--) {
        var part = parts[j];
        if (part.type !== "tool" || toolName(part.tool || "").server !== "cohort") continue;
        if (!isWait(part) || !part.state || part.state.status !== "completed") return null;
        var out = parseJson(part.state.output);
        if (out && out.status === "awaiting_approval") return { kind: "approval", key: part.id, request: out.approval_request || {} };
        if (out && out.status === "idle" && out.choices && out.choices.text) return { kind: "choices", key: part.id, text: out.choices.text };
        return null;
      }
    }
    return null;
  }

  // "1. question" lines, each followed by indented "a. reading" lines.
  function parseChoices(text) {
    var choices = [];
    (text || "").split("\n").forEach(function (line) {
      var q = line.match(/^(\d+)\.\s+(.+)$/), o = line.match(/^\s+([a-z])\.\s+(.+)$/);
      if (q) choices.push({ number: q[1], text: q[2], options: [] });
      else if (o && choices.length) choices[choices.length - 1].options.push({ letter: o[1], text: o[2] });
    });
    return choices.filter(function (c) { return c.options.length; });
  }

  function answer(text) {
    send(text);
    $("input").value = "";
  }

  function drawDecision(box) {
    var decision = state.busy || state.permissions.size ? null : pendingDecision();
    state.shownDecision = decision ? decision.key : "";
    if (!decision) return;
    var card = el("div", "ask decision"), actions = el("div", "ask-actions");
    if (decision.kind === "approval") {
      var op = decision.request.operation === "lock" ? "Lock the cohort?" : "Approve this change?";
      card.append(el("h3", null, "The cohort designer needs your decision"), el("p", null, op));
      var approve = el("button", "btn btn-primary", "Approve"), deny = el("button", "btn btn-deny", "Deny");
      approve.addEventListener("click", function () { answer("Approve."); });
      deny.addEventListener("click", function () {
        var why = $("input").value.trim();
        answer(why ? "Deny: " + why : "Deny.");
      });
      card.append(el("p", "muted", "To say why you deny, type it in the box first."));
      actions.append(approve, deny);
    } else {
      var choices = parseChoices(decision.text), picks = {};
      card.append(el("h3", null, "The cohort designer asks you to choose"));
      choices.forEach(function (choice) {
        var group = el("div", "q");
        group.append(el("div", "q-title", choice.number + ". " + choice.text));
        var row = el("div", "ask-actions");
        choice.options.forEach(function (option) {
          var label = option.letter + ". " + option.text.replace(/\s*\(built\)\s*$/, "") + (/\(built\)\s*$/.test(option.text) ? " (as built)" : "");
          var button = el("button", "btn btn-outline", label);
          button.addEventListener("click", function () {
            picks[choice.number] = option.letter;
            row.querySelectorAll("button").forEach(function (b) { b.className = "btn btn-outline"; });
            button.className = "btn btn-primary";
          });
          row.append(button);
        });
        group.append(row);
        card.append(group);
      });
      var sendPicks = el("button", "btn btn-primary", "Send my choices"), built = el("button", "btn btn-outline", "Keep all as built");
      sendPicks.addEventListener("click", function () {
        var codes = choices.map(function (c) { return picks[c.number] ? c.number + picks[c.number] : c.number + " as built"; });
        var words = $("input").value.trim();
        answer(codes.join(", ") + (words ? ". " + words : ""));
      });
      built.addEventListener("click", function () { answer("as built"); });
      actions.append(sendPicks, built);
    }
    card.append(actions);
    box.append(card);
  }

  function drawServers() {
    var list = $("servers"), names = Object.keys(state.servers).sort();
    list.replaceChildren();
    if (!names.length) list.append(el("li", "muted", "No tool servers connected"));
    names.forEach(function (name) {
      var info = state.servers[name] || {}, status = info.status || "unknown";
      var item = el("li"), title = el("div", "server-name");
      title.append(el("span", "dot" + (status === "connected" ? "" : status === "disabled" ? " off" : " bad")),
        document.createTextNode(name));
      item.append(title, el("div", "server-note", status === "connected" ? "MCP server · connected"
        : "MCP server · " + status.replace(/_/g, " ") + (info.error ? ": " + info.error : "")));
      list.append(item);
    });
    // Tool cards name their server, so they are drawn again once the servers are known.
    state.messages.forEach(function (_, id) { state.dirty.add(id); });
    if (state.dirty.size && !state.frame) state.frame = requestAnimationFrame(draw);
  }

  function drawUsed() {
    var counts = new Map();
    state.messages.forEach(function (entry) {
      entry.parts.forEach(function (part) {
        if (part.type === "tool") counts.set(part.tool, (counts.get(part.tool) || 0) + 1);
      });
    });
    var list = $("used");
    list.replaceChildren();
    if (!counts.size) return list.append(el("li", "muted", "Nothing yet"));
    Array.from(counts.keys()).sort().forEach(function (tool) {
      var named = toolName(tool), item = el("li");
      item.append(el("span", "used-count", "×" + counts.get(tool)),
        el("code", null, (named.server ? named.server + " · " : "") + named.name));
      list.append(item);
    });
  }

  function drawSessions() {
    var list = $("sessions");
    list.replaceChildren();
    if (!sessions.length) list.append(el("li", "muted", "No sessions yet"));
    sessions.forEach(function (session) {
      var item = el("li", session.id === state.sid ? "current" : "", session.title || session.slug || session.id);
      item.title = session.title || "";
      item.addEventListener("click", function () {
        if (session.id === state.sid) return;
        resetSession(session.id); loadSession(session.id);
      });
      list.append(item);
    });
  }

  // ---- Start ------------------------------------------------------------------------------

  // The page for a person the app does not let in (yet): the access state's title and message.
  // The message is text; "All of Us" in it, the program's name, is set in italics.
  // It asks again every 30 s and reloads once the answer changes.
  function gate(config) {
    var access = config.access;
    $("gate").hidden = false;
    $("gate-title").textContent = access.title;
    access.message.split(/(All of Us)/).forEach(function (part, i) {
      $("gate-message").append(i % 2 ? el("em", null, part) : document.createTextNode(part));
    });
    setInterval(function () {
      fetch("api/config").then(function (r) { return r.json(); }).then(function (next) {
        if (next.access.state !== access.state || next.access.message !== access.message) location.reload();
      }).catch(function () {});
    }, 30000);
  }

  // The model's name as the page shows it: the provider dropped, Nemotron by its own name rather
  // than its repository id (nvidia/NVIDIA-Nemotron-3.5-Super-VL-120B-A12B-NVFP4), and Gemini's id
  // in words (gemini-3.5-flash is Gemini 3.5 Flash).
  function modelName(model) {
    if (/nemotron-3\.5-super-vl/i.test(model)) return "Nemotron 3.5 Super VL";
    var gemini = /(?:^|\/)(gemini-[a-z0-9.-]+)$/i.exec(model);
    if (gemini) {
      return gemini[1].split("-").map(function (word) { return word.charAt(0).toUpperCase() + word.slice(1); }).join(" ");
    }
    return model.split("/").slice(1).join("/") || model;
  }

  function start(config) {
    state.config = config;
    document.title = config.title; $("title").textContent = config.title;
    if (config.access && config.access.state !== "ok" && config.access.state !== "open") { gate(config); return; }
    ["layout", "new-session", "conn-pill", "model-pill"].forEach(function (id) { $(id).hidden = false; });
    if (config.input === "chips") document.body.classList.add("chips-only");
    config.starters.forEach(function (item) {
      $("starters").append(chip(item, function (picked) { send(picked.prompt, picked.label); }));
    });
    config.next_steps.forEach(function (item) {
      $("next-steps").append(chip(item, function (picked) { send(picked.prompt); }));
    });
    config.about.forEach(function (line) { $("about").append(el("li", null, line)); });

    oc("config").then(function (cfg) {
      var model = (cfg && cfg.model) || "";
      var name = modelName(model);
      $("model-pill").textContent = name || "model";
      $("model-pill").title = "The model answering: " + name;
    }).catch(function () { $("model-pill").textContent = "model unavailable"; });

    var input = $("input");
    var grow = function () { input.style.height = "auto"; input.style.height = Math.min(input.scrollHeight, 160) + "px"; };
    input.addEventListener("input", grow);
    input.addEventListener("keydown", function (event) {
      if (event.key === "Enter" && !event.shiftKey && !event.isComposing) { event.preventDefault(); $("form").requestSubmit(); }
    });
    $("form").addEventListener("submit", function (event) {
      event.preventDefault();
      if (state.busy || !input.value.trim()) return;
      send(input.value); input.value = ""; grow();
    });
    $("stop").addEventListener("click", function () {
      if (state.sid) oc("session/" + state.sid + "/abort", {}).catch(function (error) { showError(error.message); });
    });
    $("new-session").addEventListener("click", function () { resetSession(null); input.focus(); });

    drawChips(); drawServers(); drawSessions();
    connect();
  }

  // The assistant stays hidden until the settings arrive, so a failure is shown on the gate page.
  fetch("api/config").then(function (r) { return r.json(); }).then(start).catch(function () {
    $("gate").hidden = false;
    $("gate-title").textContent = "The page could not load";
    $("gate-message").textContent = "The page could not load its settings. Reload to try again.";
  });
})();
