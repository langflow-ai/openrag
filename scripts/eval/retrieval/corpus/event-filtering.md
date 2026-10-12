# Routing and event filters

A route decides which events from a source go to which destinations. Without a filter, a route forwards everything. With a filter, it forwards only the events you describe, so each endpoint receives what it cares about and nothing else.

## Writing a filter

A filter is a single expression that is evaluated against each event. If it is true, the event is delivered to the route's destinations.

```
type == "order.created" && data.total > 100
```

Fields are addressed with dots. `type` is the event type. `data` is the payload body. `meta` holds information Relaywise adds, such as `meta.source` and `meta.received_at`.

## Operators

| Operator | Meaning | Example |
|---|---|---|
| `==`, `!=` | Equal, not equal | `data.currency == "EUR"` |
| `>`, `>=`, `<`, `<=` | Numeric comparison | `data.items_count >= 3` |
| `&&`, `\|\|`, `!` | And, or, not | `!(data.test == true)` |
| `in` | Value is in a list | `data.country in ["DE", "FR", "NL"]` |
| `matches` | Wildcard pattern | `type matches "invoice.*"` |
| `exists` | Field is present | `exists(data.customer.email)` |
| `contains` | Text or list contains a value | `data.tags contains "priority"` |

In a `matches` pattern, `*` stands for any run of characters within one segment of a dotted name, and `**` stands for any number of segments. So `invoice.*` matches `invoice.paid` but not `invoice.line.added`, and `invoice.**` matches both.

## Missing fields

A comparison against a field that is not in the payload is false; it is not an error. This means `data.total > 100` quietly excludes events that have no `total`. Use `exists(...)` when the difference matters to you.

## Trying a filter before you save it

The route editor has a **Test** panel. It runs your expression against the 100 most recent events from the source and shows which ones would match. Use it every time. A filter with a typo in a field name matches nothing and produces no error, which is easy to miss.

If the expression itself cannot be parsed, saving fails with error `RW-2010`, and the message points at the character where parsing stopped.

## Sending one event to several places

A route can have up to 20 destinations. Each of them gets its own delivery with its own retries, so a failure at one endpoint does not delay the others.

One event can also match several routes. If two routes send the same event to the same destination, it is delivered twice. Relaywise does not merge duplicates across routes, because the routes may apply different transformations.

## Events that match nothing

An event that matches no route is marked **unrouted**. It is stored in the event history for the usual retention period, but nothing is delivered. Unrouted events still count towards the monthly quota. If you see many of them, either add a route for them or stop sending them.

## Limits

- A filter may be up to 4 KB long and contain up to 50 conditions.
- Filters cannot call functions other than `exists`, and cannot read other events.
- The number of routes in a workspace depends on the plan.

## Filter or transformation?

Use a filter to decide whether an event is delivered. Use a transformation to change what is delivered. A transformation can also drop an event by returning `null`, but a filter is cheaper, runs first, and makes the intent visible in the route list.
