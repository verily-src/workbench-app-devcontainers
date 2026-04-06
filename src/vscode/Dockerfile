FROM lscr.io/linuxserver/code-server@sha256:629232bdd99640dd3d514a40c740a9d42dcb808a844005821b2f4be6e6a8b66e

# Gemini 2.77.0 crashes the extension host on VS Code 1.100.x with:
#   "e.longerThan(...).toArray is not a function"
# This takes down the terminal and all extensions. Pinned to 2.75.0 until Google
# ships a fix. Re-test and bump when a newer version is available.
ARG GEMINI_CODE_ASSIST_VERSION=2.75.0
ARG CLAUDE_CODE_EXTENSION_VERSION=2.1.90
ARG TARGETARCH=amd64

# Extensions are installed as user 'abc' (the linuxserver runtime user) so they
# are readable/writable at runtime without permission errors.
RUN mkdir -p /config/extensions /config/.local/share/code-server/User \
    && chown -R abc:abc /config

USER abc
ENV HOME=/config

# Disable extension auto-update so pinned versions are not overwritten at runtime.
# extensions.supportNodeGlobalNavigator: VS Code 1.101+ treats `navigator` as a Node.js
# global; extensions compiled against older bundlers declare their own `navigator` and
# crash the extension host with "PendingMigrationError" if this flag is not set.
RUN echo '{"extensions.autoUpdate": false, "extensions.autoCheckUpdates": false, "extensions.supportNodeGlobalNavigator": true}' \
    > /config/.local/share/code-server/User/settings.json

# Claude Code ships platform-specific VSIXs. Open VSX's /latest endpoint resolves
# to a single platform (currently alpine-arm64), which breaks on linux/amd64.
# Always download the explicit platform build.
RUN case "${TARGETARCH}" in \
      amd64) OVSX_PLATFORM=linux-x64 ;; \
      arm64) OVSX_PLATFORM=linux-arm64 ;; \
      *) echo "unsupported TARGETARCH=${TARGETARCH}" >&2; exit 1 ;; \
    esac \
    && curl -fL --compressed -o /tmp/geminicodeassist.vsix \
      "https://open-vsx.org/api/Google/geminicodeassist/${GEMINI_CODE_ASSIST_VERSION}/file/Google.geminicodeassist-${GEMINI_CODE_ASSIST_VERSION}.vsix" \
    && curl -fL --compressed -o /tmp/claudecode.vsix \
      "https://open-vsx.org/api/Anthropic/claude-code/${OVSX_PLATFORM}/${CLAUDE_CODE_EXTENSION_VERSION}/file/Anthropic.claude-code-${CLAUDE_CODE_EXTENSION_VERSION}@${OVSX_PLATFORM}.vsix" \
    && /app/code-server/bin/code-server --extensions-dir /config/extensions --install-extension /tmp/geminicodeassist.vsix \
    && /app/code-server/bin/code-server --extensions-dir /config/extensions --install-extension /tmp/claudecode.vsix \
    && rm /tmp/geminicodeassist.vsix /tmp/claudecode.vsix

USER root

WORKDIR /config
