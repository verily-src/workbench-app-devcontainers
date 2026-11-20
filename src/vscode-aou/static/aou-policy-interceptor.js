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
    downloadMessage: [
      "The All of Us Data Use Policies prohibit you from removing participant-level data from the workbench. You are also prohibited from publishing or otherwise distributing any data or aggregate statistics corresponding to fewer than 20 participants unless expressly permitted by our data use policies.",
      'To continue, affirm that this download will be used in accordance with the All of Us data use policy by typing "affirm" below.',
    ],
    affirmText: "affirm",
  };

  // VS Code downloads folders and files over 32 MB through showDirectoryPicker.
  // Workbench embeds the app in a cross-origin iframe, where browsers refuse to
  // show file pickers, so those downloads fail silently with a SecurityError.
  // Hiding the API makes VS Code fall back to a direct download for large
  // files. Folders can't be downloaded without the picker.
  try {
    Object.defineProperty(window, "showDirectoryPicker", {
      value: undefined,
      writable: true,
      configurable: true,
    });
  } catch (e) {
    // Leave the API in place if it can't be hidden.
  }

  const REPLAY = "__aouReplay";
  // After the reminder is acknowledged, the next matching action goes through
  // without another prompt. Menu clicks can't be replayed because clicking the
  // dialog closes VS Code's context menu, so the user repeats the action.
  const ACK_WINDOW_MS = 60 * 1000;
  const menuAckUntil = { download: 0, upload: 0 };
  // Next file picker selection or drop after an acknowledged upload.
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
        ${
          isDownload
            ? POLICY_CONFIG.downloadMessage.map((m) => `<p>${m}</p>`).join("")
            : `<p>${POLICY_CONFIG.uploadMessage}</p>`
        }
        ${note ? `<p><strong>${note}</strong></p>` : ""}
        ${
          isDownload
            ? `<div class="aou-input-group">
                 <input type="text" id="aou-affirm-input"
                        placeholder="Type 'affirm' to continue"
                        autocomplete="off" spellcheck="false">
               </div>`
            : ""
        }
      </div>
      <div class="aou-modal-footer">
        <button class="aou-button aou-button-secondary" data-action="cancel">Cancel</button>
        <button class="aou-button aou-button-warning" data-action="continue"${isDownload ? " disabled" : ""}>Continue</button>
      </div>
    `;

    const finish = (accepted) => {
      modal.remove();
      callback(accepted);
    };
    const continueButton = content.querySelector('[data-action="continue"]');
    const affirmInput = content.querySelector("#aou-affirm-input");
    const affirmed = () =>
      affirmInput.value.trim().toLowerCase() === POLICY_CONFIG.affirmText;

    content.querySelector('[data-action="cancel"]').onclick = () =>
      finish(false);
    continueButton.onclick = () => {
      if (!affirmInput || affirmed()) finish(true);
    };
    if (affirmInput) {
      affirmInput.oninput = () => {
        continueButton.disabled = !affirmed();
      };
      affirmInput.onkeydown = (e) => {
        if (e.key === "Enter" && affirmed()) continueButton.click();
      };
    }
    modal.onclick = (e) => {
      if (e.target === modal) finish(false);
    };
    modal.onkeydown = (e) => {
      if (e.key === "Escape") finish(false);
      e.stopPropagation();
    };

    modal.appendChild(content);
    document.body.appendChild(modal);
    (affirmInput || continueButton).focus();
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
    function acknowledged(type) {
      return Date.now() < menuAckUntil[type];
    }

    function consume(type) {
      menuAckUntil[type] = 0;
      if (type === "upload") uploadAckUntil = Date.now() + ACK_WINDOW_MS;
    }

    // Clicking the dialog closes VS Code's context menu, so the original click
    // can't be resumed. Remember where the menu was opened, then reopen it on
    // the same element after Continue and choose the item again. The click on
    // Continue is the user gesture the browser needs for the download or the
    // file picker.
    let lastContext = null;
    document.addEventListener(
      "contextmenu",
      (e) => {
        lastContext = { target: e.target, x: e.clientX, y: e.clientY };
      },
      true,
    );

    function findMenuItem(type) {
      return Array.from(
        document.querySelectorAll(".monaco-menu .action-item"),
      ).find((item) => menuAction(item) === type);
    }

    function replayMenuAction(type) {
      return new Promise((resolve) => {
        const ctx = lastContext;
        if (!ctx || !ctx.target.isConnected) return resolve(false);

        const mouse = (name, x, y) =>
          new MouseEvent(name, {
            bubbles: true,
            cancelable: true,
            view: window,
            button: 0,
            clientX: x,
            clientY: y,
          });
        ctx.target.dispatchEvent(mouse("contextmenu", ctx.x, ctx.y));

        let tries = 0;
        const timer = setInterval(() => {
          const item = findMenuItem(type);
          if (item) {
            clearInterval(timer);
            // VS Code ignores clicks that arrive right after a menu opens.
            setTimeout(() => {
              const rect = item.getBoundingClientRect();
              const x = rect.left + rect.width / 2;
              const y = rect.top + rect.height / 2;
              for (const name of ["mousedown", "mouseup", "click"]) {
                item.dispatchEvent(mouse(name, x, y));
              }
              // The menu closes once the item runs.
              setTimeout(() => resolve(!item.isConnected), 400);
            }, 300);
          } else if (++tries > 20) {
            clearInterval(timer);
            resolve(false);
          }
        }, 50);
      });
    }

    function showHint(text) {
      const hint = document.createElement("div");
      hint.className = "aou-hint";
      hint.textContent = text;
      hint.style.cssText =
        "position:fixed;bottom:40px;left:50%;transform:translateX(-50%);" +
        "background:#323232;color:#fff;padding:10px 16px;border-radius:4px;" +
        "z-index:100000;font-size:13px;box-shadow:0 2px 8px rgba(0,0,0,.4)";
      document.body.appendChild(hint);
      setTimeout(() => hint.remove(), 8000);
    }

    function remind(type) {
      if (document.getElementById("aou-policy-modal")) return;
      const label = type === "download" ? "Download" : "Upload";
      createModal(type, async (accepted) => {
        if (!accepted) return;
        // Let the replayed events through the interceptor.
        menuAckUntil[type] = Date.now() + ACK_WINDOW_MS;
        if (await replayMenuAction(type)) {
          consume(type);
        } else {
          showHint(`Choose ${label} again to continue.`);
        }
      });
    }

    function handle(e) {
      const type = menuAction(e.target);
      if (!type) return;

      if (acknowledged(type)) {
        if (e.type === "click") consume(type);
        return;
      }

      stop(e);
      // A click is made of several events; only open one modal for it.
      if (e.type === "click") remind(type);
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
        const type = focused && menuAction(focused);
        if (!type) return;

        if (acknowledged(type)) {
          consume(type);
          return;
        }
        stop(e);
        remind(type);
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
