import asyncio
import copy
import os
import random
from typing import Any

import yaml
from opensearchpy import AsyncOpenSearch

from utils.logging_config import get_logger

logger = get_logger(__name__)

OPENRAG_USER_ROLE = "openrag_user_role"
OPENRAG_USER_ACL_ROLE = "openrag_user_acl_role"
ALL_ACCESS_ROLE = "all_access"

DISK_SPACE_ERROR_MESSAGE = (
    "OpenSearch has run out of available disk space. "
    "Search and indexing operations are blocked. "
    "Please free up disk space to restore OpenRAG functionality."
)

# Error strings emitted by OpenSearch when disk watermark thresholds are breached
_DISK_SPACE_INDICATORS = [
    "disk watermark",
    "flood_stage",
    "flood stage",
    "disk usage exceeded",
    "index read-only",
    "no space left on device",
    "cluster_block_exception",
    "forbidden/12",
    "too_many_requests/12",
]


class OpenSearchNotReadyError(Exception):
    """Raised when OpenSearch fails to become ready within the retry limit."""


class OpenSearchDiskSpaceError(Exception):
    """Raised when OpenSearch operations fail due to insufficient disk space."""


# Error strings emitted by OpenSearch when the presented credential is rejected.
# This is an AUTHENTICATION failure (bad/expired/over-ridden credential), not an
# authorization one — callers must surface it as 401, never 403 "insufficient
# permissions", so the real cause isn't masked.
_AUTH_ERROR_INDICATORS = [
    "authenticationexception",
    "unauthorized",
    "authentication failed",
]

AUTH_ERROR_MESSAGE = (
    "Authentication failed: OpenSearch rejected the credential. Please sign in again."
)

_SECURITY_SETUP_SKIP_INDICATORS = [
    "401",
    "403",
    "404",
    "security_exception",
    "not_found",
    "unauthorized",
    "forbidden",
]


def _is_security_setup_skip_error(error: Exception) -> bool:
    """True when the security API is unavailable before any mutation is attempted."""
    error_str = str(error).lower()
    return any(indicator in error_str for indicator in _SECURITY_SETUP_SKIP_INDICATORS)


def _is_not_found_error(error: Exception) -> bool:
    """True when OpenSearch reports a missing security object."""
    error_str = str(error).lower()
    return "404" in error_str or "not_found" in error_str


def _dedupe_preserving_order(values: list[Any]) -> list[Any]:
    """Return unique values while preserving their first-seen order."""
    result: list[Any] = []
    for value in values:
        if value not in result:
            result.append(value)
    return result


def _merge_role_mappings(*mappings: dict[str, Any] | None) -> dict[str, Any]:
    """Merge OpenSearch role-mapping principals without dropping custom entries."""
    merged: dict[str, Any] = {}
    for mapping in mappings:
        if not mapping:
            continue
        for key, value in mapping.items():
            if key in {"users", "hosts", "backend_roles", "and_backend_roles"}:
                merged[key] = _dedupe_preserving_order((merged.get(key) or []) + (value or []))
            elif key not in merged:
                merged[key] = copy.deepcopy(value)
    return merged


def is_opensearch_auth_error(error: Exception | str) -> bool:
    """Whether *error* is an OpenSearch authentication failure (401).

    Accepts an exception or an already-stringified error message. Distinct from
    authorization ("only the owner can …"): this means the credential OpenRAG
    presented was not accepted at all. Callers should map it to HTTP 401
    (re-authenticate), not 403.
    """
    error_str = str(error).lower()
    return any(indicator in error_str for indicator in _AUTH_ERROR_INDICATORS)


def is_disk_space_error(error: Exception) -> bool:
    """Check whether an exception is caused by OpenSearch disk space constraints.

    OpenSearch blocks write and search operations when disk usage crosses
    the high-watermark or flood-stage watermark thresholds.
    This function detects those error signatures.

    Args:
        error: The exception to inspect.

    Returns:
        True if the error is disk-space related, False otherwise.
    """
    error_str = str(error).lower()
    return any(indicator in error_str for indicator in _DISK_SPACE_INDICATORS)


def opensearch_error_reason(error: Exception) -> str | None:
    """Return the most specific OpenSearch failure reason carried by an exception.

    OpenSearch transport errors stringify to just ``TransportError(500, '')``; the
    real cause (and, on mapping/parse failures, the offending field) lives in the
    ``info`` body under ``error.root_cause[0].reason`` or ``error.reason``. Returns
    ``None`` when the exception carries no such structured reason.
    """
    info = getattr(error, "info", None)
    if not isinstance(info, dict):
        return None
    err = info.get("error")
    if not isinstance(err, dict):
        return None
    root_cause = err.get("root_cause")
    if isinstance(root_cause, list) and root_cause and isinstance(root_cause[0], dict):
        if root_cause[0].get("reason"):
            return root_cause[0]["reason"]
    return err.get("reason")


def opensearch_error_fields(error: Exception) -> dict[str, Any]:
    """Extract structured OpenSearch context from an exception for logging.

    Surfaces ``opensearch_status``/``opensearch_error``/``opensearch_info`` (and
    ``opensearch_root_cause`` when present) so every OpenSearch-touching call site
    logs the same schema instead of an opaque ``str(e)``. Non-OpenSearch
    exceptions yield an empty dict.
    """
    fields: dict[str, Any] = {}
    status = getattr(error, "status_code", None)
    if status is not None:
        fields["opensearch_status"] = status
    os_error = getattr(error, "error", None)
    if os_error is not None:
        fields["opensearch_error"] = os_error
    info = getattr(error, "info", None)
    if info is not None:
        fields["opensearch_info"] = info
        if isinstance(info, dict):
            err = info.get("error")
            if isinstance(err, dict):
                root_cause = err.get("root_cause")
                if isinstance(root_cause, list) and root_cause and isinstance(root_cause[0], dict):
                    fields["opensearch_root_cause"] = root_cause[0]
    return fields


async def wait_for_opensearch(
    opensearch_client: AsyncOpenSearch,
    max_retries: int = 30,
    base_delay: float = 2.0,
    max_delay: float = 30.0,
) -> None:
    """Wait for OpenSearch to be ready with exponential backoff and jitter.

    Args:
        opensearch_client: The OpenSearch client to use for health checks.
        max_retries: Maximum number of retry attempts.
        base_delay: Initial delay in seconds before the first retry.
        max_delay: Upper bound in seconds for the retry delay.

    Raises:
        OpenSearchNotReadyError: If OpenSearch fails to become ready within the retry limit.
    """
    for attempt in range(max_retries):
        display_attempt: int = attempt + 1

        logger.info(
            "Verifying whether OpenSearch is ready...",
            attempt=display_attempt,
            max_retries=max_retries,
        )

        try:
            # Simple ping to check connection
            if await opensearch_client.ping():
                # Also check cluster health
                health = await opensearch_client.cluster.health()
                status = health.get("status")
                if status in ["green", "yellow"]:
                    from config.settings import (
                        OPENSEARCH_EXPECTED_CLUSTER_MANAGER_COUNT,
                        OPENSEARCH_EXPECTED_COORDINATING_NODE_COUNT,
                        OPENSEARCH_EXPECTED_DATA_NODE_COUNT,
                        OPENSEARCH_NODE_COUNT_CHECK_ENABLED,
                    )

                    if OPENSEARCH_NODE_COUNT_CHECK_ENABLED:
                        data_node_count = health.get("number_of_data_nodes", 0)
                        # Reachable cluster-manager (master) nodes.
                        cm_info = await opensearch_client.transport.perform_request(
                            "GET", "/_nodes/cluster_manager:true/process,transport"
                        )
                        cluster_manager_count = cm_info.get("_nodes", {}).get("successful", 0)
                        # Reachable coordinating-only nodes.
                        coord_info = await opensearch_client.transport.perform_request(
                            "GET", "/_nodes/coordinating_only:true/process,transport"
                        )
                        coordinating_count = coord_info.get("_nodes", {}).get("successful", 0)

                        if (
                            data_node_count < OPENSEARCH_EXPECTED_DATA_NODE_COUNT
                            or cluster_manager_count < OPENSEARCH_EXPECTED_CLUSTER_MANAGER_COUNT
                            or coordinating_count < OPENSEARCH_EXPECTED_COORDINATING_NODE_COUNT
                        ):
                            logger.warning(
                                "OpenSearch healthy but cluster has not reached expected node count.",
                                attempt=display_attempt,
                                status=status,
                                number_of_data_nodes=data_node_count,
                                cluster_manager_nodes=cluster_manager_count,
                                coordinating_nodes=coordinating_count,
                                expected_data_nodes=OPENSEARCH_EXPECTED_DATA_NODE_COUNT,
                                expected_cluster_managers=OPENSEARCH_EXPECTED_CLUSTER_MANAGER_COUNT,
                                expected_coordinating=OPENSEARCH_EXPECTED_COORDINATING_NODE_COUNT,
                            )
                            # Fall through to the retry/backoff below until nodes join.
                        else:
                            logger.info(
                                "Successfully verified that OpenSearch is ready.",
                                attempt=display_attempt,
                                status=status,
                                number_of_data_nodes=data_node_count,
                                cluster_manager_nodes=cluster_manager_count,
                                coordinating_nodes=coordinating_count,
                            )
                            return
                    else:
                        logger.info(
                            "Successfully verified that OpenSearch is ready.",
                            attempt=display_attempt,
                            status=status,
                        )
                        return
                else:
                    logger.warning(
                        "OpenSearch is up but cluster health is red.",
                        attempt=display_attempt,
                        status=status,
                    )
            else:
                logger.warning(
                    "OpenSearch ping failed.",
                    attempt=display_attempt,
                )
        except Exception as e:
            logger.warning(
                "OpenSearch is not ready.",
                attempt=display_attempt,
                error=str(e),
            )

        if attempt < max_retries - 1:
            delay = min(base_delay * (2**attempt), max_delay)
            delay = random.uniform(delay / 2, delay)

            logger.debug(
                "Retry OpenSearch readiness check after a delay (seconds).",
                attempt=display_attempt,
                delay=delay,
            )

            await asyncio.sleep(delay)

    message: str = "Failed to verify whether OpenSearch is ready."
    logger.error(message)
    raise OpenSearchNotReadyError(message)


async def graceful_opensearch_shutdown(opensearch_client: AsyncOpenSearch) -> None:
    """Gracefully shutdown OpenSearch client connection.

    This ensures that all pending operations are completed and connections
    are properly closed before the application exits.

    Args:
        opensearch_client: The OpenSearch client to shutdown.
    """
    if opensearch_client is None:
        logger.debug("OpenSearch client is None, skipping graceful shutdown")
        return

    try:
        logger.info("Initiating graceful OpenSearch shutdown...")

        # Flush any pending operations by checking cluster health one last time
        try:
            await asyncio.wait_for(opensearch_client.cluster.health(), timeout=10.0)
            logger.debug("Final cluster health check completed")
        except TimeoutError:
            logger.warning("Timeout during final cluster health check")
        except Exception as e:
            logger.debug("[OPENSEARCH] Final cluster health check skipped", reason=str(e))

        # Close the client connection
        await opensearch_client.close()
        logger.info("OpenSearch client connection closed gracefully")

    except Exception as e:
        logger.error("Error during graceful OpenSearch shutdown", error=str(e))


async def setup_opensearch_security(
    opensearch_client: AsyncOpenSearch,
    admin_username: str | None = None,
) -> None:
    """Setup OpenSearch roles and roles mapping.

    The setup involves:
    1. GET /_plugins/_security/api/rolesmapping (check existing)
    2. GET /_cluster/health
    3. PUT and verify additive roles/mappings, including openrag_user_acl_role.
    4. PUT narrowed legacy roles/mappings, preserving existing mapping principals.
    5. PUT /_plugins/_security/api/rolesmapping/all_access (merge admin mapping).
    6. Verify updated legacy roles/mappings with final GETs.

    Args:
        opensearch_client: Authenticated OpenSearch client.
        admin_username: OpenSearch username of the onboarding user (IBM mode).
            When provided, this user is pinned into the all_access role mapping's
            ``users`` list so they retain admin access after ``backend_roles``
            are modified for DLS.

    This should be called during initial setup after OpenSearch is ready.
    """
    from config.settings import IBM_AUTH_ENABLED, PLATFORM_AUTH_DEV_MODE

    if IBM_AUTH_ENABLED and PLATFORM_AUTH_DEV_MODE:
        logger.info("Skipping OpenSearch security configuration in IBM dev mode.")
        return

    logger.info("Initializing OpenSearch security configuration...", ibm_auth=IBM_AUTH_ENABLED)

    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if IBM_AUTH_ENABLED:
        security_config_dir = os.path.join(base_dir, "cloud_securityconfig")
    else:
        security_config_dir = os.path.join(base_dir, "securityconfig")

    logger.info("[OPENSEARCH] Using config directory", config_dir=security_config_dir)

    roles_file = os.path.join(security_config_dir, "roles.yml")
    roles_mapping_file = os.path.join(security_config_dir, "roles_mapping.yml")

    logger.info(
        "[OPENSEARCH] Configuration paths",
        base_dir=base_dir,
        security_config_dir=security_config_dir,
        roles_file=roles_file,
        roles_mapping_file=roles_mapping_file,
    )

    try:
        # 1. & 2. Readiness checks
        logger.info("[OPENSEARCH] Performing readiness checks...")

        rolesmapping_response: dict[str, Any] = {}
        try:
            rolesmapping_response = await opensearch_client.transport.perform_request(
                "GET", "/_plugins/_security/api/rolesmapping"
            )
            logger.info(
                "[OPENSEARCH] Current rolesmapping retrieved",
                count=len(rolesmapping_response)
                if isinstance(rolesmapping_response, dict)
                else "unknown",
            )
        except Exception as e:
            if _is_security_setup_skip_error(e):
                logger.warning(
                    "Skipping OpenSearch security configuration: "
                    "The cluster may not have the security plugin enabled or "
                    "the provided credentials do not have administrative permissions."
                )
                return
            logger.warning("[OPENSEARCH] Failed to get current rolesmapping", error=str(e))

        cluster_health = await opensearch_client.cluster.health()
        logger.info("[OPENSEARCH] Cluster health check passed", status=cluster_health.get("status"))

        # Load role definitions from YAML
        if not os.path.exists(roles_file):
            logger.error(f"[OPENSEARCH] Roles configuration file not found: {roles_file}")
            raise FileNotFoundError(f"Roles configuration file not found: {roles_file}")

        with open(roles_file) as f:
            roles_config = yaml.safe_load(f)

        logger.info(
            "[OPENSEARCH] Loaded roles configuration",
            roles=list(roles_config.keys()) if roles_config else [],
        )

        # Load roles mapping from YAML
        if not os.path.exists(roles_mapping_file):
            logger.error(f"[OPENSEARCH] Roles mapping file not found: {roles_mapping_file}")
            raise FileNotFoundError(f"Roles mapping file not found: {roles_mapping_file}")

        with open(roles_mapping_file) as f:
            mapping_config = yaml.safe_load(f)

        logger.info(
            "[OPENSEARCH] Loaded roles mapping configuration",
            mappings=list(mapping_config.keys()) if mapping_config else [],
        )

        role_names = [role_name for role_name in roles_config if not role_name.startswith("_")]
        pre_legacy_role_names = [
            role_name for role_name in role_names if role_name != OPENRAG_USER_ROLE
        ]
        ordered_role_names = pre_legacy_role_names + [
            role_name for role_name in role_names if role_name == OPENRAG_USER_ROLE
        ]

        mapping_names = [
            mapping_name
            for mapping_name in mapping_config
            if not mapping_name.startswith("_") and mapping_name != ALL_ACCESS_ROLE
        ]
        pre_legacy_mapping_names = [
            mapping_name for mapping_name in mapping_names if mapping_name != OPENRAG_USER_ROLE
        ]
        ordered_mapping_names = pre_legacy_mapping_names + [
            mapping_name for mapping_name in mapping_names if mapping_name == OPENRAG_USER_ROLE
        ]

        def merged_mapping_body(mapping_name: str) -> dict[str, Any]:
            configured = copy.deepcopy(mapping_config[mapping_name])
            existing_same = rolesmapping_response.get(mapping_name, {})
            if mapping_name == OPENRAG_USER_ACL_ROLE:
                existing_legacy = rolesmapping_response.get(OPENRAG_USER_ROLE, {})
                return _merge_role_mappings(configured, existing_legacy, existing_same)
            if mapping_name == OPENRAG_USER_ROLE:
                return _merge_role_mappings(configured, existing_same)
            return _merge_role_mappings(configured, existing_same)

        async def put_role(role_name: str) -> None:
            role_body = roles_config[role_name]
            logger.info(
                f"[OPENSEARCH] Creating/updating '{role_name}' role",
                patterns=role_body["index_permissions"][0]["index_patterns"]
                if "index_permissions" in role_body
                else "default",
                allowed_actions=role_body["index_permissions"][0].get("allowed_actions", [])
                if "index_permissions" in role_body
                else [],
            )

            resp = await opensearch_client.transport.perform_request(
                "PUT",
                f"/_plugins/_security/api/roles/{role_name}",
                body=role_body,
                headers={"Content-Type": "application/json"},
            )
            logger.info(f"[OPENSEARCH] Role '{role_name}' creation response", response=resp)

        async def verify_role(role_name: str) -> None:
            role_verify = await opensearch_client.transport.perform_request(
                "GET", f"/_plugins/_security/api/roles/{role_name}"
            )
            logger.info("[OPENSEARCH] Role verification", role_name=role_name, role=role_verify)

        async def put_mapping(mapping_name: str) -> None:
            mapping_body = merged_mapping_body(mapping_name)
            logger.info(
                f"[OPENSEARCH] Creating/updating '{mapping_name}' mapping",
                backend_roles=mapping_body.get("backend_roles", []),
                users=mapping_body.get("users", []),
                hosts=mapping_body.get("hosts", []),
            )
            resp = await opensearch_client.transport.perform_request(
                "PUT",
                f"/_plugins/_security/api/rolesmapping/{mapping_name}",
                body=mapping_body,
                headers={"Content-Type": "application/json"},
            )
            logger.info(
                f"[OPENSEARCH] Role mapping '{mapping_name}' update response", response=resp
            )

        async def verify_mapping(mapping_name: str) -> None:
            mapping_verify = await opensearch_client.transport.perform_request(
                "GET", f"/_plugins/_security/api/rolesmapping/{mapping_name}"
            )
            logger.info(
                "[OPENSEARCH] Role mapping verification",
                mapping_name=mapping_name,
                mapping=mapping_verify,
            )

        # Apply and verify the additive ACL role/mapping before narrowing the
        # legacy role. This avoids losing shared-document access if a later
        # security API call fails during upgrade.
        for role_name in pre_legacy_role_names:
            await put_role(role_name)
        for mapping_name in pre_legacy_mapping_names:
            await put_mapping(mapping_name)
        for role_name in pre_legacy_role_names:
            await verify_role(role_name)
        for mapping_name in pre_legacy_mapping_names:
            await verify_mapping(mapping_name)

        for role_name in ordered_role_names:
            if role_name in pre_legacy_role_names:
                continue
            await put_role(role_name)
        for mapping_name in ordered_mapping_names:
            if mapping_name in pre_legacy_mapping_names:
                continue
            await put_mapping(mapping_name)

        # 5. Update all_access mapping — merge with existing to preserve
        # IBM-managed entries, but ensure backend_roles never contains
        # "all_access" (which would give IBM API key users the super-admin
        # role and bypass DLS).
        if ALL_ACCESS_ROLE in mapping_config:
            all_access_body = copy.deepcopy(mapping_config[ALL_ACCESS_ROLE])

            if "backend_roles" not in all_access_body:
                all_access_body["backend_roles"] = ["admin"]
            if "description" not in all_access_body:
                all_access_body["description"] = "Maps admin to all_access"

            # Always fetch existing mapping first so we never lose previous admins
            # in multi-tenant deployments where each tenant onboards independently.
            existing_users: list = []
            existing_hosts: list = []
            existing_backend_roles: list = []
            try:
                existing = await opensearch_client.transport.perform_request(
                    "GET", "/_plugins/_security/api/rolesmapping/all_access"
                )
                existing_mapping = existing.get(ALL_ACCESS_ROLE, {})
                existing_users = existing_mapping.get("users", []) or []
                existing_hosts = existing_mapping.get("hosts", []) or []
                existing_backend_roles = existing_mapping.get("backend_roles", []) or []
            except Exception as e:
                if not _is_not_found_error(e):
                    raise
                logger.debug("[OPENSEARCH] No existing all_access mapping found, creating fresh")

            # Build merged users: source file + cluster + new admin (bare + ibmlhapikey_ variant).
            # Adding both variants ensures the user can authenticate via JWT *and* via IBM
            # Basic-Auth (ibmlhapikey_<username>), which are treated as separate principals
            # by OpenSearch's security plugin.
            new_admin_users: list = []
            if IBM_AUTH_ENABLED and admin_username:
                new_admin_users = [admin_username, f"ibmlhapikey_{admin_username}"]
                logger.info(
                    "[OPENSEARCH] Pinning onboarding user as admin (both variants)",
                    users=new_admin_users,
                )

            merged_users = _dedupe_preserving_order(
                all_access_body.get("users", []) + existing_users + new_admin_users
            )
            all_access_body["users"] = merged_users
            logger.debug("[OPENSEARCH] Merged all_access users", users=merged_users)

            if existing_hosts:
                merged_hosts = _dedupe_preserving_order(
                    all_access_body.get("hosts", []) + existing_hosts
                )
                all_access_body["hosts"] = merged_hosts
                logger.debug(
                    "[OPENSEARCH] Preserved existing all_access hosts",
                    hosts=merged_hosts,
                )

            if existing_backend_roles:
                safe_existing_backend_roles = [
                    r for r in existing_backend_roles if r != "all_access"
                ]
                merged_backend_roles = _dedupe_preserving_order(
                    all_access_body.get("backend_roles", []) + safe_existing_backend_roles
                )
                all_access_body["backend_roles"] = merged_backend_roles
                logger.debug(
                    "[OPENSEARCH] Preserved existing all_access backend_roles",
                    backend_roles=merged_backend_roles,
                )

            if "all_access" in all_access_body.get("backend_roles", []):
                all_access_body["backend_roles"] = [
                    r for r in all_access_body["backend_roles"] if r != "all_access"
                ]
                logger.info(
                    "[OPENSEARCH] Removed 'all_access' from all_access backend_roles to preserve DLS",
                    final_backend_roles=all_access_body["backend_roles"],
                )

            logger.info("[OPENSEARCH] Updating 'all_access' mapping...", body=all_access_body)
            resp = await opensearch_client.transport.perform_request(
                "PUT",
                "/_plugins/_security/api/rolesmapping/all_access",
                body=all_access_body,
                headers={"Content-Type": "application/json"},
            )
            logger.info("[OPENSEARCH] All access mapping update response", response=resp)

        # 6. Final verification
        logger.info("[OPENSEARCH] Verifying security configuration...")
        for role_name in ordered_role_names:
            if role_name in pre_legacy_role_names:
                continue
            await verify_role(role_name)
        for mapping_name in ordered_mapping_names:
            if mapping_name in pre_legacy_mapping_names:
                continue
            await verify_mapping(mapping_name)

        logger.info("Successfully completed OpenSearch security configuration.")

    except Exception as e:
        logger.error("Failed to setup OpenSearch security configuration", error=str(e))
        raise
