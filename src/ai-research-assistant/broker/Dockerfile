# The sandbox-broker (the agent-sandbox README, "Admin-locked mode"): the one container that reaches the
# OpenShell gateway. It runs agent-sandbox for the app over SSH, with this image's policy
# files, so a workspace user can start, use and reset the sandbox but not change what it may
# reach. Built from the app folder, where the platform has put the features under
# .devcontainer/features/ (startupscript/butane/050-parse-devcontainer.sh), so it carries the
# same feature files as the app image: the policy compiler, the sandbox commands in the broker
# role (which adds sshd), and the harness files (the config hook runs here).
FROM debian@sha256:d7e12182ce18b85b93007c1dedf31f2d29e01ccf3182cc4017c709b6259bc132

COPY .devcontainer/features/ai-policy /tmp/features/ai-policy
COPY .devcontainer/features/agent-sandbox /tmp/features/agent-sandbox
COPY .devcontainer/features/opencode-harness /tmp/features/opencode-harness
# Only the designer's catalog (its sandbox/ folder and installer), not its code: the designer
# runs in the app.
COPY .devcontainer/features/cohort-designer/install.sh /tmp/features/cohort-designer/install.sh
COPY .devcontainer/features/cohort-designer/sandbox /tmp/features/cohort-designer/sandbox
# The same for the Kumo forecast server: its catalog, not the model.
COPY .devcontainer/features/kumo-forecast/install.sh /tmp/features/kumo-forecast/install.sh
COPY .devcontainer/features/kumo-forecast/sandbox /tmp/features/kumo-forecast/sandbox
RUN bash /tmp/features/ai-policy/install.sh \
    && USERNAME=abc USERHOMEDIR=/config ROLE=broker bash /tmp/features/agent-sandbox/install.sh \
    && USERNAME=abc USERHOMEDIR=/config INSTALLLAUNCHER=false bash /tmp/features/opencode-harness/install.sh \
    && ROLE=broker bash /tmp/features/cohort-designer/install.sh \
    && ROLE=broker bash /tmp/features/kumo-forecast/install.sh \
    && rm -rf /tmp/features

ENV OPENSHELL_TELEMETRY_ENABLED=false NO_COLOR=1
EXPOSE 22
ENTRYPOINT ["/opt/agent-sandbox/broker/entrypoint.sh"]
