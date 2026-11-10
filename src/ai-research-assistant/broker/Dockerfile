# The sandbox-broker (the agent-sandbox README, "Admin-locked mode"): the one container that reaches the
# OpenShell gateway. It runs agent-sandbox for the app over SSH, with this image's policy
# files, so a workspace user can start, use and reset the sandbox but not change what it may
# reach. Built from the app folder, where the platform has put the features under
# .devcontainer/features/ (startupscript/butane/050-parse-devcontainer.sh), so it carries the
# same feature files as the app image: the policy compiler, the sandbox commands in the broker
# role (which adds sshd), and the harness files (the config hook runs here).
FROM debian:bookworm-slim@sha256:7ff6ba31527b9e336162fa061746c366c4b2032f4d2cff2078bea43f78efe3f8

COPY .devcontainer/features/ai-policy /tmp/features/ai-policy
COPY .devcontainer/features/agent-sandbox /tmp/features/agent-sandbox
COPY .devcontainer/features/opencode-harness /tmp/features/opencode-harness
RUN bash /tmp/features/ai-policy/install.sh \
    && USERNAME=abc USERHOMEDIR=/config ROLE=broker bash /tmp/features/agent-sandbox/install.sh \
    && USERNAME=abc USERHOMEDIR=/config INSTALLLAUNCHER=false bash /tmp/features/opencode-harness/install.sh \
    && rm -rf /tmp/features

ENV OPENSHELL_TELEMETRY_ENABLED=false NO_COLOR=1
EXPOSE 22
ENTRYPOINT ["/opt/agent-sandbox/broker/entrypoint.sh"]
