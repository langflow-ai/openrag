# Rate limits and size limits

Relaywise limits how fast each workspace can send events and call the management API. The limits protect the service as a whole and stop a runaway loop in one of your systems from using up your monthly quota in an afternoon.

## Ingest limits

The ingest limit is counted in events per second, across all sources in the workspace.

| Plan | Sustained ingest rate |
|---|---|
| Sandbox | 10 events per second |
| Team | 200 events per second |
| Scale | 2,000 events per second |
| Enterprise | Set by contract |

Short spikes are allowed. For up to 10 seconds a workspace may send at twice its sustained rate. After that, requests above the limit are rejected until the average falls back under it.

## Management API limits

Calls that read or change configuration, list events or start replays are limited to 600 requests per minute for each API key. This limit is the same on every plan.

## What a rejected request looks like

A request over the limit gets the status `429 Too Many Requests` and error code `RW-4290`. The event is not accepted, so your code has to send it again.

Every response, whether accepted or rejected, includes these headers:

```
Relaywise-RateLimit-Limit: 200
Relaywise-RateLimit-Remaining: 0
Relaywise-RateLimit-Reset: 1767225612
```

`Reset` is the Unix time at which more capacity becomes available. A rejected response also carries a standard `Retry-After` header giving the same moment as a number of seconds.

## Handling 429 responses well

- Wait until the reset time before trying again. Retrying at once only prolongs the problem.
- Add a small random delay so that many workers do not all resume together.
- Put a queue in front of your sender if you produce events in bursts.
- Use the batch endpoint when you have many events to send at once.

The official client libraries do all of this for you. They retry a rate-limited request up to five times before giving up.

## Batching

The batch endpoint accepts up to 500 events in one request. A batch is one HTTP request, but every event inside it counts towards the events-per-second limit. Batching reduces connection overhead; it is not a way around the ingest limit.

If part of a batch would go over the limit, the whole batch is rejected. Relaywise never accepts half of a batch.

## Size limits

| Item | Limit |
|---|---|
| One event payload | 256 KB |
| One batch request | 5 MB |
| Custom headers on a destination | 20 headers, 8 KB in total |
| Event type name | 128 characters |

A payload over 256 KB is rejected with error `RW-4130`. If you need to move something bigger, store it elsewhere and send a link to it in the event.

## Monthly quota is a separate thing

The rate limit controls how fast you send. The monthly quota controls how much you send in a billing period. Reaching the monthly quota produces a different error, `RW-4291`, and waiting a few seconds does not clear it. On paid plans events over the quota are accepted and billed as overage, unless you have set a hard cap.

## Asking for a higher limit

Workspaces on the Scale plan can request a temporary increase for a planned event such as a product launch or a data migration. Open a support ticket at least three working days ahead, and say what peak rate you expect and for how long.
