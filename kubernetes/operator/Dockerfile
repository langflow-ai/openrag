FROM golang:1.26.5 AS builder
ARG TARGETOS
ARG TARGETARCH

WORKDIR /workspace

COPY go.mod go.sum ./
RUN go mod download

COPY api/ api/
COPY cmd/ cmd/
COPY internal/ internal/

RUN CGO_ENABLED=0 GOOS=${TARGETOS:-linux} GOARCH=${TARGETARCH} go build -a -o manager cmd/main.go

FROM registry.access.redhat.com/ubi10/ubi-minimal:latest

# Install necessary CA certificates for HTTPS connections
RUN microdnf install -y ca-certificates && \
    microdnf clean all && \
    rm -rf /var/cache/yum

# CWE-426 fix: explicitly set PATH so system-owned directories are always resolved
# first. App venv dirs are appended last so they cannot shadow system binaries.
# Matches the ordering used by the upstream image but with system dirs promoted
# to the front.
ENV PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:/opt/app-root/bin:/opt/app-root/src/bin:/opt/app-root/src/.local/bin

WORKDIR /
COPY --from=builder /workspace/manager .

# Use non-root user (default ubi-minimal user)
USER 65532:65532

ENTRYPOINT ["/manager"]
