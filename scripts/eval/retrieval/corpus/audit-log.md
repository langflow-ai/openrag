# Audit log

The audit log is a record of who did what in a workspace. It answers questions such as "who revoked that key?", "when was this destination's URL changed?" and "has anyone looked at customer payloads this month?".

The audit log is about actions taken by people and API keys. It is not a log of events or deliveries; those are in the event history.

## What is recorded

Each entry holds the time, the actor, the action, the thing that was acted on, the IP address the request came from, and whether the action succeeded. The actor is a member, an API key or Relaywise support.

| Area | Example actions |
|---|---|
| Members | `member.invited`, `member.removed`, `member.role_changed` |
| API keys | `key.created`, `key.rotated`, `key.revoked` |
| Signing | `secret.revealed`, `secret.rolled` |
| Configuration | `destination.created`, `destination.url_changed`, `route.deleted`, `transformation.activated` |
| Data access | `payload.viewed`, `events.exported`, `events.deleted` |
| Security | `sso.enabled`, `sso.enforced`, `login.failed`, `ip_allowlist.changed` |
| Billing | `plan.changed`, `usage_cap.changed` |

Entries describe changes without holding secrets. An entry for a rolled signing secret states that the roll happened; it does not contain the old or the new secret.

## Who can read it

Owners and Admins can read the audit log. Developers and Viewers cannot. On the Enterprise plan, a custom role can be given read access to the audit log and nothing else, which suits an auditor or a security reviewer.

## Finding entries

Open **Settings → Audit log**. Filter by actor, action, target or time range. Typing a destination ID into the search box lists everything that has happened to that destination.

## How long entries are kept

| Plan | Audit log kept for |
|---|---|
| Sandbox | 30 days |
| Team | 1 year |
| Scale | 1 year |
| Enterprise | 7 years |

This is separate from event retention. Shortening how long payloads are kept has no effect on the audit log.

## Entries cannot be changed

Nobody can edit or delete an audit log entry, including Owners and Relaywise staff. Each entry includes a hash of the entry before it, so removing or altering one would break the chain and be detectable. Use **Verify integrity** on the audit log page to check a time range.

## Exporting

Select **Export** to download the entries matching the current filter as CSV or JSON. One export can hold up to 500,000 entries.

For continuous export, the Enterprise plan can stream audit entries to a Relaywise destination or to a storage bucket you own, typically within a minute of the action. Security teams use this to feed their own log analysis tools.

## Actions by Relaywise support

Support staff cannot see your payloads or change your configuration by default. If you ask them to investigate something, an Owner grants time-limited access under **Settings → Security → Support access**, for between 1 hour and 7 days. Everything support does during that time appears in the audit log with the actor shown as `support`, together with the ticket number.

## Useful checks

- **Monthly:** review `key.created` and `member.role_changed` for anything unexpected.
- **After someone leaves:** search for their name to see which keys and secrets they created or revealed.
- **After an incident:** filter by the time range and the affected destination to rebuild the sequence of changes.
