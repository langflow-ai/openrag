"""The health-cache key must accept everything ``check_provider_health`` sends.

A missing keyword here is not a quiet degradation: ``cache_key()`` is called
before any provider validation runs, so a ``TypeError`` there surfaces in the
UI as "<Provider> error - cache_key() got an unexpected keyword argument ..."
for whichever provider happens to be configured — i.e. it breaks the health
banner for every provider at once.
"""

import inspect

from api import provider_health
from utils import provider_health_cache


def _calls(function_name: str, callee: str) -> list[set[str]]:
    """Keyword names for each call to ``callee`` in ``function_name``'s source."""
    import ast

    source = inspect.getsource(getattr(provider_health, function_name))
    tree = ast.parse(inspect.cleandoc(source))
    calls: list[set[str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        attribute = func.attr if isinstance(func, ast.Attribute) else None
        plain = func.id if isinstance(func, ast.Name) else None
        if attribute != callee and plain != callee:
            continue
        calls.append({kw.arg for kw in node.keywords if kw.arg})
    return calls


def _call_kwargs(function_name: str, callee: str) -> set[str]:
    """Union of keyword names passed to ``callee``."""
    return set().union(*_calls(function_name, callee)) if _calls(function_name, callee) else set()


def test_cache_key_accepts_every_keyword_the_endpoint_passes():
    accepted = set(inspect.signature(provider_health_cache.cache_key).parameters)
    passed = _call_kwargs("check_provider_health", "cache_key")

    assert passed, "expected check_provider_health to call cache_key with keywords"
    assert passed <= accepted, f"cache_key() cannot accept: {sorted(passed - accepted)}"


def test_credentials_change_the_cache_key():
    """Rotating a generic provider's credentials must bust the cached verdict."""
    base = {
        "provider": "openai",
        "embedding_provider": "openai",
        "test_completion": False,
        "llm_model": "gpt-4o-mini",
        "embedding_model": "text-embedding-3-small",
        "endpoint": None,
        "project_id": None,
        "api_key": "sk-same",
    }

    unset = provider_health_cache.cache_key(**base)
    first = provider_health_cache.cache_key(**base, credentials={"api_key": "sk-one"})
    second = provider_health_cache.cache_key(**base, credentials={"api_key": "sk-two"})
    embedding = provider_health_cache.cache_key(
        **base, embedding_credentials={"api_key": "sk-one"}
    )

    assert first != second
    assert first != unset
    assert embedding != unset
    assert first != embedding


def test_credential_key_is_order_independent():
    base = {
        "provider": "custom",
        "embedding_provider": "custom",
        "test_completion": False,
        "llm_model": None,
        "embedding_model": None,
        "endpoint": None,
        "project_id": None,
        "api_key": None,
    }

    forward = provider_health_cache.cache_key(
        **base, credentials={"api_base": "https://x", "api_key": "k"}
    )
    reversed_ = provider_health_cache.cache_key(
        **base, credentials={"api_key": "k", "api_base": "https://x"}
    )

    assert forward == reversed_


def test_credentials_never_appear_in_plaintext_in_the_key():
    key = provider_health_cache.cache_key(
        provider="custom",
        embedding_provider="custom",
        test_completion=False,
        llm_model=None,
        embedding_model=None,
        endpoint=None,
        project_id=None,
        api_key=None,
        credentials={"api_key": "super-secret-value"},
    )

    assert "super-secret-value" not in key


def test_every_validation_call_forwards_credentials():
    """Generic providers carry their secrets only in ``credentials``.

    Covers the specific-provider branch too — it is what the providers page
    hits when you click Configure on a non-built-in provider, and it silently
    validated with no credentials at all before.
    """
    calls = _calls("check_provider_health", "validate_provider_setup")

    assert calls, "expected check_provider_health to call validate_provider_setup"
    missing = [index for index, kwargs in enumerate(calls) if "credentials" not in kwargs]
    assert not missing, f"validate_provider_setup call(s) {missing} drop credentials"
