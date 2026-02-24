########################################
# Stage 1: Upstream OpenSearch with plugins
########################################
FROM opensearchproject/opensearch:3.2.0 AS upstream_opensearch

# Remove plugins
RUN opensearch-plugin remove opensearch-neural-search || true && \
    opensearch-plugin remove opensearch-knn || true && \
    # removing this one due to Netty CVE-2025-58056, can bring it back in the future
    opensearch-plugin remove opensearch-security-analytics || true 

# Prepare jvector plugin artifacts
RUN mkdir -p /tmp/opensearch-jvector-plugin && \
    curl -L -s https://github.com/opensearch-project/opensearch-jvector/releases/download/3.2.0.0/artifacts.tar.gz \
      | tar zxvf - -C /tmp/opensearch-jvector-plugin

# Prepare neural-search plugin
RUN mkdir -p /tmp/opensearch-neural-search && \
    curl -L -s https://storage.googleapis.com/opensearch-jvector/opensearch-neural-search-3.2.0.0-20251029200300.zip \
      > /tmp/opensearch-neural-search/plugin.zip

# Install additional plugins
RUN opensearch-plugin install --batch file:///tmp/opensearch-jvector-plugin/repository/org/opensearch/plugin/opensearch-jvector-plugin/3.2.0.0/opensearch-jvector-plugin-3.2.0.0.zip && \
    opensearch-plugin install --batch file:///tmp/opensearch-neural-search/plugin.zip && \
    opensearch-plugin install --batch repository-gcs && \
    opensearch-plugin install --batch repository-azure && \
    # opensearch-plugin install --batch repository-s3 && \
    opensearch-plugin install --batch https://github.com/opensearch-project/opensearch-prometheus-exporter/releases/download/3.2.0.0/prometheus-exporter-3.2.0.0.zip

# Apply Netty patch
COPY patch-netty.sh /tmp/
RUN whoami && bash /tmp/patch-netty.sh

# Set permissions for OpenShift compatibility before copying
RUN chmod -R g=u /usr/share/opensearch


########################################
# Stage 2: UBI9 runtime image
########################################
FROM registry.access.redhat.com/ubi9/ubi:latest

USER root

# Update packages and install required tools
# TODO bring back iostat somehow? sysstat isn't in ubi
# TODO bring back 'perf' package, but what did we need it for?
RUN dnf update -y && \
    dnf install -y --allowerasing \
      less procps-ng findutils sudo curl tar gzip shadow-utils which && \
    dnf clean all

# Create opensearch user and group
ARG UID=1000
ARG GID=1000
ARG OPENSEARCH_HOME=/usr/share/opensearch

WORKDIR $OPENSEARCH_HOME

RUN groupadd -g $GID opensearch && \
    adduser -u $UID -g $GID -d $OPENSEARCH_HOME opensearch

# Grant the opensearch user sudo privileges (passwordless sudo)
RUN usermod -aG wheel opensearch && \
    echo "opensearch ALL=(ALL) NOPASSWD:ALL" >> /etc/sudoers

# Copy OpenSearch from the upstream stage
COPY --from=upstream_opensearch --chown=$UID:0 $OPENSEARCH_HOME $OPENSEARCH_HOME

ARG OPENSEARCH_VERSION=3.2.0

########################################
# Async-profiler (multi-arch like your original)
########################################
ARG TARGETARCH

RUN if [ "$TARGETARCH" = "amd64" ]; then \
      export ASYNC_PROFILER_URL=https://github.com/async-profiler/async-profiler/releases/download/v4.2/async-profiler-4.2-linux-x64.tar.gz; \
    elif [ "$TARGETARCH" = "arm64" ]; then \
      export ASYNC_PROFILER_URL=https://github.com/async-profiler/async-profiler/releases/download/v4.2/async-profiler-4.2-linux-arm64.tar.gz; \
    else \
      echo "Unsupported architecture: $TARGETARCH" && exit 1; \
    fi && \
    mkdir /opt/async-profiler && \
    curl -s -L -f $ASYNC_PROFILER_URL | tar zxvf - --strip-components=1 -C /opt/async-profiler && \
    chown -R opensearch:opensearch /opt/async-profiler

# Create profiling script (as in your original Dockerfile)
RUN echo "#!/bin/bash" > /usr/share/opensearch/profile.sh && \
    echo "export PATH=\$PATH:/opt/async-profiler/bin" >> /usr/share/opensearch/profile.sh && \
    echo "echo 1 | sudo tee /proc/sys/kernel/perf_event_paranoid >/dev/null" >> /usr/share/opensearch/profile.sh && \
    echo "echo 0 | sudo tee /proc/sys/kernel/kptr_restrict >/dev/null" >> /usr/share/opensearch/profile.sh && \
    echo "asprof \$@" >> /usr/share/opensearch/profile.sh && \
    chmod 777 /usr/share/opensearch/profile.sh

########################################
# Security config (OIDC/DLS) and setup script
########################################

# Copy OIDC and DLS security configuration (as root, like before)
COPY securityconfig/ /usr/share/opensearch/securityconfig/
RUN chown -R opensearch:opensearch /usr/share/opensearch/securityconfig/

# Create a script to apply security configuration after OpenSearch starts
RUN echo '#!/bin/bash' > /usr/share/opensearch/setup-security.sh && \
    echo 'echo "Waiting for OpenSearch to start..."' >> /usr/share/opensearch/setup-security.sh && \
    echo 'PASSWORD=${OPENSEARCH_INITIAL_ADMIN_PASSWORD:-${OPENSEARCH_PASSWORD}}' >> /usr/share/opensearch/setup-security.sh && \
    echo 'if [ -z "$PASSWORD" ]; then echo "[ERROR] OPENSEARCH_INITIAL_ADMIN_PASSWORD or OPENSEARCH_PASSWORD must be set"; exit 1; fi' >> /usr/share/opensearch/setup-security.sh && \
    echo 'until curl -s -k -u admin:$PASSWORD https://localhost:9200; do sleep 1; done' >> /usr/share/opensearch/setup-security.sh && \
    echo 'echo "Generating admin hash from configured password..."' >> /usr/share/opensearch/setup-security.sh && \
    echo 'HASH=$(/usr/share/opensearch/plugins/opensearch-security/tools/hash.sh -p "$PASSWORD")' >> /usr/share/opensearch/setup-security.sh && \
    echo 'if [ -z "$HASH" ]; then echo "[ERROR] Failed to generate admin hash"; exit 1; fi' >> /usr/share/opensearch/setup-security.sh && \
    echo 'sed -i "s|^  hash: \".*\"|  hash: \"$HASH\"|" /usr/share/opensearch/securityconfig/internal_users.yml' >> /usr/share/opensearch/setup-security.sh && \
    echo 'echo "Updated internal_users.yml with runtime-generated admin hash"' >> /usr/share/opensearch/setup-security.sh && \
    echo 'echo "Applying OIDC and DLS security configuration..."' >> /usr/share/opensearch/setup-security.sh && \
    echo '/usr/share/opensearch/plugins/opensearch-security/tools/securityadmin.sh \' >> /usr/share/opensearch/setup-security.sh && \
    echo '  -cd /usr/share/opensearch/securityconfig \' >> /usr/share/opensearch/setup-security.sh && \
    echo '  -icl -nhnv \' >> /usr/share/opensearch/setup-security.sh && \
    echo '  -cacert /usr/share/opensearch/config/root-ca.pem \' >> /usr/share/opensearch/setup-security.sh && \
    echo '  -cert /usr/share/opensearch/config/kirk.pem \' >> /usr/share/opensearch/setup-security.sh && \
    echo '  -key /usr/share/opensearch/config/kirk-key.pem' >> /usr/share/opensearch/setup-security.sh && \
    echo 'echo "Security configuration applied successfully"' >> /usr/share/opensearch/setup-security.sh && \
    chmod +x /usr/share/opensearch/setup-security.sh

########################################
# Final runtime settings
########################################
USER opensearch
WORKDIR $OPENSEARCH_HOME
ENV JAVA_HOME=$OPENSEARCH_HOME/jdk
ENV PATH=$PATH:$JAVA_HOME/bin:$OPENSEARCH_HOME/bin

# Expose ports
EXPOSE 9200 9300 9600 9650

ENTRYPOINT ["./opensearch-docker-entrypoint.sh"]
CMD ["opensearch"]

