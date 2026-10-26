# Network security

This page describes the controls that decide which machines may talk to Relaywise on your behalf, and how you can be sure that traffic reaching your endpoints really comes from Relaywise.

## Encryption

All traffic to and from Relaywise is encrypted in transit with TLS 1.2 or newer. Older protocol versions are refused. Stored event payloads, transformation secrets and backups are encrypted at rest with AES-256, using keys that are rotated every 90 days.

On the Enterprise plan you can supply your own encryption key from a key management service that you control. If you withdraw the key, Relaywise can no longer read the stored payloads of that workspace.

## Restricting who can send events

By default any machine that holds a valid API key can send events. To narrow this, set an ingest allowlist under **Settings → Security → Ingest allowlist**, or with the `ingest.allowed_ips` setting. Enter one or more address ranges in CIDR notation, for example `203.0.113.0/24`.

Once the allowlist has at least one entry, requests from any other address are refused before the API key is even checked. Add the new range first and remove the old one afterwards when your addresses change, or you will lock out your own senders.

## Restricting who can use the console

A separate console allowlist limits where members can log in from, which is useful for requiring the company network or VPN. It is set under **Settings → Security → Console allowlist**. Owners are exempt, so that a mistake in the list cannot lock everyone out.

## Allowing Relaywise through your firewall

Deliveries are sent from a fixed, published set of addresses for each region. If your endpoint is behind a firewall, allow those addresses and block everything else. Find them on the **Network** page or with `rwctl network egress-ips`.

Do not rely on the firewall alone. Addresses prove where a request came from, not that it is genuine. Verify the signature on every delivery as well.

## Mutual TLS

For endpoints that require the caller to present a certificate, turn on mutual TLS for the destination. Relaywise then presents a client certificate with each delivery. Download the certificate authority bundle from the destination's **Security** tab and configure your server to trust it. Client certificates are renewed every 60 days, and the new certificate is signed by the same authority, so nothing has to change on your side.

## Private connectivity

On the Enterprise plan, deliveries can reach endpoints that have no public address through a private link between Relaywise and your cloud network. This is also the only way to deliver to private address ranges. Without it, a destination URL that resolves to a private address is rejected with error `RW-2031`.

## Two-factor authentication

Members who log in with a password can add a second factor, using an authenticator app or a hardware security key. Admins can make this compulsory for the whole workspace under **Settings → Security → Require two-factor**. Members without a second factor are then asked to set one up at their next login. Members who log in through single sign-on follow the identity provider's own rules instead.

## Independent assurance

Relaywise is audited every year by an independent firm against a widely used security standard for service providers. The current report is available to customers and serious prospects under a confidentiality agreement; request it from support. An external firm also carries out a penetration test once a year, and a summary of the findings is available on the same terms.

A data processing agreement is included in the terms for every paid plan. No separate signature is needed, though a countersigned copy can be requested.

## Reporting a vulnerability

If you believe you have found a security weakness in Relaywise, email the security team at the address given on the security page of the website. Reports are acknowledged within two working days. Please allow time for a fix before publishing details.
