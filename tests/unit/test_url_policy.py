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


@pytest.mark.parametrize(
    ("address", "expected"),
    [
        ("8.8.8.8", True),
        ("127.0.0.1", False),
        ("10.0.0.5", False),
        ("169.254.169.254", False),
        ("100.64.0.1", False),
        ("::ffff:10.0.0.1", False),
        # NAT64 well-known prefix: judged by the IPv4 address it reaches.
        ("64:ff9b::7f00:1", False),  # 127.0.0.1
        ("64:ff9b::a00:1", False),  # 10.0.0.1
        ("64:ff9b::a9fe:a9fe", False),  # 169.254.169.254, cloud metadata
        ("64:ff9b::808:808", True),  # 8.8.8.8
        # NAT64 local-use prefix maps wherever the operator chooses.
        ("64:ff9b:1::808:808", False),
        ("2606:4700:4700::1111", True),
    ],
)
def test_public_ip_judges_nat64_addresses_by_their_ipv4_destination(address, expected):
    assert policy.public_ip(address) is expected


def test_a_hostname_resolving_into_nat64_toward_a_private_network_is_rejected(monkeypatch):
    monkeypatch.setattr(
        policy.socket,
        "getaddrinfo",
        lambda *args, **kwargs: [(None, None, None, "", ("64:ff9b::a00:1", 443, 0, 0))],
    )

    with pytest.raises(policy.CrawlPolicyError, match="public addresses"):
        policy.resolve_public_addresses("internal.example.com", 443)
