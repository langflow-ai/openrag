#!/bin/bash
set -euo pipefail

NETTY_VERSION="4.2.15.Final"
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

# Whitelist of core Netty artifacts to match and patch
declare -A CORE_NETTY_ARTIFACTS=(
    ["netty-buffer"]=1
    ["netty-codec"]=1
    ["netty-codec-dns"]=1
    ["netty-codec-http"]=1
    ["netty-codec-http2"]=1
    ["netty-codec-socks"]=1
    ["netty-common"]=1
    ["netty-handler"]=1
    ["netty-handler-proxy"]=1
    ["netty-resolver"]=1
    ["netty-resolver-dns"]=1
    ["netty-transport"]=1
    ["netty-transport-classes-epoll"]=1
    ["netty-transport-native-unix-common"]=1
)

replaced_count=0
matched_count=0

echo "Searching for Netty jars to patch in /usr/share/opensearch..."

# Find all Netty jars under /usr/share/opensearch
shopt -s globstar
for jar_path in /usr/share/opensearch/**/netty-*.jar; do
    [ -f "$jar_path" ] || continue
    filename=$(basename "$jar_path")
    dir=$(dirname "$jar_path")
    
    # Match netty-<artifact>-<version>.jar
    # Example: netty-buffer-4.2.12.Final.jar
    if [[ "$filename" =~ ^(netty-[a-z0-9-]+)-([0-9]+\.[0-9]+\.[0-9]+\.?[a-zA-Z0-9]*)\.jar$ ]]; then
        artifact="${BASH_REMATCH[1]}"
        version="${BASH_REMATCH[2]}"
        
        # Check if the artifact is one of the core Netty artifacts we want to patch
        if [[ -n "${CORE_NETTY_ARTIFACTS[$artifact]:-}" ]]; then
            matched_count=$((matched_count + 1))
            # If the version is already the target version, skip
            if [ "$version" = "$NETTY_VERSION" ]; then
                echo "  Skipping: ${filename} (already version ${NETTY_VERSION})"
                continue
            fi
            
            echo "  Found vulnerable Netty jar: ${filename} in ${dir}"
            
            new_jar="${DOWNLOAD_DIR}/${artifact}-${NETTY_VERSION}.jar"
            
            # Download the new version if it hasn't been downloaded yet
            if [ ! -f "$new_jar" ]; then
                echo "    Downloading ${artifact}-${NETTY_VERSION}.jar..."
                if ! download_with_retry "${MAVEN_BASE_URL}/${artifact}/${NETTY_VERSION}/${artifact}-${NETTY_VERSION}.jar" "$new_jar"; then
                    echo "ERROR: Failed to download patched dependency ${artifact}."
                    exit 1
                fi
            fi
            
            # Replace the old jar with a hardlink to the new jar
            rm -f "$jar_path"
            new_filename="${dir}/${artifact}-${NETTY_VERSION}.jar"
            ln "$new_jar" "$new_filename"
            echo "    Replaced with: ${artifact}-${NETTY_VERSION}.jar"
            replaced_count=$((replaced_count + 1))
        fi
    fi
done

# Clean up download directory
rm -rf "${DOWNLOAD_DIR}"

echo "Netty patching complete. Replaced ${replaced_count} jars."

# Fail-safe check: If no Netty jars were matched at all, we must fail the build.
if [ "${matched_count}" -eq 0 ]; then
    echo "ERROR: No Netty jars were found to be patched! This indicates that the script failed to find any expected jars."
    exit 1
fi
