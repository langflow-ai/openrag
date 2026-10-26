# Delivery and retries

Endpoints fail. They get deployed, overloaded, misconfigured or cut off by a network fault. Relaywise assumes this will happen and keeps trying to deliver an event until it succeeds or the retry budget runs out.

## What counts as a successful delivery

A delivery succeeds when your endpoint answers with any status code from 200 to 299 before the timeout. The response body is ignored, so return as little as possible and return it quickly. Do the slow work after you have acknowledged the event.

Everything else is a failure: a 3xx redirect, a 4xx or 5xx status, a timeout, a refused connection, a TLS error or a DNS failure. Relaywise does not follow redirects.

## The default retry schedule

Each event gets up to 8 delivery attempts. The first attempt is made as soon as the event is accepted. If it fails, the waits before the following attempts are:

| Attempt | Wait since the previous attempt |
|---|---|
| 2 | 30 seconds |
| 3 | 2 minutes |
| 4 | 10 minutes |
| 5 | 1 hour |
| 6 | 3 hours |
| 7 | 8 hours |
| 8 | 15 hours |

Taken together the schedule covers a little over 27 hours. That is long enough to ride out an overnight outage without anyone having to step in.

Each wait is adjusted by a random amount of up to 20 percent in either direction. Without this jitter, every event that failed during an outage would be retried at the same instant, and the burst could knock the recovering endpoint over again.

## Changing the schedule

Retry behaviour is set per destination, under **Settings → Delivery**, or with these configuration keys:

- `delivery.max_attempts` sets the total number of attempts, from 1 to 20. The default is 8. A value of 1 disables retries.
- `delivery.backoff` chooses between `exponential`, which is the schedule above, and `fixed`.
- `delivery.fixed_interval_seconds` sets the wait when the backoff is `fixed`.
- `delivery.timeout_seconds` sets how long Relaywise waits for a response. The default is 15 seconds and the maximum is 60.

If you raise the number of attempts above 8, the extra attempts are spaced 15 hours apart.

## Responses that change the schedule

- **`Retry-After` header.** If a failed response includes this header, Relaywise waits at least that long before the next attempt, up to a ceiling of one hour.
- **`410 Gone`.** Relaywise takes this to mean the endpoint has been removed on purpose. It stops retrying the event and pauses the destination so that you can check the URL.
- **`429 Too Many Requests`.** Treated as a failure and retried, and it also counts towards the circuit breaker described below.

## The circuit breaker

If more than half of the deliveries to one destination fail within a ten-minute window, Relaywise marks the destination as **degraded**. While a destination is degraded, deliveries to it are slowed to one request per second so that a struggling endpoint has room to recover. Events are not dropped; they wait in the queue. The destination returns to normal after two minutes in which every delivery succeeds.

## Automatic disabling

A destination that has not accepted a single delivery for five days in a row is disabled, and Relaywise emails the workspace Admins. New events for a disabled destination are not attempted; they go straight to the dead-letter queue with error `RW-3410`. Re-enable the destination from its settings page once the endpoint is fixed.

## Ordering

Relaywise does not guarantee delivery order by default, because a retried event can arrive after newer ones. If your endpoint needs events for the same entity in order, turn on ordered delivery for the route and choose an ordering key, such as a customer ID. With ordered delivery, a failing event holds back later events that share its key until it succeeds or is exhausted.

## Idempotency

Because of retries, your endpoint can receive the same event more than once, for example when it processed the event but the response was lost. Every delivery carries the event ID in the `Relaywise-Event-Id` header. Store the IDs you have handled and skip repeats.

## When the attempts run out

An event that fails its final attempt is moved to the dead-letter queue, where it waits for you to inspect and replay it.
