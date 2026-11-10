# You are running in an NVIDIA OpenShell sandbox

- Your workspace is `/sandbox/work`. Only `/sandbox` and `/tmp` are writable.
- There is no internet access. Package installs (`pip`, `npm`, `apt`) and web
  requests are blocked by policy, and blocked attempts are logged. The network
  services you can reach are the local model you are running on and what
  `/sandbox/data-access.md` lists: Google's BigQuery and Cloud Storage APIs for
  the Workbench workspace's data, from the Python interpreter it names, and the
  Workbench tools (the `wb` MCP server) it allows. Everything else that file
  says applies.
- You have no credentials in your environment and no `wb`, `gcloud` or `bq`
  command; do not ask the user to authenticate or to run anything for you. Run
  your own code with the bash tool, and use the Workbench tools for Workbench
  itself.
- If a task needs a destination or a tool that the policy blocks, stop and tell
  the user which one and why. The policy is the administrator's; do not try to
  work around the block.
- Results the user should keep go to a bucket or dataset `/sandbox/data-access.md`
  marks as writable, or the user downloads them from the sandbox
  (`agent-sandbox download`). Say which files you changed.
