"""Deployment-config tests for the AWS Bedrock backend env vars.

`config_manager._load_env_overrides` reads BEDROCK_REGION,
BEDROCK_ACCESS_KEY_ID and BEDROCK_SECRET_ACCESS_KEY. docker-compose.yml has
no `env_file:` directive for openrag-backend, so a variable that is not
listed in that service's `environment:` block never reaches the process -
Bedrock silently stayed unconfigurable in every containerized deployment.
The Helm chart and the operator have the same per-variable allowlist shape.

Mirrors the deployment-config assertions in test_langflow_ingest_callback.py.
"""

from pathlib import Path

import pytest
import yaml

BEDROCK_ENV_VARS = (
    "BEDROCK_REGION",
    "BEDROCK_ACCESS_KEY_ID",
    "BEDROCK_SECRET_ACCESS_KEY",
)


def _config_manager_bedrock_env_names() -> set[str]:
    """The env var names config_manager actually reads, straight from source,
    so this test can't drift away from the code it is guarding."""
    source = Path("src/config/config_manager.py").read_text(encoding="utf-8")
    return {name for name in BEDROCK_ENV_VARS if f'os.getenv("{name}")' in source}


def test_env_var_names_match_config_manager():
    assert _config_manager_bedrock_env_names() == set(BEDROCK_ENV_VARS)


def test_docker_compose_backend_receives_bedrock_env_vars():
    compose = yaml.safe_load(Path("docker-compose.yml").read_text(encoding="utf-8"))
    backend = compose["services"]["openrag-backend"]

    # No env_file: means the environment block is the only channel in.
    assert "env_file" not in backend

    declared = {entry.split("=", 1)[0] for entry in backend["environment"]}
    for variable_name in BEDROCK_ENV_VARS:
        assert variable_name in declared


def test_docker_compose_reads_bedrock_vars_from_the_host_environment():
    compose_text = Path("docker-compose.yml").read_text(encoding="utf-8")

    for variable_name in BEDROCK_ENV_VARS:
        assert f"{variable_name}=${{{variable_name}}}" in compose_text


def test_env_example_documents_the_bedrock_vars():
    env_example = Path(".env.example").read_text(encoding="utf-8")

    for variable_name in BEDROCK_ENV_VARS:
        assert f"{variable_name}=" in env_example


@pytest.mark.parametrize(
    "config_path",
    [
        "kubernetes/helm/openrag/templates/backend/backend-dotenv.yaml",
        "kubernetes/operator/internal/controller/env.go",
    ],
)
def test_kubernetes_deployments_declare_bedrock_env_vars(config_path):
    config_text = Path(config_path).read_text(encoding="utf-8")

    for variable_name in BEDROCK_ENV_VARS:
        assert f"{variable_name}=" in config_text or f'"{variable_name}":' in config_text


def test_helm_values_expose_the_bedrock_provider_knobs():
    values = yaml.safe_load(Path("kubernetes/helm/openrag/values.yaml").read_text(encoding="utf-8"))
    bedrock = values["llmProviders"]["bedrock"]

    assert set(bedrock) >= {"region", "accessKeyId", "secretAccessKey"}
    # Blank by default: that is IAM role / IRSA mode.
    assert bedrock["accessKeyId"] == ""
    assert bedrock["secretAccessKey"] == ""


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
