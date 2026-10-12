# Payload transformations

A transformation is a small piece of JavaScript that runs on an event after it has passed the route's filter and before it is delivered. Use one when the receiving system expects a different shape from the one your application produces.

## What transformations are for

- Renaming or removing fields to match what the receiver expects.
- Removing sensitive fields that a particular destination should not see.
- Adding a computed field, such as a total or a formatted date.
- Setting custom HTTP headers for one delivery.
- Dropping events based on logic too involved for a filter.

## Writing one

A transformation exports a single function. It receives the event and a context object, and returns the payload to deliver.

```javascript
export default function transform(event, context) {
  const { card_number, ...safe } = event.data;
  return {
    ...safe,
    amount_formatted: (event.data.amount_cents / 100).toFixed(2),
    forwarded_by: "relaywise",
  };
}
```

Return `null` to drop the event for this route. A dropped event is recorded as **filtered by transformation** and is not treated as a failure.

Returning anything other than an object or `null` fails with error `RW-5004`.

## The context object

| Property | Contents |
|---|---|
| `context.headers` | Headers to send with the delivery. Add or change entries to set custom headers. |
| `context.destination` | The ID and name of the destination being delivered to. |
| `context.attempt` | The attempt number, starting at 1. |
| `context.secrets` | Read-only values stored under the route's **Secrets** tab. |

Put tokens and passwords in `context.secrets`; do not paste them into the code. Secrets are encrypted, never appear in logs, and are not included when a transformation is exported.

## The sandbox

Transformations run in an isolated sandbox with firm limits.

- **No network access.** The code cannot make HTTP requests or open sockets.
- **No file system and no clock tricks.** The code cannot read files, and timers are not available.
- **Time.** Each run has 250 milliseconds by default, configurable up to one second. Going over fails with `RW-5002`.
- **Memory.** Each run has 32 MB by default.
- **Output size.** The returned payload must be within the normal event size limit, or the run fails with `RW-5003`.

The transformation runs again on every delivery attempt, so it must give the same output for the same input. Do not rely on random numbers.

## When the code fails

If the function throws, the run fails with `RW-5001`. What happens next depends on the `transform.on_error` setting of the route:

- `dead_letter`, the default, moves the event to the dead-letter queue without attempting delivery. Fix the code and replay.
- `pass_through` delivers the original payload unchanged.
- `drop` discards the event for this route.

Choose `pass_through` only if the receiver can cope with both shapes.

## Testing

The editor has a **Run** panel. Paste a sample payload or pick a recent event, and the panel shows the output, the headers, anything written with `console.log`, and how long the run took. Log output is kept for 24 hours and capped at 4 KB per run.

## Versions and rollback

Every save creates a new version. The route always uses the version marked **active**. To undo a bad change, open **History**, choose an earlier version and select **Make active**. The switch applies to new deliveries within a few seconds. Relaywise keeps the last 50 versions of each transformation.

## Sharing code between routes

Save a transformation to the workspace library to use it on several routes. A change to a library transformation applies to every route that uses it, so test carefully, or copy it first if only one route needs the change.
