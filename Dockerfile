FROM opensearchproject/opensearch:3.0.0

USER root

RUN echo y | dnf install less procps-ng findutils sysstat perf sudo

# Grant the opensearchuser sudo privileges
# 'wheel' is the sudo group in Amazon Linux
RUN usermod -aG wheel opensearch

# Change the sudoers file to allow passwordless sudo
RUN echo "opensearch ALL=(ALL) NOPASSWD:ALL" >> /etc/sudoers

# FIXME handle the machine arch better, somehow
ARG ASYNC_PROFILER_URL=https://github.com/async-profiler/async-profiler/releases/download/v4.0/async-profiler-4.0-linux-x64.tar.gz

RUN mkdir /opt/async-profiler
RUN curl -s -L $ASYNC_PROFILER_URL | tar zxvf - --strip-components=1 -C /opt/async-profiler
RUN chown -R opensearch:opensearch /opt/async-profiler

RUN echo "#!/bin/bash" > /usr/share/opensearch/profile.sh
RUN echo "export PATH=\$PATH:/opt/async-profiler/bin" >> /usr/share/opensearch/profile.sh
RUN echo "echo 1 | sudo tee /proc/sys/kernel/perf_event_paranoid >/dev/null" >> /usr/share/opensearch/profile.sh
RUN echo "echo 0 | sudo tee /proc/sys/kernel/kptr_restrict >/dev/null" >> /usr/share/opensearch/profile.sh
RUN echo "asprof \$@" >> /usr/share/opensearch/profile.sh

RUN chmod 777 /usr/share/opensearch/profile.sh

USER opensearch

RUN opensearch-plugin remove opensearch-neural-search
RUN opensearch-plugin remove opensearch-knn

# FIXME installing the prom exporter plugin ahead of time isn't compatible with the operator, for now
# RUN opensearch-plugin install https://github.com/Virtimo/prometheus-exporter-plugin-for-opensearch/releases/download/v2.18.0/prometheus-exporter-2.18.0.0.zip

RUN echo y | opensearch-plugin install https://repo1.maven.org/maven2/org/opensearch/plugin/opensearch-jvector-plugin/3.0.0.3/opensearch-jvector-plugin-3.0.0.3.zip
RUN echo y | opensearch-plugin install repository-gcs
RUN echo y | opensearch-plugin install repository-azure
RUN echo y | opensearch-plugin install repository-s3

# Copy OIDC and DLS security configuration
COPY securityconfig/ /usr/share/opensearch/securityconfig/

# Create a script to apply security configuration after OpenSearch starts
RUN echo '#!/bin/bash' > /usr/share/opensearch/setup-security.sh && \
    echo 'echo "Waiting for OpenSearch to start..."' >> /usr/share/opensearch/setup-security.sh && \
    echo 'until curl -s -k -u admin:${OPENSEARCH_INITIAL_ADMIN_PASSWORD} https://localhost:9200; do sleep 1; done' >> /usr/share/opensearch/setup-security.sh && \
    echo 'echo "Applying OIDC and DLS security configuration..."' >> /usr/share/opensearch/setup-security.sh && \
    echo '/usr/share/opensearch/plugins/opensearch-security/tools/securityadmin.sh \' >> /usr/share/opensearch/setup-security.sh && \
    echo '  -cd /usr/share/opensearch/securityconfig \' >> /usr/share/opensearch/setup-security.sh && \
    echo '  -icl -nhnv \' >> /usr/share/opensearch/setup-security.sh && \
    echo '  -cacert /usr/share/opensearch/config/root-ca.pem \' >> /usr/share/opensearch/setup-security.sh && \
    echo '  -cert /usr/share/opensearch/config/kirk.pem \' >> /usr/share/opensearch/setup-security.sh && \
    echo '  -key /usr/share/opensearch/config/kirk-key.pem' >> /usr/share/opensearch/setup-security.sh && \
    echo 'echo "Security configuration applied successfully"' >> /usr/share/opensearch/setup-security.sh && \
    chmod +x /usr/share/opensearch/setup-security.sh
