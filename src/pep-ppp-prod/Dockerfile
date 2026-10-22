FROM gitlabregistry.pep.cs.ru.nl/pep-public/core/ppp-prod

# Install Node.js system-wide so devcontainer features (e.g. claude-code) can find it
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl \
    && curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*
