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
    apt-get install -y docker-ce-cli docker-compose-plugin && \
    rm -rf /var/lib/apt/lists/*

# Install kubectl
RUN curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl" && \
    install -o root -g root -m 0755 kubectl /usr/local/bin/kubectl && \
    rm kubectl

# Install minikube
RUN curl -LO https://storage.googleapis.com/minikube/releases/latest/minikube-linux-amd64 && \
    install minikube-linux-amd64 /usr/local/bin/minikube && \
    rm minikube-linux-amd64

# Install helm
RUN curl https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash

# Install skaffold
RUN curl -Lo skaffold https://storage.googleapis.com/skaffold/releases/latest/skaffold-linux-amd64 && \
    install skaffold /usr/local/bin/ && \
    rm skaffold

# Install Go (version 1.23.5)
RUN wget https://go.dev/dl/go1.23.5.linux-amd64.tar.gz && \
    tar -C /usr/local -xzf go1.23.5.linux-amd64.tar.gz && \
    rm go1.23.5.linux-amd64.tar.gz

# Install gh (GitHub CLI)
RUN curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg | dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg && \
    chmod go+r /usr/share/keyrings/githubcli-archive-keyring.gpg && \
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" | tee /etc/apt/sources.list.d/github-cli.list > /dev/null && \
    apt-get update && \
    apt-get install -y gh && \
    rm -rf /var/lib/apt/lists/*

# Install uv (Python package manager)
RUN curl -LsSf https://astral.sh/uv/install.sh | sh && \
    mv $HOME/.local/bin/uv /usr/local/bin/ && \
    mv $HOME/.local/bin/uvx /usr/local/bin/

# Set up environment variables
ENV PATH="/usr/local/go/bin:${PATH}"
ENV GOPATH="/config/go"
ENV GOPRIVATE="github.com/verily-src/*"

# Configure git to use SSH instead of HTTPS for GitHub
RUN git config --system url."git@github.com:".insteadOf "https://github.com/"

WORKDIR /config
