# API keys

API keys authenticate requests your own code makes to Relaywise: sending events, managing destinations, reading delivery history. They are different from signing secrets, which Relaywise uses to sign the requests it sends to you.

## Key format

Every key starts with a prefix that tells you what kind of key it is:

| Prefix | Kind | Typical use |
|---|---|---|
| `rwk_live_` | Live key | Production traffic |
| `rwk_test_` | Test key | Development; events are accepted but never delivered outside the tunnel |
| `rwk_ci_` | Automation key | Pipelines and infrastructure tooling; cannot send events |

The full key is shown only once, at creation. Afterwards the console displays just the prefix and the last four characters.

## Creating a key

1. Open **Settings → API keys**.
2. Select **Create key**.
3. Name the key after the system that will use it, for example `checkout-backend`.
4. Choose scopes. Grant only what that system needs.
5. Optionally set an expiry date. Keys without an expiry stay valid until revoked.

Only members with the Admin or Owner role can create keys. Developers can see the list of keys but not create or revoke them.

## Scopes

| Scope | Allows |
|---|---|
| `events:write` | Posting events to a source |
| `events:read` | Listing events and reading delivery attempts |
| `destinations:manage` | Creating, updating and deleting destinations and routes |
| `replay:run` | Replaying events from history or from the dead-letter queue |
| `workspace:admin` | Managing members, keys and settings |

A request made with a key that lacks the required scope fails with error `RW-1403`.

## Rotating a key

Rotate a key on a schedule, and immediately if you suspect it has leaked. Rotation in Relaywise is designed so that you never need downtime:

1. In **Settings → API keys**, open the key and select **Rotate**.
2. Relaywise issues a replacement key with the same name and scopes. The old key keeps working during an overlap window, which is 24 hours by default.
3. Deploy the replacement key to every system that used the old one.
4. Check the **Last used** column. When the old key shows no recent use, select **Revoke now** to end the overlap early, or simply let the window run out.

You can change the overlap window to anything between 1 hour and 7 days when you start the rotation. If the key has definitely leaked, choose **Revoke immediately** instead of rotating; that skips the overlap entirely and the old key stops working at once.

From the command line the same operation is `rwctl keys rotate <key-name> --overlap 24h`.

## Revoking a key

Revoking is permanent. Requests that use a revoked key fail with error `RW-1401`. A revoked key cannot be restored; create a new one instead.

## Good practice

- Give each service its own key so that revoking one does not break the others.
- Store keys in a secret manager, not in source control or in a build log.
- Set an expiry on keys used by contractors and short-lived projects.
- Review the **Last used** column every quarter and revoke keys that have been idle for more than 90 days. Relaywise flags these with an **Idle** badge.
