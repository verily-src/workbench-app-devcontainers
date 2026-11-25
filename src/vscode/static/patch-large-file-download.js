// Build-time patch for VS Code's browser download (doDownloadBrowser).
//
// Without showDirectoryPicker, a file over 32 MB is read through
// fileService.readFile with a 32 MB limit. The read fails with "too large", but
// VS Code first drains the whole read stream, so the user waits for the entire
// file to transfer (and sees "Downloading" the whole time) before the real
// download starts and transfers it a second time. Fail the read immediately for
// files over the limit so VS Code goes straight to the direct download URL.
//
// Usage: node patch-large-file-download.js <path to workbench.js>
const fs = require("fs");

const file = process.argv[2];
const source = fs.readFileSync(file, "utf8");
const id = "[\\w$]+";
const pattern = new RegExp(
  `try\\{(${id})=\\(await this\\.fileService\\.readFile\\((${id})\\.resource,\\{limits:\\{size:(${id})\\}\\},(${id})\\.token\\)\\)\\.value\\.buffer\\}catch\\{`,
  "g",
);

const matches = source.match(pattern) || [];
if (matches.length !== 1) {
  console.error(
    `Expected one download readFile call in ${file}, found ${matches.length}`,
  );
  process.exit(1);
}

const patched = source.replace(
  pattern,
  (_, out, item, limit, req) =>
    `try{${out}=(await (${item}.size>${limit}?Promise.reject(new Error("file too large")):this.fileService.readFile(${item}.resource,{limits:{size:${limit}}},${req}.token))).value.buffer}catch{`,
);
fs.writeFileSync(file, patched);
console.log(`Patched ${file}`);
