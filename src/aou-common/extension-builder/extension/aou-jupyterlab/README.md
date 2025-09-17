# aou_jupyterlab

This JupyterLab extension was created using copier with the [JupyterLab
extension template](https://github.com/jupyterlab/extension-template). The
template parameters are in `.copier-answers.yml` and the template can be updated
with the command:

```bash
copier update --trust
```

This extension is based off of the All of Us Jupyter Notebook extension,
[aou-file-tree-policy-extension.js](https://github.com/all-of-us/workbench/blob/main/api/src/main/webapp/static/aou-file-tree-policy-extension.js), but rewritten for JupyterLab.

## Plugins

### `aou-jupyterlab:filebrowser-download`

Replaces the [default `filebrowser-extension:download`
plugin](https://github.com/jupyterlab/jupyterlab/blob/main/packages/filebrowser-extension/src/index.ts)
with a wrapper to display the policy reminder prompt before downloading a
file or copying a download link from within the file browser widget.

### `aou-jupyterlab:filebrowser-open-browser-tab`

Replaces the [default `filebrowser-extension:open-browser-tab`
plugin](https://github.com/jupyterlab/jupyterlab/blob/main/packages/filebrowser-extension/src/index.ts)
with a wrapper to display the policy reminder prompt before opening a file in
a new browser tab. Internally this could run the `docmanager:open-browser-tab`
command provided by `docmanager-extension:open-browser-tab` extension, replaced
by `aou-jupyterlab:docmanager-open-browser-tab`.

### `aou-jupyterlab:docmanager-download`

Replaces the [default `docmanager-extension:download`
plugin](https://github.com/jupyterlab/jupyterlab/blob/main/packages/docmanager-extension/src/index.ts)
with a wrapper to display the policy reminder prompt before downloading a
file using the menu bar.

### `aou-jupyterlab:docmanager-open-browser-tab`

Replaces the [default `docmanager-extension:open-browser-tab`
plugin](https://github.com/jupyterlab/jupyterlab/blob/main/packages/docmanager-extension/src/index.ts)
with a wrapper to display the policy reminder prompt before opening a file in a
new browser tab using the command palette.

### `aou-jupyterlab:notebook-export`

Replaces the [default `notebook-extension:export`
plugin](https://github.com/jupyterlab/jupyterlab/blob/4.4.x/packages/notebook-extension/src/index.ts)
with a wrapper to display the policy reminder prompt before exporting a
notebook.

### `aou-jupyterlab:upload-intercept`

This plugin injects a upload policy reminder prompt into the filebrowser's
upload action. Since upload is not provided as a separate plugin, this is
accomplished by mutating the filebrowser's upload function.

## Requirements

- JupyterLab >= 4.0.0

## Install

To install the extension, execute:

```bash
pip install aou_jupyterlab
```

## Uninstall

To remove the extension, execute:

```bash
pip uninstall aou_jupyterlab
```

## Contributing

### Development install

Note: You will need NodeJS to build the extension package.

The `jlpm` command is JupyterLab's pinned version of
[yarn](https://yarnpkg.com/) that is installed with JupyterLab. You may use
`yarn` or `npm` in lieu of `jlpm` below.

```bash
# Clone the repo to your local environment
# Change directory to the aou_jupyterlab directory
# Install package in development mode
pip install -e "."
# Link your development version of the extension with JupyterLab
jupyter labextension develop . --overwrite
# Rebuild extension Typescript source after making changes
jlpm build
```

You can watch the source directory and run JupyterLab at the same time in different terminals to watch for changes in the extension's source and automatically rebuild the extension.

```bash
# Watch the source directory in one terminal, automatically rebuilding when needed
jlpm watch
# Run JupyterLab in another terminal
jupyter lab
```

With the watch command running, every saved change will immediately be built locally and available in your running JupyterLab. Refresh JupyterLab to load the change in your browser (you may need to wait several seconds for the extension to be rebuilt).

By default, the `jlpm build` command generates the source maps for this extension to make it easier to debug using the browser dev tools. To also generate source maps for the JupyterLab core extensions, you can run the following command:

```bash
jupyter lab build --minimize=False
```

### Development uninstall

```bash
pip uninstall aou_jupyterlab
```

In development mode, you will also need to remove the symlink created by `jupyter labextension develop`
command. To find its location, you can run `jupyter labextension list` to figure out where the `labextensions`
folder is located. Then you can remove the symlink named `aou-jupyterlab` within that folder.
