# Plans and pricing

Relaywise has four plans. They differ mainly in how many events are included each month, how fast you can send them, and how long history is kept.

## Comparing the plans

| | Sandbox | Team | Scale | Enterprise |
|---|---|---|---|---|
| Monthly price | Free | $49 | $399 | By contract |
| Events included per month | 50,000 | 1 million | 20 million | By contract |
| Price per extra 10,000 events | Not available | $0.60 | $0.25 | By contract |
| Routes | 5 | 50 | 500 | Unlimited |
| Members | 3 | 15 | Unlimited | Unlimited |
| Single sign-on | No | No | Yes | Yes |
| Custom roles | No | No | No | Yes |
| Support | Community forum | Email, next working day | Email and chat, 4 hours | Named contact, 1 hour |

## What counts as an event

Each payload accepted by a source is one event, whatever number of destinations it is delivered to and however many times delivery is retried. Three things are easy to overlook:

- Replayed events count again.
- Events that match no route still count.
- Events sent with a test key do not count.

## Going over the included amount

On the Team and Scale plans, events beyond the included amount are accepted and billed as overage at the per-10,000 rate shown above. Overage appears as a separate line on the next invoice.

The Sandbox plan has no overage. When a Sandbox workspace reaches 50,000 events, further events are rejected until the next month begins.

## Setting a spending cap

If you would sooner lose events than receive an unexpected bill, set a hard cap under **Settings → Billing → Usage cap**. When usage reaches the cap, Relaywise rejects new events for the rest of the billing period. The cap can be set at the included amount or at any higher number.

Relaywise emails the Owners when usage reaches 80 percent and 100 percent of the included amount. You can change these thresholds.

## Paying yearly

Team and Scale can be paid yearly. Yearly billing costs the same as ten months, so two months are free. The included events are still counted month by month; they do not pool across the year.

## Upgrading

An upgrade takes effect straight away. You are charged the difference for the remainder of the current billing period, and the higher limits apply at once. Only an Owner can change the plan.

## Downgrading

A downgrade takes effect at the end of the current billing period. Before it can go ahead, the workspace has to fit inside the lower plan's limits. For example, a workspace with 60 routes has to remove 10 before it can move to Team. Retention shortens when the downgrade takes effect, and history older than the new limit is deleted then.

## Cancelling

Cancelling a paid plan moves the workspace to Sandbox at the end of the billing period. Nothing is deleted immediately, but the Sandbox limits on routes, members and retention apply from that date.

## Discounts

Registered charities and accredited schools and universities get 50 percent off the Team and Scale plans. Open-source projects with a public repository can apply for a free Team plan. Both need a short application through support.
