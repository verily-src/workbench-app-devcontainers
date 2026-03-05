# Validation Plan: PHP-130724 — Register .wdl as text MIME type for RStudio

## 1. CI smoke test (automatic)

- [ ] PR triggers the `test-pr.yaml` workflow
- [ ] `r-analysis` smoke test passes
- [ ] `r-analysis-aou` smoke test passes
- [ ] Non-RStudio app smoke tests (e.g., `vscode`) still pass

## 2. Local devcontainer build

- [ ] Build and start the R app locally:
  ```bash
  cd src/r-analysis
  devcontainer up --workspace-folder .
  ```
- [ ] Confirm `/usr/share/mime/packages/wdl.xml` exists in the container:
  ```bash
  devcontainer exec --workspace-folder . /bin/bash -c "cat /usr/share/mime/packages/wdl.xml"
  ```

## 3. MIME resolution check

- [ ] Create a test `.wdl` file with an `import` statement inside the container:
  ```bash
  cat > /tmp/main.wdl << 'EOF'
  import "tasks/align.wdl" as align
  workflow main {
    call align.bwa_mem
  }
  EOF
  ```
- [ ] Verify `xdg-mime query filetype /tmp/main.wdl` returns `text/x-wdl` (not `application/javascript`)
- [ ] Verify `file --mime-type /tmp/main.wdl` returns a `text/*` type

## 4. RStudio Server UI test

- [ ] Open RStudio Server at `localhost:8787`
- [ ] Clone the [reproducer repo](https://github.com/anand-imcm/wgs-varcall) or create a `.wdl` file with `import` statements
- [ ] Click on `workflows/main.wdl` in the RStudio file browser
- [ ] Confirm the file opens in the editor as text (no "binary file" error)
- [ ] Confirm other `.wdl` files (without `import`) also still open normally

## 5. Workbench deployment test

- [ ] Deploy a test `r-analysis` app in a Workbench workspace using the branch image
- [ ] Open the app and clone a repo with `.wdl` files
- [ ] Click on `main.wdl` (the file containing `import` statements) in the RStudio file browser
- [ ] Verify it opens as text, not as binary

## 6. Negative testing

- [ ] Confirm `post-startup.sh` does **not** create `/usr/share/mime/packages/wdl.xml` on a VS Code or Jupyter app (the `command -v rstudio-server` guard should skip it)
- [ ] Verify a VS Code app still starts and functions normally
