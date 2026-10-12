# Data retention and deletion

Relaywise stores the events you send so that you can inspect them, debug deliveries and replay them. This page explains what is stored, for how long, and how to remove it sooner.

## What is stored

For each event Relaywise keeps two kinds of record:

- **Payload.** The body of the event, exactly as it was received, and the body after any transformation.
- **Metadata.** Event ID, type, size, source, the time it was received, and one record per delivery attempt with its status code, duration and error code.

The two are kept for different lengths of time. Metadata is small and useful for spotting trends, so it is kept longer. Payloads can contain personal data, so they are kept for a shorter time.

## Retention by plan

| Plan | Payloads | Metadata |
|---|---|---|
| Sandbox | 3 days | 7 days |
| Team | 14 days | 30 days |
| Scale | 30 days | 90 days |
| Enterprise | 90 days | 400 days |

These are maximums. You can choose shorter periods with the `retention.payload_days` and `retention.metadata_days` settings. Some teams set payload retention to a single day to keep as little personal data as possible.

Once a payload has expired, the event still appears in the history with its metadata, but its body cannot be viewed and the event cannot be replayed. A replay attempt returns error `RW-6001`.

## Storing less in the first place

If a field should never be stored at all, add its path to `retention.redact_fields`. Relaywise replaces the value with `[redacted]` before the event is written to storage. The endpoint still receives the original value, because redaction changes only the stored copy.

To remove a field from what is delivered as well, use a transformation.

## Deleting events on request

To delete particular events before they expire, for example to honour a request from a person to erase their data, use the deletion API or the console:

- **One event.** Open the event and select **Delete payload**.
- **By filter.** Under **Settings → Data → Delete events**, enter a time range and optionally a payload field and value, such as `data.customer_id` equal to `C-2291`.

Deletion removes payloads at once from the primary store. Copies in encrypted backups age out within 35 days. Metadata is kept unless you also tick **Delete metadata**. Every deletion is written to the audit log with the filter that was used; the deleted content itself is not recorded.

## Exporting before deletion

If you need events for longer than your plan keeps them, export them. A scheduled export writes new events to a storage bucket that you own, every hour, as compressed JSON Lines files. Set it up under **Settings → Data → Export**. Exports are available on the Scale and Enterprise plans.

For a single download, **Events → Export** produces a file of up to one million events matching the current filter.

## When a workspace is closed

When you delete a workspace, ingest stops immediately. All payloads and metadata are deleted within 7 days, and backups age out within 35 days after that. Invoices are kept for as long as accounting law requires.

A closed workspace cannot be restored once the 7 days have passed. Within the 7 days, an Owner can ask support to reopen it.

## What retention does not cover

- The dead-letter queue has its own time limits, counted separately.
- Audit log entries follow the audit log's retention, not the event retention.
- Metric charts are built from aggregated numbers, not from stored events, and stay available longer.
