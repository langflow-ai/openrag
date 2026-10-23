"""Amazon Bedrock - chat and embeddings through LiteLLM's own `bedrock` provider.

There is no new transport here and the key is LiteLLM's, so no route alias. The
module exists for what a bare `model_providers.yaml` row would get wrong:

- **The form.** LiteLLM's published Bedrock form has ten optional fields whose
  tooltips advertise `os.environ/VAR` references that OpenRAG never expands, and
  it leaves the region optional, so a missing one silently becomes `us-west-2`.
  Here the region is required and the secret access key is the only secret.
- **Ambient identity.** With the key fields blank, boto3 falls back to its
  default chain (IRSA, instance profile, `AWS_*` environment). A region-only
  form is therefore a complete, configured provider.
- **A model-free health check.** `sts:GetCallerIdentity` needs no IAM permission
  and bills nothing, so the polled health check never runs inference. It proves
  the identity is valid, not that it may call Bedrock (no `bedrock:InvokeModel`
  permission or no model access in the region still passes), and it checks the
  boto3 identity, which LiteLLM can override from `AWS_SESSION_TOKEN`,
  `AWS_ROLE_NAME` and friends. If STS times out on connect (a VPC with only a
  Bedrock endpoint), that says nothing about the credentials, so the save is not
  blocked. A DNS failure is not that case: it means the region is mistyped.

Field names are LiteLLM's own kwargs, so the stored values go straight to
`litellm.acompletion` / `aembedding`. Nothing is written to `os.environ`: the
region travels with every call.

Nothing here imports OpenRAG config - `config_manager`, `model_catalog` and
`llm_gateway` all read this module, so it has to stay a leaf.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any

from utils.logging_config import get_logger

logger = get_logger(__name__)

PROVIDER_KEY = "bedrock"

_IDENTITY_TOOLTIP = (
    "Leave blank to use the backend's IAM role (IRSA, instance profile) or AWS_* environment"
)

# The access key ID is an identifier, not a secret, so it is a plain text field:
# the settings dialog only offers removal for those, and clearing it is how an
# operator goes back from static keys to the IAM role (see
# `ProvidersConfig.set_credentials`, which then drops the secret with it).
CREDENTIAL_FIELDS: list[dict[str, Any]] = [
    {
        "key": "aws_region_name",
        "label": "AWS region",
        "placeholder": "us-east-1",
        "tooltip": "Region whose Bedrock endpoint serves your models.",
        "required": True,
        "field_type": "text",
    },
    {
        "key": "aws_access_key_id",
        "label": "Access key ID",
        "tooltip": _IDENTITY_TOOLTIP + ". Clear it and save to go back to the role.",
        "required": False,
        "field_type": "text",
    },
    {
        "key": "aws_secret_access_key",
        "label": "Secret access key",
        "tooltip": "Saved with the access key ID; entering a new ID replaces it.",
        "required": False,
        "field_type": "password",
    },
]

#: Seconds each way to STS. A health check must not hang a settings save.
_STS_TIMEOUT_SECONDS = 5


def litellm_credentials(stored: Mapping[str, Any]) -> dict[str, str]:
    """The stored form with blanks dropped; its keys are already LiteLLM's kwargs."""
    return {
        name: value.strip()
        for name, value in (stored or {}).items()
        if isinstance(value, str) and value.strip()
    }


async def lightweight_health_check(credentials: Mapping[str, Any]) -> None:
    """Validate the region and identity without selecting a model.

    Failures are `ValueError`s naming what is wrong. They carry an AWS error
    *code* at most, never AWS's message text or any submitted value.
    """
    from botocore.exceptions import ConnectTimeoutError, EndpointConnectionError

    values = litellm_credentials(credentials)
    region = values.get("aws_region_name")
    if not region:
        raise ValueError("No AWS region is configured for Amazon Bedrock")
    try:
        await asyncio.to_thread(_get_caller_identity, values, region)
    except ValueError:
        raise
    except ConnectTimeoutError:
        logger.warning("Could not reach AWS STS; saving without the identity check", region=region)
        return
    except EndpointConnectionError:
        # A mistyped region is a DNS failure, not a timeout, so it must not pass.
        raise ValueError("Could not reach AWS in this region. Check the region name.") from None
    except Exception as exc:
        raise ValueError(_describe(exc)) from None
    logger.info("Amazon Bedrock health check passed", region=region)


def _get_caller_identity(values: Mapping[str, str], region: str) -> None:
    import boto3
    from botocore.config import Config

    keys = {
        name: values[name]
        for name in ("aws_access_key_id", "aws_secret_access_key")
        if name in values
    }
    boto3.session.Session().client(
        "sts",
        region_name=region,
        config=Config(
            connect_timeout=_STS_TIMEOUT_SECONDS,
            read_timeout=_STS_TIMEOUT_SECONDS,
            retries={"max_attempts": 1},
        ),
        **keys,
    ).get_caller_identity()


def _describe(exc: Exception) -> str:
    from botocore.exceptions import ClientError, NoCredentialsError, PartialCredentialsError

    if isinstance(exc, PartialCredentialsError):
        return "Enter both the access key ID and the secret access key"
    if isinstance(exc, NoCredentialsError):
        return (
            "No AWS credentials were found. Enter an access key and secret, or run OpenRAG "
            "with an IAM role (IRSA, instance profile) or AWS_* environment variables."
        )
    if isinstance(exc, ClientError):
        code = exc.response.get("Error", {}).get("Code", "Unknown")
        return f"AWS rejected the credentials ({code})"
    return f"The AWS credentials could not be checked ({type(exc).__name__})"
