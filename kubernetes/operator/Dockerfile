FROM golang:1.26.0 AS builder
ARG TARGETOS
ARG TARGETARCH

WORKDIR /workspace

COPY go.mod go.sum ./
RUN go mod download

COPY api/ api/
COPY cmd/ cmd/
COPY internal/ internal/

RUN CGO_ENABLED=0 GOOS=${TARGETOS:-linux} GOARCH=${TARGETARCH} go build -a -o manager cmd/main.go

FROM registry.access.redhat.com/ubi9/ubi-minimal:latest

# Install necessary CA certificates for HTTPS connections
RUN microdnf install -y ca-certificates && \
    microdnf clean all && \
    rm -rf /var/cache/yum

WORKDIR /
COPY --from=builder /workspace/manager .

# Use non-root user (default ubi-minimal user)
USER 65532:65532

ENTRYPOINT ["/manager"]
