import pytest

from connectors.url import policy


def test_resolved_addresses_are_normalized_to_strings(monkeypatch):
    class Address:
        def __str__(self) -> str:
            return "8.8.8.8"

    seen: list[str] = []
    monkeypatch.setattr(
        policy.socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [(None, None, None, None, (Address(), 443))],
    )
    monkeypatch.setattr(policy, "public_ip", lambda address: seen.append(address) or True)

    addresses = policy.resolve_public_addresses("docs.example.com", 443)

    assert addresses == ("8.8.8.8",)
    assert seen == ["8.8.8.8"]


@pytest.mark.parametrize(
    "path",
    [
        "/%2e%2e/private",
        "/%2E%2E/private",
        "/%2Fprivate",
        "/%5cprivate",
        "/%255cprivate",
        "/%252e%252e/private",
    ],
)
def test_canonicalize_url_rejects_ambiguous_encoded_paths(path):
    with pytest.raises(policy.CrawlPolicyError):
        policy.canonicalize_url(f"https://docs.example.com{path}")


def test_path_scope_include_paths_cannot_expand_past_seed_path():
    spec = policy.CrawlSpec(
        seed_url="https://docs.example.com/guides",
        scope="path",
        include_paths=("/guides", "/admin"),
    )

    assert spec.allows("https://docs.example.com/guides/getting-started") is True
    assert spec.allows("https://docs.example.com/admin") is False
