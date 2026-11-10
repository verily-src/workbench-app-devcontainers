(function () {
  "use strict";

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
})();
