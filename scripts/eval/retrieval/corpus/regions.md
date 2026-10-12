# Regions and data residency

A Relaywise workspace lives in one region. Events sent to that workspace are received, stored and delivered from that region, and are not copied to any other.

## Available regions

| Region code | Location | Ingest hostname |
|---|---|---|
| `us-east` | Virginia, United States | `ingest.us.relaywise.example` |
| `eu-central` | Frankfurt, Germany | `ingest.eu.relaywise.example` |
| `ap-southeast` | Singapore | `ingest.ap.relaywise.example` |

Each region runs across three separate data centres. The loss of one data centre does not interrupt the service or lose accepted events.

## Choosing a region

You choose the region when you create the workspace. Two things should guide the choice:

- **Where your data is allowed to be.** If your company or your customers require data to remain in the European Union, choose `eu-central`.
- **Where your systems run.** Put the workspace close to the applications that send events and the endpoints that receive them. Distance adds delay to every request.

If the two pull in different directions, the legal requirement wins.

## What stays in the region

Event payloads, event metadata, dead-letter queues, transformation code, logs produced by transformations and backups all stay in the workspace's region.

A small amount of account information is held centrally in the United States so that login and billing work everywhere: member names and email addresses, the workspace name, plan and invoices. Event data is never part of this.

## Changing region

The region of an existing workspace cannot be changed. To move, create a new workspace in the target region, copy the configuration across with `rwctl config export` and `rwctl config import`, and point your senders at the new ingest hostname. Event history does not move.

Enterprise customers can ask support for an assisted migration, which keeps destination IDs and signing secrets the same, so that receiving endpoints need no changes.

## Sending to the wrong region

Each ingest hostname accepts events only for workspaces in its own region. A request sent to the hostname of another region is rejected with error `RW-7001`. The general hostname `ingest.relaywise.example` redirects to the correct region, but it adds a network round trip, so use the regional hostname in production.

## Where deliveries come from

Deliveries leave from a fixed set of IP addresses in each region. If your endpoint sits behind a firewall, allow the addresses for your workspace's region. The current list is on the workspace's **Network** page and is printed by `rwctl network egress-ips`. Relaywise gives at least 30 days' notice before adding or removing an address.

## Running in several regions

A company that needs events handled in more than one region creates one workspace per region. Workspaces are independent. They do not share sources, destinations, quotas or history. Members can belong to several workspaces and switch between them in the console, and Enterprise contracts can pool the event allowance across workspaces.

## Disaster recovery

Backups are taken every hour and kept in the same region, in a different data centre from the primary copy. Relaywise aims to restore service within four hours of losing a whole region and to lose no more than one hour of event history. Events that had been accepted but not yet delivered are delivered once service resumes.
