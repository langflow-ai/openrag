#!/bin/bash
set -euo pipefail

NETTY_VERSION="4.1.125.Final"
MAVEN_BASE_URL="https://repo1.maven.org/maven2/io/netty"
DOWNLOAD_DIR="/tmp/netty-${NETTY_VERSION}"

# Create download directory
mkdir -p "${DOWNLOAD_DIR}"

# Download with retry logic for transient network failures
download_with_retry() {
    local url="$1"
    local output="$2"
    local max_retries=3
    local retry_delay=5
    
    for i in $(seq 1 $max_retries); do
        if curl -fsSL "$url" -o "$output"; then
            return 0
        fi
        echo "    Attempt $i failed, retrying in ${retry_delay}s..."
        sleep $retry_delay
    done
    
    echo "    ERROR: Failed to download after $max_retries attempts: $url"
    return 1
}

# List of unique Netty artifacts
# Some of them are not used below, but we'll keep the complete set here
NETTY_ARTIFACTS=(
    "netty-buffer"
    "netty-codec"
    "netty-codec-dns"
    "netty-codec-http"
    "netty-codec-http2"
    "netty-codec-socks"
    "netty-common"
    "netty-handler"
    "netty-handler-proxy"
    "netty-resolver"
    "netty-resolver-dns"
    "netty-transport"
    "netty-transport-classes-epoll"
    "netty-transport-native-unix-common"
)

echo "Downloading Netty ${NETTY_VERSION} artifacts..."
for artifact in "${NETTY_ARTIFACTS[@]}"; do
    jar_file="${artifact}-${NETTY_VERSION}.jar"
    if [ ! -f "${DOWNLOAD_DIR}/${jar_file}" ]; then
        echo "  Downloading ${artifact}..."
        download_with_retry "${MAVEN_BASE_URL}/${artifact}/${NETTY_VERSION}/${jar_file}" \
            "${DOWNLOAD_DIR}/${jar_file}"
    fi
done

echo "Removing old Netty jars and replacing with ${NETTY_VERSION}..."

# Function to replace jar with hardlink
replace_jar() {
    local old_jar="$1"
    local artifact_name="$2"
    local new_jar="${DOWNLOAD_DIR}/${artifact_name}-${NETTY_VERSION}.jar"

    if [ -f "${old_jar}" ]; then
        rm -f "${old_jar}"
        # Extract directory path
        local dir=$(dirname "${old_jar}")
        # Create hardlink with the new version number in filename
        local new_filename="${dir}/${artifact_name}-${NETTY_VERSION}.jar"
        ln "${new_jar}" "${new_filename}"
        echo "  Replaced: ${old_jar} -> ${new_filename}"
    fi
}

# Replace transport-netty4 module jars (4.1.121.Final -> 4.1.125.Final)
replace_jar "/usr/share/opensearch/modules/transport-netty4/netty-buffer-4.1.121.Final.jar" "netty-buffer"
replace_jar "/usr/share/opensearch/modules/transport-netty4/netty-codec-4.1.121.Final.jar" "netty-codec"
replace_jar "/usr/share/opensearch/modules/transport-netty4/netty-codec-http-4.1.121.Final.jar" "netty-codec-http"
replace_jar "/usr/share/opensearch/modules/transport-netty4/netty-codec-http2-4.1.121.Final.jar" "netty-codec-http2"
replace_jar "/usr/share/opensearch/modules/transport-netty4/netty-common-4.1.121.Final.jar" "netty-common"
replace_jar "/usr/share/opensearch/modules/transport-netty4/netty-handler-4.1.121.Final.jar" "netty-handler"
replace_jar "/usr/share/opensearch/modules/transport-netty4/netty-resolver-4.1.121.Final.jar" "netty-resolver"
replace_jar "/usr/share/opensearch/modules/transport-netty4/netty-transport-4.1.121.Final.jar" "netty-transport"
replace_jar "/usr/share/opensearch/modules/transport-netty4/netty-transport-native-unix-common-4.1.121.Final.jar" "netty-transport-native-unix-common"

# Replace opensearch-ml plugin jars (4.1.118.Final -> 4.1.125.Final)
replace_jar "/usr/share/opensearch/plugins/opensearch-ml/netty-buffer-4.1.118.Final.jar" "netty-buffer"
replace_jar "/usr/share/opensearch/plugins/opensearch-ml/netty-codec-4.1.118.Final.jar" "netty-codec"
replace_jar "/usr/share/opensearch/plugins/opensearch-ml/netty-codec-http-4.1.118.Final.jar" "netty-codec-http"
replace_jar "/usr/share/opensearch/plugins/opensearch-ml/netty-codec-http2-4.1.118.Final.jar" "netty-codec-http2"
replace_jar "/usr/share/opensearch/plugins/opensearch-ml/netty-common-4.1.118.Final.jar" "netty-common"
replace_jar "/usr/share/opensearch/plugins/opensearch-ml/netty-handler-4.1.118.Final.jar" "netty-handler"
replace_jar "/usr/share/opensearch/plugins/opensearch-ml/netty-resolver-4.1.118.Final.jar" "netty-resolver"
replace_jar "/usr/share/opensearch/plugins/opensearch-ml/netty-transport-4.1.118.Final.jar" "netty-transport"
replace_jar "/usr/share/opensearch/plugins/opensearch-ml/netty-transport-classes-epoll-4.1.118.Final.jar" "netty-transport-classes-epoll"
replace_jar "/usr/share/opensearch/plugins/opensearch-ml/netty-transport-native-unix-common-4.1.118.Final.jar" "netty-transport-native-unix-common"

# Replace opensearch-notifications plugin jars (4.1.118.Final -> 4.1.125.Final)
replace_jar "/usr/share/opensearch/plugins/opensearch-notifications/netty-buffer-4.1.118.Final.jar" "netty-buffer"
replace_jar "/usr/share/opensearch/plugins/opensearch-notifications/netty-codec-4.1.118.Final.jar" "netty-codec"
replace_jar "/usr/share/opensearch/plugins/opensearch-notifications/netty-codec-http-4.1.118.Final.jar" "netty-codec-http"
replace_jar "/usr/share/opensearch/plugins/opensearch-notifications/netty-codec-http2-4.1.118.Final.jar" "netty-codec-http2"
replace_jar "/usr/share/opensearch/plugins/opensearch-notifications/netty-common-4.1.118.Final.jar" "netty-common"
replace_jar "/usr/share/opensearch/plugins/opensearch-notifications/netty-handler-4.1.118.Final.jar" "netty-handler"
replace_jar "/usr/share/opensearch/plugins/opensearch-notifications/netty-resolver-4.1.118.Final.jar" "netty-resolver"
replace_jar "/usr/share/opensearch/plugins/opensearch-notifications/netty-transport-4.1.118.Final.jar" "netty-transport"
replace_jar "/usr/share/opensearch/plugins/opensearch-notifications/netty-transport-classes-epoll-4.1.118.Final.jar" "netty-transport-classes-epoll"
replace_jar "/usr/share/opensearch/plugins/opensearch-notifications/netty-transport-native-unix-common-4.1.118.Final.jar" "netty-transport-native-unix-common"

# Replace opensearch-performance-analyzer plugin jars (4.1.121.Final -> 4.1.125.Final)
replace_jar "/usr/share/opensearch/plugins/opensearch-performance-analyzer/netty-buffer-4.1.121.Final.jar" "netty-buffer"
replace_jar "/usr/share/opensearch/plugins/opensearch-performance-analyzer/netty-codec-4.1.121.Final.jar" "netty-codec"
replace_jar "/usr/share/opensearch/plugins/opensearch-performance-analyzer/netty-codec-http-4.1.121.Final.jar" "netty-codec-http"
replace_jar "/usr/share/opensearch/plugins/opensearch-performance-analyzer/netty-codec-http2-4.1.121.Final.jar" "netty-codec-http2"
replace_jar "/usr/share/opensearch/plugins/opensearch-performance-analyzer/netty-codec-socks-4.1.121.Final.jar" "netty-codec-socks"
replace_jar "/usr/share/opensearch/plugins/opensearch-performance-analyzer/netty-common-4.1.121.Final.jar" "netty-common"
replace_jar "/usr/share/opensearch/plugins/opensearch-performance-analyzer/netty-handler-4.1.121.Final.jar" "netty-handler"
replace_jar "/usr/share/opensearch/plugins/opensearch-performance-analyzer/netty-handler-proxy-4.1.121.Final.jar" "netty-handler-proxy"
replace_jar "/usr/share/opensearch/plugins/opensearch-performance-analyzer/netty-resolver-4.1.121.Final.jar" "netty-resolver"
replace_jar "/usr/share/opensearch/plugins/opensearch-performance-analyzer/netty-transport-4.1.121.Final.jar" "netty-transport"
replace_jar "/usr/share/opensearch/plugins/opensearch-performance-analyzer/netty-transport-native-unix-common-4.1.121.Final.jar" "netty-transport-native-unix-common"

# Replace opensearch-security plugin jars (4.1.121.Final -> 4.1.125.Final)
replace_jar "/usr/share/opensearch/plugins/opensearch-security/netty-buffer-4.1.121.Final.jar" "netty-buffer"
replace_jar "/usr/share/opensearch/plugins/opensearch-security/netty-codec-4.1.121.Final.jar" "netty-codec"
replace_jar "/usr/share/opensearch/plugins/opensearch-security/netty-codec-http-4.1.121.Final.jar" "netty-codec-http"
replace_jar "/usr/share/opensearch/plugins/opensearch-security/netty-codec-http2-4.1.121.Final.jar" "netty-codec-http2"
replace_jar "/usr/share/opensearch/plugins/opensearch-security/netty-common-4.1.121.Final.jar" "netty-common"
replace_jar "/usr/share/opensearch/plugins/opensearch-security/netty-handler-4.1.121.Final.jar" "netty-handler"
replace_jar "/usr/share/opensearch/plugins/opensearch-security/netty-resolver-4.1.121.Final.jar" "netty-resolver"
replace_jar "/usr/share/opensearch/plugins/opensearch-security/netty-transport-4.1.121.Final.jar" "netty-transport"
replace_jar "/usr/share/opensearch/plugins/opensearch-security/netty-transport-native-unix-common-4.1.121.Final.jar" "netty-transport-native-unix-common"

# Replace repository-azure plugin jars (4.1.121.Final -> 4.1.125.Final)
replace_jar "/usr/share/opensearch/plugins/repository-azure/netty-buffer-4.1.121.Final.jar" "netty-buffer"
replace_jar "/usr/share/opensearch/plugins/repository-azure/netty-codec-4.1.121.Final.jar" "netty-codec"
replace_jar "/usr/share/opensearch/plugins/repository-azure/netty-codec-dns-4.1.121.Final.jar" "netty-codec-dns"
replace_jar "/usr/share/opensearch/plugins/repository-azure/netty-codec-http-4.1.121.Final.jar" "netty-codec-http"
replace_jar "/usr/share/opensearch/plugins/repository-azure/netty-codec-http2-4.1.121.Final.jar" "netty-codec-http2"
replace_jar "/usr/share/opensearch/plugins/repository-azure/netty-codec-socks-4.1.121.Final.jar" "netty-codec-socks"
replace_jar "/usr/share/opensearch/plugins/repository-azure/netty-common-4.1.121.Final.jar" "netty-common"
replace_jar "/usr/share/opensearch/plugins/repository-azure/netty-handler-4.1.121.Final.jar" "netty-handler"
replace_jar "/usr/share/opensearch/plugins/repository-azure/netty-handler-proxy-4.1.121.Final.jar" "netty-handler-proxy"
replace_jar "/usr/share/opensearch/plugins/repository-azure/netty-resolver-4.1.121.Final.jar" "netty-resolver"
replace_jar "/usr/share/opensearch/plugins/repository-azure/netty-resolver-dns-4.1.121.Final.jar" "netty-resolver-dns"
replace_jar "/usr/share/opensearch/plugins/repository-azure/netty-transport-4.1.121.Final.jar" "netty-transport"
replace_jar "/usr/share/opensearch/plugins/repository-azure/netty-transport-native-unix-common-4.1.121.Final.jar" "netty-transport-native-unix-common"

# Remove the download directory after hardlinking
rm -rf "${DOWNLOAD_DIR}"

echo "Successfully replaced all old Netty jars with ${NETTY_VERSION}"
echo "Hardlinks used to minimize disk space"
