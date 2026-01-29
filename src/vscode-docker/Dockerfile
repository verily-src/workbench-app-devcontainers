# VS Code Docker Development Container
# Based on lscr.io/linuxserver/code-server with Docker, kubectl, minikube, skaffold, helm, and Go pre-installed

FROM lscr.io/linuxserver/code-server:4.100.3

# Install system dependencies
RUN apt-get update && apt-get install -y \
    curl \
    wget \
    git \
    gnupg \
    lsb-release \
    ca-certificates \
    apt-transport-https \
    software-properties-common \
    build-essential \
    python3-pip \
    socat \
    && rm -rf /var/lib/apt/lists/*

# Install Docker CLI
RUN install -m 0755 -d /etc/apt/keyrings && \
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg && \
    chmod a+r /etc/apt/keyrings/docker.gpg && \
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
    $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
    tee /etc/apt/sources.list.d/docker.list > /dev/null && \
    apt-get update && \
    apt-get install -y docker-ce-cli=5:29.2.0-1~ubuntu.24.04~noble docker-compose-plugin=5.0.2-1~ubuntu.24.04~noble && \
    rm -rf /var/lib/apt/lists/*

# Install kubectl (version 1.35.0)
RUN curl -LO "https://dl.k8s.io/release/v1.35.0/bin/linux/amd64/kubectl" && \
    install -o root -g root -m 0755 kubectl /usr/local/bin/kubectl && \
    rm kubectl

# Install minikube (version 1.37.0)
RUN curl -LO https://storage.googleapis.com/minikube/releases/v1.37.0/minikube-linux-amd64 && \
    install minikube-linux-amd64 /usr/local/bin/minikube && \
    rm minikube-linux-amd64

# Install helm (version 3.20.0)
RUN curl -LO https://get.helm.sh/helm-v3.20.0-linux-amd64.tar.gz && \
    tar -zxvf helm-v3.20.0-linux-amd64.tar.gz && \
    mv linux-amd64/helm /usr/local/bin/helm && \
    rm -rf linux-amd64 helm-v3.20.0-linux-amd64.tar.gz

# Install skaffold (version 2.17.1)
RUN curl -Lo skaffold https://storage.googleapis.com/skaffold/releases/v2.17.1/skaffold-linux-amd64 && \
    install skaffold /usr/local/bin/ && \
    rm skaffold

# Install Go (version 1.23.5)
RUN wget https://go.dev/dl/go1.23.5.linux-amd64.tar.gz && \
    tar -C /usr/local -xzf go1.23.5.linux-amd64.tar.gz && \
    rm go1.23.5.linux-amd64.tar.gz

# Install gh (GitHub CLI version 2.86.0)
RUN curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg | dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg && \
    chmod go+r /usr/share/keyrings/githubcli-archive-keyring.gpg && \
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" | tee /etc/apt/sources.list.d/github-cli.list > /dev/null && \
    apt-get update && \
    apt-get install -y gh=2.86.0 && \
    rm -rf /var/lib/apt/lists/*

# Install uv (Python package manager version 0.9.27)
RUN curl -LsSf https://astral.sh/uv/0.9.27/install.sh | sh && \
    mv $HOME/.local/bin/uv /usr/local/bin/ && \
    mv $HOME/.local/bin/uvx /usr/local/bin/

# Set up environment variables
ENV PATH="/usr/local/go/bin:${PATH}"
ENV GOPATH="/config/go"
ENV GOPRIVATE="github.com/verily-src/*"
ENV SUDO_PASSWORD="pwd"

# Copy docker group setup script
COPY docker-setup.sh /etc/cont-init.d/50-docker-setup
RUN chmod +x /etc/cont-init.d/50-docker-setup

# Configure git to use SSH instead of HTTPS for GitHub
RUN git config --system url."git@github.com:".insteadOf "https://github.com/"

WORKDIR /config
