# Bedrock and cohort-agent plan

Status: implementation and deployment plan, 2026-10-20. Direct Bedrock Converse and the local cohort specialist are implemented and tested locally. AgentCore remains a plan. No AWS resources were created and no AWS invocation was verified.

## Current app boundary

`app/agent.py` owns the chat loop and builds tools over the active in-memory dataset and UI state. `app/providers.py` runs OpenAI-compatible providers; Anthropic uses its SDK path in `agent.py`. The tools validate filters against the loaded dataset, then return counts, aggregates, previews, and UI changes. `app/mcp_server.py` exposes read/query tools and OMOP-specific concept search, cohort count, and cohort open tools. `app/db.py` resolves Aurora credentials through `wb resource resolve`; `wb workspace configure-aws` creates per-resource profiles for AWS CLI and DuckDB/S3 access.

These Workbench credentials are resource-scoped. The code does not establish that they authorize Amazon Bedrock or AgentCore API calls. Treat model invocation and AgentCore permissions as a separate AWS identity setup, and do not copy a per-resource S3 profile into a general AWS service credential path without confirmation from Workbench/IAM owners.

## Recommended shape

1. Add Bedrock as a Studio-side model provider. Use the AWS SDK `bedrock-runtime` Converse API for consistent messages and tool use. Keep the existing server-side tool execution and validation in `agent.py`; add provider-specific dispatch and settings for Region and model ID. The Studio backend makes signed AWS requests through an explicitly approved workload identity.
2. Add a specialized cohort-building workflow on those validated backend tools. For OMOP, guide the user through concept search, inclusion/exclusion criteria, descendant options, observation period and demographics; show incremental counts and attrition; then open the cohort into Studio. Reuse the OMOP operations already exposed by MCP as a starting contract. Keep count/search/preview separate from the final UI mutation, and show the cohort specification and count before applying it.
3. Evaluate AgentCore Runtime as a separately hosted agent only after the identity and network path are known. Studio would call `InvokeAgentRuntime` from FastAPI. The Runtime must call tools through a reachable, authenticated endpoint or a controlled Gateway target. Do not assume it can call Studio's localhost MCP endpoint, inherit the Studio process's Workbench CLI session, or see its in-memory datasets. The current MCP note says Workbench's public app proxy needs browser cookies; its suitability for a service-to-service caller is unverified.

This order keeps the cohort workflow usable within the current app boundary while AgentCore remains a deployment choice. AgentCore is a runtime and integration layer; Bedrock Converse is the model API. They solve different parts of the design.

## Workbench workflow and app operations

The specialist should first support read-only operational tools. Studio already lists workflow jobs and the workflow registry (`app/workflows.py`, `GET /api/workflows` and `/api/workflows/registry`), and exposes submission as a separate `POST /api/workflows/submit`. The installed `wb` CLI also reports these app commands: `list`, `describe`, and `logs` are read-only; `start`, `stop`, and `update` change app state. Workflow jobs support `list` and `describe`; `cancel` changes job state. The CLI help confirms `wb app list` can scope by workspace/config/owner, `wb app describe` and `wb app logs` require an app ID, and logs accept a time window and filters.

Implementation status: `app/cohort_agent.py` has local callables for concept search, aggregate cohort count, validated cohort proposal, workflow job listing, and Workbench app listing. `app/workbench_apps.py` uses the fixed read-only `wb app list --format JSON` command and returns selected operational fields; it derives the app ID from `/app/<UUID>/` in `proxyUrl` when the CLI response has no ID field. The backend endpoint `POST /api/omop/{resource_id}/cohort/agent` and the OMOP builder UI are now wired: the agent returns a proposal for the user to review and apply, then the existing UI Count/Open actions run. Endpoint regression tests cover spec errors, missing provider configuration, and telemetry. The full OMOP UI flow and MCP HTTP flow pass against a real local PostgreSQL fixture. Real Aurora behavior remains unverified. No workflow/app mutation tool exists. AgentCore remains a research option; no Runtime was provisioned or invoked.

Recommended first tools:

- `list_workflow_jobs` / `describe_workflow_job`: expose status, run ID, workflow, owner, times, output bucket and status message. Add bounded task details if the user asks; do not dump unbounded logs.
- `list_workbench_apps` / `describe_workbench_app`: require an explicit workspace scope or use only the current workspace; report app ID, config, owner, and status when returned by the CLI.
- `get_workbench_app_logs`: require an exact app ID and bounded time range; apply a small result cap and redact secrets/tokens before returning log text to a model.

Keep mutations in separate tools with explicit, typed targets and arguments:

- `submit_workflow`: exact workflow ID, output bucket resource ID, and any batch-input bucket/path and mappings. The user must ask to submit/run the workflow. Show the target and input/output locations before execution; return the run ID and resulting status.
- `cancel_workflow`: exact workflow job/run ID. Require a direct user instruction to cancel that run.
- `start_app`, `stop_app`, `update_app`: exact Workbench app resource ID (plus workspace where required). Require a direct user instruction naming the requested operation. A question or mention such as “is app X running?” or “the workflow is stuck” authorizes inspection only. Never infer start/stop/update intent from context.

Before each mutation, check that the target ID is present and unambiguous, the caller has access, and the requested operation matches the user's explicit intent. For ambiguous targets or incomplete required parameters, ask for the missing detail. Return operation status, resource/run ID, and any CLI error. Treat timeout or lost response as “outcome unknown”; inspect status before retrying to avoid duplicate submission or repeated state changes. Keep read-only tool permissions separate from mutation permissions in the application and IAM design. Current app start/stop/update/cancel routes are not implemented in Studio; this section is a design boundary, not a claim that the agent can perform them now.

## Configuration and access needed

### Browser isolation

The isolated deployment uses `src/virtual-browser-cohort-studio`: Selkies on port
3000 is the proxy target; Studio has no published port and runs only on
`backend-network`. Keep cohort search/count/import and provider requests in the
backend. Chromium needs access only to `http://application-server:8080`.

An external AgentCore Runtime cannot use the streamed browser URL as an MCP
endpoint. Establish a separately authenticated private service path before
enabling remote tools. Do not publish Studio port 8080 or widen the browser URL
allowlist as a shortcut. Local agents can call Studio from the app container or
the private Compose network. Workflow and app links outside Studio will be
blocked by the kiosk policy; use backend status tools and show their results in
Studio. Verify these flows in the deployed sidecar, including reconnect after
backend updates, before marking the isolated release complete.

For direct Bedrock calls from Studio, define an approved AWS credential chain for the app process and a Region, such as `AWS_REGION`/`AWS_DEFAULT_REGION`, plus a Bedrock model ID or inference profile. The caller needs `bedrock:InvokeModel` for Converse, and `bedrock:InvokeModelWithResponseStream` only if streaming is added. The account and Region must allow the selected model/inference profile. Prefer a role with only the selected model resources. AWS documents the Converse API and permissions in [Inference using Converse API](https://docs.aws.amazon.com/bedrock/latest/userguide/conversation-inference.html) and [Prerequisites for running model inference](https://docs.aws.amazon.com/bedrock/latest/userguide/inference-prereq.html).

For an AgentCore Runtime deployment, configure its Runtime ARN and Region in Studio, then authorize Studio's caller identity for `bedrock-agentcore:InvokeAgentRuntime` on that runtime. Separately, configure a Runtime execution role for the agent's own calls, including narrowly scoped `bedrock:InvokeModel` if it uses Bedrock. If Runtime uses VPC access to reach private tools or data, an administrator must provide a VPC, supported subnets, security groups, and required service-linked role permissions. AWS notes that public subnets alone do not provide Runtime internet access; private subnets need NAT for internet egress, or appropriate VPC endpoints for supported AWS services. See [IAM Permissions for AgentCore Runtime](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-permissions.html), [Runtime invocation](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-get-started-cli.html), and [Configure AgentCore Runtime and tools for VPC](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/agentcore-vpc.html).

AgentCore can use IAM/SigV4 or JWT/OAuth inbound authorization. For this app's backend-to-backend call, IAM invocation is the first option to evaluate; OAuth requires a real user-token flow and HTTP invocation. Bind Runtime session IDs to the authenticated Workbench user if sessions can retain state. See [AgentCore inbound and outbound auth](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-oauth.html) and [Runtime security and session isolation](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-instances-security.html).

## Phases and checks

- **Phase 0 — access spike:** Ask Workbench/IAM owners which app workload identity, if any, may invoke Bedrock and AgentCore. Verify Region, model access, account policy, egress or VPC endpoints, and service-to-service access to the tool endpoint. Do not provision AWS resources in this repo task.
- **Phase 1 — Bedrock provider:** Add Converse tool-call handling and provider settings; keep API keys and AWS credentials server-side. Verify tool calls, malformed arguments, permission failures, and telemetry with a permitted test identity and model.
- **Phase 2 — cohort specialist:** Define a versioned cohort spec and deterministic validation. Add concept search, count/attrition, preview, and apply actions. Verify against OMOP fixtures and a permitted real Aurora CDM when available; keep generated SQL server-side and parameterized.
- **Phase 3 — AgentCore decision:** Prototype Runtime only if it adds needed managed runtime, auth, or observability. Verify private/authenticated reachability to tools, per-user session isolation, streaming/timeouts, and cost/latency. If these conditions fail, keep the agent in the Studio backend and use Bedrock directly.
- **Phase 4 — Workbench operations:** Ship bounded read-only status/list/log tools first. Add each mutation as a separate, least-privilege tool with explicit target IDs, intent checks, operation result reporting, and retry-safe handling. Start with workflow submission only after the read-only flow is reliable; add cancel and app start/stop/update only when their permissions and user experience are defined.

## Open questions

- Does this Workbench app receive any AWS identity that is allowed to call Bedrock or AgentCore? Does `wb workspace configure-aws` ever authorize those APIs, or does it only provide resource-scoped S3 profiles here?
- Which AWS account and Region, approved model IDs, inference profile, budget, and data-handling policy apply to cohort prompts and results?
- Can AgentCore Runtime reach an authenticated Studio tool endpoint over private networking? Is a Gateway or a separate service needed? The current localhost MCP endpoint is not an established remote integration.
- Which user identity is available at the app backend, and how should Runtime sessions and audit records bind to it?
- Which cohort-building scope should ship first: OMOP CDM only, or also generic loaded datasets?
- Which Workbench CLI version and app state fields are stable on the target VM? Can app logs be read without exporting to a bucket, and what log redaction rules apply?
- Which roles may submit/cancel workflow jobs or start/stop/update apps, and should each mutation require a separate in-product review step?

## Official AWS references

- [Bedrock Converse API](https://docs.aws.amazon.com/bedrock/latest/userguide/conversation-inference.html)
- [Bedrock model invocation permissions](https://docs.aws.amazon.com/bedrock/latest/userguide/inference-prereq.html)
- [AgentCore Runtime IAM permissions and execution role](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-permissions.html)
- [AgentCore Runtime invocation](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-get-started-cli.html)
- [AgentCore Runtime VPC access and networking](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/agentcore-vpc.html)
- [AgentCore authentication](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-oauth.html)
- [AgentCore session isolation](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-instances-security.html)
