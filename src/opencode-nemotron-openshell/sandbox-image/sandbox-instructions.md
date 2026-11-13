# You are running in an NVIDIA OpenShell sandbox

- Your workspace is `/sandbox/work`. Only `/sandbox` and `/tmp` are writable.
- There is no internet access. Package installs (`pip`, `npm`, `apt`) and web
  requests are blocked by policy, and blocked attempts are logged. The only
  network service you can reach is the local model you are running on.
- You have no Workbench, Google Cloud or other credentials, and no Workbench
  tools. Work with the files in your workspace.
- If a task needs a destination that the policy blocks, stop and tell the user
  which host and why. The user can approve a rule; do not try to work around
  the block.
- Files the user wants to keep must be downloaded from the sandbox by the user
  (`opencode-sandbox download`). Say which files you changed.
