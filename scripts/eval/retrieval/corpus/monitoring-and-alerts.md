# Monitoring and alerts

Relaywise records how every source and destination is behaving and can tell you when something goes wrong, so that you do not learn about a broken integration from a customer.

## The dashboard

The **Overview** page shows the state of the workspace over the last 24 hours: events received, delivery success rate, the slowest destinations and the size of each dead-letter queue. Select any chart to narrow the view to one destination or change the time range.

## Metrics

| Metric | What it measures |
|---|---|
| `ingest.rate` | Events accepted per second |
| `ingest.rejected` | Events refused, grouped by error code |
| `delivery.success_rate` | Share of delivery attempts that got a 2xx response |
| `delivery.latency_p50` | Median response time of the endpoint |
| `delivery.latency_p95` | Response time that 95 percent of attempts stay under |
| `delivery.attempts_per_event` | Average number of attempts needed for an event |
| `dlq.depth` | Number of events waiting in a dead-letter queue |
| `queue.age_seconds` | Age of the oldest event still waiting for delivery |
| `quota.used_percent` | Share of the monthly included events used so far |

Each metric can be split by destination, source or event type.

Metrics are kept at one-minute resolution for 7 days and at one-hour resolution for 13 months. This is longer than events themselves are kept, because metrics hold only counts and timings, never payloads.

## Alert rules

An alert rule watches one metric and notifies you when it crosses a threshold.

1. Open **Monitoring → Alerts** and select **New rule**.
2. Choose a metric, and optionally limit the rule to one destination.
3. Set the condition, for example `delivery.success_rate` below 95 percent.
4. Set the evaluation window. The condition has to hold for the whole window before the alert fires. The shortest window is 5 minutes.
5. Choose where the notification goes.

Longer windows produce fewer false alarms. A destination that drops below 95 percent for one minute during a deployment is normal. One that stays there for 15 minutes is not.

## Notification channels

- **Email** to named members or any address.
- **Chat webhook**, posting a message to a channel in your team chat tool.
- **Paging integration**, opening an incident with your on-call service.
- **A Relaywise destination**, delivering the alert as an event so that your own tooling can react to it.

One rule can notify several channels.

## Avoiding repeated notifications

After a rule fires, it stays quiet for a cooldown period of 30 minutes even if the condition still holds. When the metric returns to normal, Relaywise sends a single **resolved** notification. The cooldown can be set per rule to anything from 5 minutes to 24 hours.

To silence a rule during planned work, select **Mute** and choose a duration. A muted rule keeps evaluating and records what it would have sent.

## Rules worth creating first

| Rule | Why |
|---|---|
| `delivery.success_rate` below 95 percent for 15 minutes | An endpoint is failing |
| `dlq.depth` above 100 | Events are being given up on |
| `queue.age_seconds` above 600 | Deliveries are falling behind |
| `quota.used_percent` above 80 | You are about to pay overage or reach a cap |
| `delivery.latency_p95` above 5 seconds | An endpoint is slow and close to timing out |

New workspaces on paid plans get the first two created automatically, with email notifications to the Admins.

## Sending metrics to your own tools

All of the metrics above can be read from the metrics API in a text format that most monitoring systems understand. Scrape it once a minute at most. Use an API key with the `events:read` scope.

## Relaywise's own status

Problems on the Relaywise side are published on the status page, which you can subscribe to by email. An incident there usually explains a sudden rise in `RW-9000` or `RW-9003` errors.
