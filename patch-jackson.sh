#!/bin/bash
set -euo pipefail

JACKSON_OLD_VERSION="2.21.2"
JACKSON_NEW_VERSION="2.21.5"
MAVEN_BASE_URL="https://repo1.maven.org/maven2/com/fasterxml/jackson"
DOWNLOAD_DIR="/tmp/patches/jackson"

# Mapping of artifact name -> maven sub-path under ${MAVEN_BASE_URL}
declare -A ARTIFACT_GROUP=(
    ["jackson-core"]="core"
    ["jackson-databind"]="core"
    ["jackson-dataformat-yaml"]="dataformat"
    ["jackson-dataformat-smile"]="dataformat"
    ["jackson-dataformat-cbor"]="dataformat"
    ["jackson-dataformat-xml"]="dataformat"
    ["jackson-datatype-jsr310"]="datatype"
    ["jackson-module-paranamer"]="module"
    ["jackson-module-jaxb-annotations"]="module"
)

# Strict list of standalone jars to replace (2.21.2 -> 2.21.5)
JACKSON_FILES=(
    "/usr/share/opensearch/plugins/opensearch-search-relevance/jackson-databind-${JACKSON_OLD_VERSION}.jar"
    "/usr/share/opensearch/plugins/opensearch-notifications-core/jackson-databind-${JACKSON_OLD_VERSION}.jar"
    "/usr/share/opensearch/plugins/opensearch-neural-search/jackson-databind-${JACKSON_OLD_VERSION}.jar"
    "/usr/share/opensearch/plugins/opensearch-sql/jackson-databind-${JACKSON_OLD_VERSION}.jar"
    "/usr/share/opensearch/plugins/opensearch-reports-scheduler/jackson-databind-${JACKSON_OLD_VERSION}.jar"
    "/usr/share/opensearch/plugins/opensearch-performance-analyzer/jackson-databind-${JACKSON_OLD_VERSION}.jar"
    "/usr/share/opensearch/plugins/opensearch-performance-analyzer/jackson-module-paranamer-${JACKSON_OLD_VERSION}.jar"
    "/usr/share/opensearch/plugins/opensearch-notifications/jackson-datatype-jsr310-${JACKSON_OLD_VERSION}.jar"
    "/usr/share/opensearch/plugins/repository-s3/jackson-databind-${JACKSON_OLD_VERSION}.jar"
    "/usr/share/opensearch/plugins/opensearch-flow-framework/jackson-databind-${JACKSON_OLD_VERSION}.jar"
    "/usr/share/opensearch/plugins/opensearch-flow-framework/jackson-datatype-jsr310-${JACKSON_OLD_VERSION}.jar"
    "/usr/share/opensearch/plugins/opensearch-ubi/jackson-databind-${JACKSON_OLD_VERSION}.jar"
    "/usr/share/opensearch/plugins/opensearch-security/jackson-databind-${JACKSON_OLD_VERSION}.jar"
    "/usr/share/opensearch/plugins/opensearch-ml/jackson-databind-${JACKSON_OLD_VERSION}.jar"
    "/usr/share/opensearch/plugins/opensearch-observability/jackson-databind-${JACKSON_OLD_VERSION}.jar"
    "/usr/share/opensearch/plugins/repository-azure/jackson-dataformat-xml-${JACKSON_OLD_VERSION}.jar"
    "/usr/share/opensearch/plugins/repository-azure/jackson-databind-${JACKSON_OLD_VERSION}.jar"
    "/usr/share/opensearch/plugins/repository-azure/jackson-datatype-jsr310-${JACKSON_OLD_VERSION}.jar"
    "/usr/share/opensearch/plugins/repository-azure/jackson-module-jaxb-annotations-${JACKSON_OLD_VERSION}.jar"
    "/usr/share/opensearch/plugins/opensearch-anomaly-detection/jackson-databind-${JACKSON_OLD_VERSION}.jar"
    "/usr/share/opensearch/lib/jackson-dataformat-yaml-${JACKSON_OLD_VERSION}.jar"
    "/usr/share/opensearch/lib/jackson-dataformat-smile-${JACKSON_OLD_VERSION}.jar"
    "/usr/share/opensearch/lib/jackson-core-${JACKSON_OLD_VERSION}.jar"
    "/usr/share/opensearch/lib/jackson-dataformat-cbor-${JACKSON_OLD_VERSION}.jar"
    "/usr/share/opensearch/modules/ingest-geoip/jackson-databind-${JACKSON_OLD_VERSION}.jar"
    "/usr/share/opensearch/modules/ingest-geoip/jackson-datatype-jsr310-${JACKSON_OLD_VERSION}.jar"
)

# Special cases: jars with a non-standard old version
# Format: "old_path:artifact_name"
JACKSON_SPECIAL_FILES=(
    "/usr/share/opensearch/plugins/opensearch-ml/jackson-datatype-jsr310-2.18.3.jar:jackson-datatype-jsr310"
)

# Fat/shaded JARs that contain jackson classes internally.
# These are repacked: jackson classes are replaced in-place inside the fat jar.
# Format: "fat_jar_path:artifact_name_to_replace"
JACKSON_SHADED_JARS=(
    "/usr/share/opensearch/plugins/opensearch-security/opensaml-3.6.0.0-all.jar:jackson-core"
)

# ---------------------------------------------------------------------------
# Download phase
# ---------------------------------------------------------------------------

# Derive unique artifact names from JACKSON_FILES + JACKSON_SPECIAL_FILES
declare -A ARTIFACTS_TO_DOWNLOAD
for old_jar in "${JACKSON_FILES[@]}"; do
    filename=$(basename "${old_jar}")
    artifact="${filename%-${JACKSON_OLD_VERSION}.jar}"
    ARTIFACTS_TO_DOWNLOAD["${artifact}"]=1
done
for entry in "${JACKSON_SPECIAL_FILES[@]}"; do
    artifact="${entry#*:}"
    ARTIFACTS_TO_DOWNLOAD["${artifact}"]=1
done
# Also need jackson-core for repacking shaded jars
ARTIFACTS_TO_DOWNLOAD["jackson-core"]=1

mkdir -p "${DOWNLOAD_DIR}"

echo "Downloading Jackson ${JACKSON_NEW_VERSION} artifacts..."
for artifact in "${!ARTIFACTS_TO_DOWNLOAD[@]}"; do
    jar_file="${artifact}-${JACKSON_NEW_VERSION}.jar"
    dest="${DOWNLOAD_DIR}/${jar_file}"

    if [ ! -f "${dest}" ]; then
        group="${ARTIFACT_GROUP[${artifact}]:-}"
        if [ -z "${group}" ]; then
            echo "ERROR: Unknown maven group for artifact '${artifact}'. Add it to ARTIFACT_GROUP." >&2
            exit 1
        fi
        url="${MAVEN_BASE_URL}/${group}/${artifact}/${JACKSON_NEW_VERSION}/${jar_file}"
        echo "  Downloading ${artifact} from ${url}..."
        curl -fsSL "${url}" -o "${dest}"
    else
        echo "  Already cached: ${jar_file}"
    fi
done

# Replace standalone jars
replace_jackson_jar() {
    local old_jar="$1"
    if [ ! -f "${old_jar}" ]; then
        echo "  Skipping (not found): ${old_jar}"
        return
    fi
    local dir; dir=$(dirname "${old_jar}")
    local filename; filename=$(basename "${old_jar}")
    local artifact="${filename%-${JACKSON_OLD_VERSION}.jar}"
    local new_jar="${DOWNLOAD_DIR}/${artifact}-${JACKSON_NEW_VERSION}.jar"
    local new_path="${dir}/${artifact}-${JACKSON_NEW_VERSION}.jar"
    rm -f "${old_jar}"
    ln "${new_jar}" "${new_path}"
    echo "  Replaced: ${old_jar} -> ${new_path}"
}

replace_jackson_jar_special() {
    local old_jar="$1"
    local artifact="$2"
    if [ ! -f "${old_jar}" ]; then
        echo "  Skipping (not found): ${old_jar}"
        return
    fi
    local dir; dir=$(dirname "${old_jar}")
    local new_jar="${DOWNLOAD_DIR}/${artifact}-${JACKSON_NEW_VERSION}.jar"
    local new_path="${dir}/${artifact}-${JACKSON_NEW_VERSION}.jar"
    rm -f "${old_jar}"
    ln "${new_jar}" "${new_path}"
    echo "  Replaced: ${old_jar} -> ${new_path}"
}

echo "Replacing standalone Jackson ${JACKSON_OLD_VERSION} jars with ${JACKSON_NEW_VERSION}..."
for old_jar in "${JACKSON_FILES[@]}"; do
    replace_jackson_jar "${old_jar}"
done

echo "Replacing special-versioned Jackson jars with ${JACKSON_NEW_VERSION}..."
for entry in "${JACKSON_SPECIAL_FILES[@]}"; do
    old_jar="${entry%%:*}"
    artifact="${entry#*:}"
    replace_jackson_jar_special "${old_jar}" "${artifact}"
done

# Repack shaded/fat JARs — replace jackson classes inside the fat jar
repack_shaded_jar() {
    local fat_jar="$1"
    local artifact="$2"

    if [ ! -f "${fat_jar}" ]; then
        echo "  Skipping (not found): ${fat_jar}"
        return
    fi

    echo "  Repacking shaded jar: ${fat_jar}"

    # Use the JDK jar tool bundled with OpenSearch — no unzip/zip needed
    local JAR_CMD
    if [ -x "/usr/share/opensearch/jdk/bin/jar" ]; then
        JAR_CMD="/usr/share/opensearch/jdk/bin/jar"
    elif command -v jar &>/dev/null; then
        JAR_CMD="jar"
    else
        echo "ERROR: no 'jar' command found. Cannot repack shaded jar." >&2
        exit 1
    fi

    local work_dir="${DOWNLOAD_DIR}/repack/$(basename "${fat_jar}" .jar)"
    mkdir -p "${work_dir}"

    # Extract the fat jar
    (cd "${work_dir}" && "${JAR_CMD}" xf "${fat_jar}")

    # Extract the patched artifact's classes into a temp dir and overlay
    local patched_jar="${DOWNLOAD_DIR}/${artifact}-${JACKSON_NEW_VERSION}.jar"
    local overlay_dir="${DOWNLOAD_DIR}/overlay/$(basename "${fat_jar}" .jar)"
    mkdir -p "${overlay_dir}"
    (cd "${overlay_dir}" && "${JAR_CMD}" xf "${patched_jar}")

    # Find where jackson classes live in the fat jar (may be shaded/relocated)
    local jackson_dirs
    jackson_dirs=$(find "${work_dir}" -type d -name "jackson" 2>/dev/null | head -5)
    if [ -z "${jackson_dirs}" ]; then
        echo "    WARNING: no jackson class directory found in $(basename "${fat_jar}") — skipping class overlay (classes may be relocated under a different package)"
    else
        echo "    Found jackson dirs: ${jackson_dirs}"
        # Overlay standard com/fasterxml/jackson classes from the patched jar
        if [ -d "${overlay_dir}/com/fasterxml/jackson" ]; then
            while IFS= read -r target_dir; do
                cp -rf "${overlay_dir}/com/fasterxml/jackson/" "${target_dir}/"
                echo "    Overlaid ${artifact} classes -> ${target_dir}"
            done <<< "${jackson_dirs}"
        else
            echo "    WARNING: overlay jar has no com/fasterxml/jackson dir — skipping overlay"
        fi
    fi

    # Remove embedded maven metadata for the artifact so Trivy does not report
    # the old version from pom.properties / pom.xml inside the fat jar.
    local meta_dir="${work_dir}/META-INF/maven/com.fasterxml.jackson.core/${artifact}"
    if [ -d "${meta_dir}" ]; then
        rm -rf "${meta_dir}"
        echo "    Removed embedded maven metadata: META-INF/maven/com.fasterxml.jackson.core/${artifact}"
    else
        echo "    No embedded maven metadata found for ${artifact} (nothing to remove)"
    fi

    # Repack the fat jar in-place
    rm -f "${fat_jar}"
    (cd "${work_dir}" && "${JAR_CMD}" cf "${fat_jar}" .)
    echo "    Repacked: ${fat_jar}"

    # Cleanup work dirs
    rm -rf "${work_dir}" "${overlay_dir}"
}

echo "Repacking shaded JARs containing Jackson ${JACKSON_OLD_VERSION}..."
for entry in "${JACKSON_SHADED_JARS[@]}"; do
    fat_jar="${entry%%:*}"
    artifact="${entry#*:}"
    repack_shaded_jar "${fat_jar}" "${artifact}"
done

# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------
rm -rf "${DOWNLOAD_DIR}"

echo "Successfully patched all Jackson jars to ${JACKSON_NEW_VERSION}."

