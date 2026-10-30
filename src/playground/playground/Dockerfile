FROM golang:1.25-alpine AS build

WORKDIR /app

COPY go.mod go.sum ./
RUN go mod download
COPY . .
 
RUN go build -o /playground .

FROM node@sha256:06d7adf3e0ef61a13f1d28682726366f97a15aa1888c934d3ecec86c33918b53

# Install Docker CLI, docker-compose, buildx, ttyd, bash, and devcontainer CLI
RUN apk add --no-cache docker-cli docker-cli-compose docker-cli-buildx ttyd bash && \
    npm install -g @devcontainers/cli

RUN addgroup -S playground -g 1001 && adduser -S playground -u 1001 -G playground

WORKDIR /workspace
COPY --chown=playground:playground --from=build /playground /playground

# Create startup script to run ttyd in background and playground in foreground
RUN cat > /start.sh <<'EOF'
#!/bin/sh
ttyd --writable --port 7681 --base-path /_shell bash &
exec /playground
EOF

RUN chmod +x /start.sh

USER playground

EXPOSE 8080 7681

CMD [ "/start.sh" ]
