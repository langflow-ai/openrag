
import httpx


_DEFAULT_K8S_SA_TOKEN_PATH = "/var/run/secrets/kubernetes.io/serviceaccount/token"


# Read the K8S service account token
def _read_k8s_sa_token(k8s_sa_token_path: str) -> str | None:
    try:
        with open(k8s_sa_token_path) as f:
            return f.read().strip() or None
    except (FileNotFoundError, PermissionError):
        return None


def get_opensearch_service_token(
    auth_server_url: str | None,
    tenant_id: str,
    k8s_sa_token_path: str = _DEFAULT_K8S_SA_TOKEN_PATH,
) -> str | None:
    """
    Fetch an OpenSearch service token from the internal auth server using the current K8S service account token.

    Args:
        tenant_id (str): The tenant ID for which the token is requested.

    Returns:
        str | None: The raw OpenSearch token if successful, else None.
    """
    if not auth_server_url:
        return None

    token_endpoint = f"{auth_server_url.rstrip('/')}/internal/token/opensearch"
    try:
        # Read the K8S service account token
        k8s_token = _read_k8s_sa_token(k8s_sa_token_path)
        if not k8s_token:
            return None

        headers = {
            "Authorization": f"Bearer {k8s_token}",
            "Content-Type": "application/json",
        }
        json_body = {"tenant_id": tenant_id}

        # Verify is False for cluster-local/internal endpoints; see original curl -k
        with httpx.Client(verify=False, timeout=10) as client:
            resp = client.post(token_endpoint, headers=headers, json=json_body)
            resp.raise_for_status()
            data = resp.json()
            return data.get("token")
    except Exception:
        return None
