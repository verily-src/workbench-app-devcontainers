FROM golang:1.25-alpine AS build

WORKDIR /app

COPY go.mod go.sum ./
RUN go mod download
COPY . .
 
RUN go build -o /playground .

FROM alpine:latest

# Install Node.js, npm, Docker CLI, docker-compose, and devcontainer CLI
RUN apk add --no-cache nodejs npm docker-cli docker-cli-compose && \
    npm install -g @devcontainers/cli

RUN addgroup -S playground -g 1001 && adduser -S playground -u 1001 -G playground

WORKDIR /home/playground/app
COPY --chown=playground:playground --from=build /playground /playground

USER playground

EXPOSE 8080

CMD [ "/playground" ]
