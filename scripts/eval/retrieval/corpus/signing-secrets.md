# Signing secrets and signature verification

Anyone who learns your endpoint URL can post data to it. To let you tell real deliveries from forged ones, Relaywise signs every request it sends with a secret that only you and Relaywise know. Your endpoint recomputes the signature and rejects requests where it does not match.

Signing secrets are not API keys. An API key identifies you to Relaywise. A signing secret proves to you that a request came from Relaywise.

## The signature header

Each delivery carries two headers:

```
Relaywise-Timestamp: 1767225600
Relaywise-Signature: v1=5f2b7c0e9a...
```

The signature is an HMAC-SHA256 digest, written in lowercase hexadecimal. The signed message is the timestamp, a full stop, and the exact raw request body:

```
<timestamp>.<raw body>
```

## Verifying a delivery

1. Read the raw body as bytes, before any JSON parsing. Parsing and re-serialising changes whitespace and key order, and the signature will no longer match.
2. Build the signed message from the timestamp header and the raw body.
3. Compute the HMAC-SHA256 of that message using the destination's signing secret.
4. Compare your result with the value after `v1=` using a constant-time comparison.
5. Reject the request if the timestamp is more than five minutes old. This limits replay attacks, where someone captures a valid request and sends it again later.

A request that fails verification should get a `401` response. Relaywise treats a 401 like any other failed delivery and retries it.

## Where to find the secret

Each destination has its own secret, which starts with `whsec_`. Open the destination, go to **Settings → Signing**, and select **Reveal**. Revealing a secret is recorded in the audit log.

## Rolling a signing secret

Change a signing secret when someone who knew it leaves the team, or when it may have been exposed.

1. Open the destination's **Signing** settings and select **Roll secret**.
2. Relaywise creates a new secret. For the next 72 hours every delivery carries two signatures in the header, one made with each secret, separated by a comma.
3. Update your endpoint to use the new secret. Because both signatures are present, your endpoint keeps accepting deliveries whichever secret it holds during the changeover.
4. After 72 hours the previous secret is discarded and deliveries carry a single signature again.

The 72-hour dual-signature period is fixed and cannot be shortened. If the old secret is known to be compromised, select **Expire previous secret** to drop it at once.

## Common mistakes

- **Verifying the parsed body.** Frameworks that parse JSON automatically often discard the raw bytes. Configure the route to keep them.
- **Clock drift.** If your server clock is wrong by more than five minutes, every delivery looks like a replay. Keep time synchronised.
- **Using the wrong destination's secret.** Secrets are per destination, not per workspace.
- **Comparing with `==`.** Ordinary string comparison leaks timing information. Use the constant-time function from your language's standard library.
