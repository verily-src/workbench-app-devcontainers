FROM golang:1.23-alpine AS builder

RUN apk add --no-cache git ca-certificates

WORKDIR /build
COPY go.mod go.sum ./
RUN go mod download

COPY . .
RUN CGO_ENABLED=0 GOOS=linux go build -o /program-generator .

# ---

FROM alpine:3.21

RUN apk add --no-cache ca-certificates

COPY --from=builder /program-generator /usr/local/bin/program-generator

EXPOSE 8080
CMD ["program-generator"]
