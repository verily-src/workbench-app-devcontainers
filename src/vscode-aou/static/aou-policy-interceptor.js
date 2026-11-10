(function () {
  "use strict";

  // Policy reminders for file transfers in code-server. Modeled on the RStudio
  // AoU interceptor (r-analysis-aou/static/aou-policy-interceptor.js). This only
  // reminds users; egress is limited by the wondershaper sidecar.

  const POLICY_CONFIG = {
    uploadTitle: "Policy Reminder",
    uploadMessage:
      "The All of Us Data Use Policies prohibit you from uploading data or files containing personally identifiable information (PII). Any external data, files, or software that is uploaded into the Workspace should be exclusively for the research purpose that was provided for this Workspace.",
    downloadTitle: "Policy Reminder",
    downloadMessage:
      "The All of Us Data Use Policies prohibit you from removing participant-level data from the workbench. You are also prohibited from publishing or otherwise distributing any data or aggregate statistics corresponding to fewer than 20 participants unless expressly permitted by our data use policies.",
  };

  const REPLAY = "__aouReplay";
  // After the reminder is acknowledged, the next file picker selection or drop
  // goes through without another prompt.
  const ACK_WINDOW_MS = 60 * 1000;
  let uploadAckUntil = 0;

  function createModal(type, callback, note) {
    const existing = document.getElementById("aou-policy-modal");
    if (existing) {
      existing.remove();
    }

    const isDownload = type === "download";
    const modal = document.createElement("div");
    modal.id = "aou-policy-modal";
    modal.className = "aou-modal-overlay";
    modal.setAttribute("role", "dialog");
    modal.setAttribute("aria-modal", "true");

    const content = document.createElement("div");
    content.className = "aou-modal-content";
    content.innerHTML = `
      <div class="aou-modal-header">
        <h2>${isDownload ? POLICY_CONFIG.downloadTitle : POLICY_CONFIG.uploadTitle}</h2>
      </div>
      <div class="aou-modal-body">
        <p>${isDownload ? POLICY_CONFIG.downloadMessage : POLICY_CONFIG.uploadMessage}</p>
        ${note ? `<p><strong>${note}</strong></p>` : ""}
      </div>
      <div class="aou-modal-footer">
        <button class="aou-button aou-button-secondary" data-action="cancel">Cancel</button>
        <button class="aou-button aou-button-warning" data-action="continue">Continue</button>
      </div>
    `;

    const finish = (accepted) => {
      modal.remove();
      callback(accepted);
    };
    content.querySelector('[data-action="cancel"]').onclick = () =>
      finish(false);
    content.querySelector('[data-action="continue"]').onclick = () =>
      finish(true);
    modal.onclick = (e) => {
      if (e.target === modal) finish(false);
    };
    modal.onkeydown = (e) => {
      if (e.key === "Escape") finish(false);
      e.stopPropagation();
    };

    modal.appendChild(content);
    document.body.appendChild(modal);
    content.querySelector('[data-action="continue"]').focus();
  }

  function menuAction(target) {
    const item = target.closest && target.closest(".monaco-menu .action-item");
    if (!item) return null;
    const label = (item.textContent || "").trim().toLowerCase();
    if (label.startsWith("download")) return "download";
    if (label.startsWith("upload")) return "upload";
    return null;
  }

  function stop(e) {
    e.preventDefault();
    e.stopPropagation();
    e.stopImmediatePropagation();
  }

  // Explorer context menu: "Download..." and "Upload...".
  function interceptMenus() {
    let pending = null;

    function handle(e) {
      if (e[REPLAY]) return;
      const type = menuAction(e.target);
      if (!type) return;

      stop(e);
      // A click is made of several events; only open one modal for it.
      if (e.type !== "click" && e.type !== "keydown") return;
      if (document.getElementById("aou-policy-modal")) return;

      const item = e.target.closest(".monaco-menu .action-item");
      pending = item;
      createModal(type, (accepted) => {
        const el = pending;
        pending = null;
        if (!accepted || !el || !el.isConnected) return;
        if (type === "upload") uploadAckUntil = Date.now() + ACK_WINDOW_MS;
        for (const name of ["mousedown", "mouseup", "click"]) {
          const ev = new MouseEvent(name, { bubbles: true, cancelable: true });
          ev[REPLAY] = true;
          el.querySelector(".action-label, a, span").dispatchEvent(ev);
        }
      });
    }

    for (const name of ["mousedown", "mouseup", "click"]) {
      document.addEventListener(name, handle, true);
    }
    document.addEventListener(
      "keydown",
      (e) => {
        if (e.key !== "Enter" && e.key !== " ") return;
        const focused = document.querySelector(
          ".monaco-menu .action-item.focused",
        );
        if (!focused || !menuAction(focused)) return;
        const type = menuAction(focused);
        stop(e);
        createModal(type, (accepted) => {
          if (!accepted || !focused.isConnected) return;
          if (type === "upload") uploadAckUntil = Date.now() + ACK_WINDOW_MS;
          const ev = new MouseEvent("click", { bubbles: true, cancelable: true });
          ev[REPLAY] = true;
          focused.querySelector(".action-label, a, span").dispatchEvent(ev);
        });
      },
      true,
    );
  }

  // The explorer builds a hidden <input type="file"> for "Upload...".
  function interceptFileInputs() {
    document.addEventListener(
      "change",
      (e) => {
        if (!e.target || e.target.type !== "file" || e.target[REPLAY]) return;
        if (!e.target.files || e.target.files.length === 0) return;
        if (Date.now() < uploadAckUntil) {
          uploadAckUntil = 0;
          return;
        }

        stop(e);
        createModal("upload", (accepted) => {
          if (!accepted) {
            e.target.value = "";
            return;
          }
          e.target[REPLAY] = true;
          e.target.dispatchEvent(new Event("change", { bubbles: true }));
          delete e.target[REPLAY];
        });
      },
      true,
    );
  }

  // Dragging files from the local machine into the browser window. The browser
  // drops the drag data once the event handler returns, and VS Code needs the
  // original entries, so the drop can't be replayed. Show the reminder, then ask
  // the user to drop again.
  function interceptDrops() {
    document.addEventListener(
      "drop",
      (e) => {
        const dt = e.dataTransfer;
        if (!dt || !dt.files || dt.files.length === 0) return;
        if (Date.now() < uploadAckUntil) {
          uploadAckUntil = 0;
          return;
        }

        stop(e);
        createModal(
          "upload",
          (accepted) => {
            if (accepted) uploadAckUntil = Date.now() + ACK_WINDOW_MS;
          },
          "After you continue, drop your files again.",
        );
      },
      true,
    );
  }

  function init() {
    interceptMenus();
    interceptFileInputs();
    interceptDrops();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
