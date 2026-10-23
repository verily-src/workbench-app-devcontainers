# AWS Bedrock and AgentCore access check

Checked 2026-10-23 in `us-east-1`, account `535002863113`, using the
`vwb-Developer-535002863113` profile. This was a read-only access check. No
model invocation, runtime creation, or IAM change was made.

## Result

The Cohort Studio application container does not have direct Bedrock model
catalog, inference-profile, or AgentCore runtime-list access. Its IAM policy
simulation also returns `implicitDeny` for Bedrock model invocation and
AgentCore runtime invocation. No model invocation was attempted, so actual
inference permission and billing were not tested.

| Principal / action | Observed result |
|---|---|
| Developer profile `sts:GetCallerIdentity` | Account `535002863113`; assumed role `AWSReservedSSO_vwb-Developer_c317f16f3063ea40` |
| Developer `bedrock:ListFoundationModels` | `AccessDeniedException`; identity policy has no allow |
| Developer `bedrock:ListInferenceProfiles` | `AccessDeniedException`; identity policy has no allow |
| Developer `bedrock-agentcore:ListAgentRuntimes` | `AccessDeniedException`; identity policy has no allow |
| App container `sts:GetCallerIdentity` | `arn:aws:sts::535002863113:assumed-role/v0SaasDevAppInstance/i-0e9d71494595f205c` |
| App container `bedrock:ListFoundationModels` | `AccessDeniedException`; identity policy has no allow |
| App container `bedrock:ListInferenceProfiles` | `AccessDeniedException`; identity policy has no allow |
| App container `bedrock-agentcore:ListAgentRuntimes` | `AccessDeniedException`; identity policy has no allow |
| App role simulation: `bedrock:InvokeModel`, `bedrock:InvokeModelWithResponseStream`, `bedrock-agentcore:InvokeAgentRuntime` | `implicitDeny`; no missing context values in the simulation |

The app EC2 instance was running and used instance profile
`v0SaasDevAppInstanceInstanceProfile`, which contains role
`v0SaasDevAppInstance`. Its attached policies are `v0SaasDevAppInstanceSelfActions`,
`v0SaasDevAppInstanceCloudWatchLogs`, `v0SaasDevAppInstanceCodeArtifactReadOnly`,
and `AmazonSSMManagedInstanceCore`. Its inline policies cover ECR reads and an
`sts:AssumeRole` grant to `ws-perim-match`; none of the inspected app-role
policies grant Bedrock or AgentCore actions. The role has no permissions
boundary.

The `ws-perim-match` role trust allows account principals to assume it. Its
attached policy is `AmazonS3ReadOnlyAccess`; its inline policy grants KMS
decrypt/describe/data-key actions for one key. The inspected policies do not
grant Bedrock or AgentCore actions. No role assumption was performed.

## Evidence commands

Developer-profile calls:

```sh
aws sts get-caller-identity --profile vwb-Developer-535002863113 --region us-east-1
aws bedrock list-foundation-models --profile vwb-Developer-535002863113 --region us-east-1
aws bedrock list-inference-profiles --profile vwb-Developer-535002863113 --region us-east-1
aws bedrock-agentcore-control list-agent-runtimes --profile vwb-Developer-535002863113 --region us-east-1
```

The last three calls returned `AccessDeniedException`. The app identity and
the same three service-list calls were run in `application-server` through
SSM Run Command `23c35a21-19e9-4121-b582-4ba665a5c46a`. They returned the app
role identity above and the same access-denied results.

IAM simulation used the app role ARN and the observed instance context values
for `ec2:InstanceID`, `aws:userid`, `aws:TagKeys`, and `sts:AWSServiceName`.
The six checked actions were `bedrock:ListFoundationModels`,
`bedrock:ListInferenceProfiles`, `bedrock:InvokeModel`,
`bedrock:InvokeModelWithResponseStream`,
`bedrock-agentcore:ListAgentRuntimes`, and
`bedrock-agentcore:InvokeAgentRuntime`. Each returned `implicitDeny` with an
empty `MissingContextValues` list.

## Enablement path

1. Have the AWS administrator grant the application a dedicated, scoped role
   for the approved Bedrock model or inference profile. The existing Converse
   adapter needs `bedrock:InvokeModel`; streaming also needs
   `bedrock:InvokeModelWithResponseStream`. Avoid broad grants on the shared
   app instance role. Configure the approved model and region, then run a small
   connection test from the app. Model availability and billing remain untested.
2. AgentCore is separate: deploy an agent runtime with its own execution role,
   then grant Studio `bedrock-agentcore:InvokeAgentRuntime` on that runtime.
   Deployment permissions, including scoped `iam:PassRole`, belong to the
   deployment identity, not the ordinary Studio caller. Integration is not built.
3. Bedrock can be enabled first; AgentCore is not required for the current
   cohort assistant. No IAM changes were made during this audit.

References: [Bedrock inference permissions](https://docs.aws.amazon.com/bedrock/latest/userguide/inference-prereq.html)
and [AgentCore runtime permissions](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-permissions.html).

## Verification limits

This verifies the identity and direct IAM permissions of the current app
container and the named developer profile at the time of the check. It does
not prove model availability, inference acceptance, account-level model
agreements, network reachability to inference endpoints, or AgentCore runtime
behavior. Invoke APIs were not called. No Secrets Manager values or credential
material were read.

## Browser isolation and API calls

The browser sidecar runs the browser; it is not the cohort agent or an AI
gateway. Studio's backend calls the regional Bedrock Runtime API with IAM
credentials. No Bedrock key or direct AWS access is required in the browser.
A later AgentCore integration would call the deployed agent runtime API from
the same backend. Browser isolation does not grant AWS IAM permissions or
configure service networking. End-to-end operation in the isolated Workbench
app remains unverified. Bedrock can use a private VPC endpoint where required:
[AWS PrivateLink documentation](https://docs.aws.amazon.com/bedrock/latest/userguide/vpc-interface-endpoints.html).
