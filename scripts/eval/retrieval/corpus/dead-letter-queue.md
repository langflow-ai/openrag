# Dead-letter queue and replay

The dead-letter queue, or DLQ, holds events that Relaywise could not deliver. Nothing in it is lost: you can look at each event, see why it failed, and send it again once the cause is fixed.

## How events end up in the queue

An event moves to the DLQ of a destination when one of these happens:

- Every delivery attempt allowed for that destination has failed.
- The destination was disabled or paused when the event arrived.
- A transformation on the route raised an error, so there was no payload to deliver.
- The endpoint answered `410 Gone`.

Each destination has its own queue. An event routed to three destinations can be delivered to two of them and sit in the queue of the third.

## How long events are kept there

| Plan | Time in the dead-letter queue |
|---|---|
| Sandbox | 3 days |
| Team | 14 days |
| Scale | 30 days |
| Enterprise | 30 days, extendable to 90 by contract |

When that time is up, the event is deleted from the queue and can no longer be replayed. This period is counted from the moment the event entered the queue, and it is separate from the retention of ordinary event history.

## Inspecting a failed event

Open **Destinations**, choose the destination, then the **Dead-letter queue** tab. For each event you can see the payload, every delivery attempt with its status code and response time, the first 2 KB of each response body, and the error code of the final attempt.

Filter the list by error code, event type or time range to find a pattern. A queue full of timeouts points at a slow endpoint. A queue full of 401 responses usually means the signing secret on your side is out of date.

## Replaying events

Replaying sends an event again as a fresh delivery with a full retry budget.

**One event.** Open the event and select **Replay**.

**Many events.** Tick the events, or select everything that matches the current filter, then select **Replay selected**. Bulk replays run in the background at the destination's normal delivery rate, so they do not flood your endpoint.

**From the command line.**

```bash
rwctl dlq replay --destination dst_4h7q2 --since 2h
rwctl dlq replay --destination dst_4h7q2 --error RW-3001
```

**To a different destination.** Add `--to dst_9x1aa` to send the events somewhere other than where they first failed. This is useful when you have replaced an endpoint with a new one.

Replayed deliveries carry the header `Relaywise-Replay: true` and keep the original event ID, so an endpoint that tracks event IDs will recognise anything it has already handled.

Replaying needs the Developer role or higher, or an API key with the `replay:run` scope.

## Purging

If the events in a queue are no longer wanted, for example test traffic sent to a decommissioned endpoint, select **Purge queue**. Purging deletes every event in that destination's queue and cannot be undone. Only Admins and Owners can purge.

## Getting told about failures

A growing queue is often the first sign that an integration is broken. Create an alert rule on the `dlq.depth` metric to be told when a queue passes a size you choose. By default Relaywise also sends the workspace Admins a daily digest email listing destinations whose queues grew in the last 24 hours. Turn the digest off under **Settings → Notifications**.

## Replay limits

A single bulk replay can include at most 100,000 events. Larger recoveries have to be split by time range. Replayed events count towards your monthly event quota in the same way as new events.
