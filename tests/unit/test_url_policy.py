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
