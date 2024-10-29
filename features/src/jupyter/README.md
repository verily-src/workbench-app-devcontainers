
# Jupyter Server (jupyter)

Installs the provided version of Python, as well as PIPX, and other common Python utilities.  JupyterLab is conditionally installed with the python feature. Note: May require source code compilation.

## Example Usage

```json
"features": {
    "./.devcontainer/features/src/jupyter:1": {}
}
```

## Options

| Options Id | Description | Type | Default Value |
|-----|-----|-----|-----|
| version | Select a Python version to install. | string | os-provided |
| installTools | Flag indicating whether or not to install the tools specified via the 'toolsToInstall' option. Default is 'true'. | boolean | true |
| user | User to install python and jupyter lab as | string | automatic |
| cloudPlatform | Cloud platform context to determine cloud speficic tools to install | string | gcp |
| toolsToInstall | Comma-separated list of tools to install when 'installTools' is true. Defaults to a set of common Python tools like pylint. | string | virtualenv |
| optimize | Optimize Python for performance when compiled (slow) | boolean | false |
| enableShared | Enable building a shared Python library | boolean | false |
| installPath | The path where python will be installed. | string | /usr/local/python |
| installJupyterlab | Install JupyterLab, a web-based interactive development environment for notebooks | boolean | false |
| configureJupyterlabAllowOrigin | Configure JupyterLab to accept HTTP requests from the specified origin | string | - |
| httpProxy | Connect to GPG keyservers using a proxy for fetching source code signatures by configuring this option | string | - |



## OS Support

This Feature should work on recent versions of Debian/Ubuntu, RedHat Enterprise Linux, Fedora, Alma, and RockyLinux distributions with the apt, yum, dnf, or microdnf package manager installed.

`bash` is required to execute the `install.sh` script.


---

_Note: This file was auto-generated from the [devcontainer-feature.json](devcontainer-feature.json).  Add additional notes to a `NOTES.md`._
