# Configuration reference

This page lists every setting that can be changed on a workspace, a destination or a route. Each setting can be changed in the console, with `rwctl config set`, or through the management API.

Settings are inherited. A value set on a destination overrides the workspace default, and a value set on a route overrides the destination. To see the value that is actually in force and where it came from, run `rwctl config explain <key> --destination <id>`.

## Delivery settings

Scope: workspace or destination.

| Key | Default | Allowed values | Purpose |
|---|---|---|---|
| `delivery.max_attempts` | `8` | 1 to 20 | Total delivery attempts for one event |
| `delivery.backoff` | `exponential` | `exponential`, `fixed` | How the wait between attempts grows |
| `delivery.fixed_interval_seconds` | `300` | 10 to 86400 | Wait between attempts when the backoff is `fixed` |
| `delivery.timeout_seconds` | `15` | 1 to 60 | How long to wait for the endpoint to respond |
| `delivery.max_concurrency` | `25` | 1 to 500 | Deliveries in flight to one destination at the same time |
| `delivery.rate_per_second` | unset | 1 to 5000 | Upper limit on deliveries per second to one destination |
| `delivery.ordered` | `false` | `true`, `false` | Deliver events that share an ordering key strictly in order |
| `delivery.ordering_key` | unset | A payload path | The field whose value groups events for ordered delivery |

Lower `delivery.max_concurrency` if your endpoint cannot handle many requests in parallel. Set `delivery.rate_per_second` if the system behind the endpoint has a strict requests-per-second allowance of its own.

## Signing settings

Scope: destination.

| Key | Default | Allowed values | Purpose |
|---|---|---|---|
| `signing.enabled` | `true` | `true`, `false` | Add signature headers to deliveries |
| `signing.tolerance_seconds` | `300` | 60 to 900 | Age a timestamp may reach before the official libraries reject it |
| `signing.header_prefix` | `Relaywise` | Letters and hyphens | Prefix used for the signature and timestamp header names |

## Ingest settings

Scope: workspace or source.

| Key | Default | Allowed values | Purpose |
|---|---|---|---|
| `ingest.require_type` | `true` | `true`, `false` | Reject events that have no `type` field |
| `ingest.dedupe_window_seconds` | `0` | 0 to 3600 | Discard events whose idempotency key was already seen within this window |
| `ingest.allowed_ips` | unset | List of CIDR ranges | Accept events only from these source addresses |
| `ingest.schema_validation` | `off` | `off`, `warn`, `reject` | Check payloads against the registered schema for their event type |

With `ingest.schema_validation` set to `warn`, an event that does not match its schema is still accepted, and a warning is attached to it in the console. With `reject`, the event is refused.

## Retention settings

Scope: workspace.

| Key | Default | Allowed values | Purpose |
|---|---|---|---|
| `retention.payload_days` | Plan maximum | 1 up to the plan maximum | Days that event bodies are kept |
| `retention.metadata_days` | Plan maximum | 1 up to the plan maximum | Days that event metadata and attempt records are kept |
| `retention.redact_fields` | unset | List of payload paths | Fields replaced with `[redacted]` before the event is stored |

Redaction is applied to the stored copy only. The delivered payload is not changed.

## Transformation settings

Scope: route.

| Key | Default | Allowed values | Purpose |
|---|---|---|---|
| `transform.timeout_ms` | `250` | 50 to 1000 | Time allowed for one run of the transformation |
| `transform.memory_mb` | `32` | 16 to 128 | Memory available to one run |
| `transform.on_error` | `dead_letter` | `dead_letter`, `pass_through`, `drop` | What happens to the event when the code fails |

## Notification settings

Scope: workspace.

| Key | Default | Allowed values | Purpose |
|---|---|---|---|
| `notify.dlq_digest` | `true` | `true`, `false` | Send Admins a daily email about dead-letter queues that grew |
| `notify.quota_thresholds` | `80,100` | List of percentages | Quota usage levels that trigger an email |
| `notify.destination_disabled` | `true` | `true`, `false` | Email Admins when a destination is disabled automatically |

## Console settings

Scope: workspace.

| Key | Default | Allowed values | Purpose |
|---|---|---|---|
| `console.session_hours` | `12` | 1 to 720 | Length of a console session; changing it needs the Enterprise plan |
| `console.idle_timeout_minutes` | `60` | 5 to 240 | Idle time after which a session ends |
| `console.payload_preview` | `true` | `true`, `false` | Show payload bodies in the event list |

## Resetting a setting

Run `rwctl config unset <key>` to remove an override, so that the setting falls back to the value inherited from the level above.
