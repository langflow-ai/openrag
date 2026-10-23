# Getting started with Relaywise

Relaywise is a hosted service that receives events from your applications and delivers them to HTTP endpoints you control. You send an event once; Relaywise takes care of queuing, signing, retrying and recording what happened to it.

This page walks through the shortest path from a new account to a delivered event. It takes about ten minutes.

## Core concepts

- **Workspace.** The top-level container for everything you create. Billing, members and settings all belong to a workspace. Most companies need one workspace per environment, for example one for staging and one for production.
- **Source.** Where events come from. A source has an ingest URL that your application posts events to.
- **Destination.** An HTTP endpoint that should receive events. A destination has a URL, a signing secret and its own delivery settings.
- **Route.** A rule that connects a source to one or more destinations, optionally with a filter and a transformation.
- **Event.** A single JSON payload accepted by a source. One event can produce several deliveries, one per matching destination.

## Step 1: Create a workspace

Sign up at the Relaywise console and choose a workspace name. The name becomes part of your ingest hostname, so pick something short. You can rename a workspace later, but the ingest hostname keeps the original name.

Every new workspace starts on the Sandbox plan, which is free and needs no payment card.

## Step 2: Create a source

Open **Sources** and select **New source**. Give it a name such as `orders-service`. Relaywise shows the ingest URL once the source is saved. The URL looks like this:

```
https://ingest.relaywise.example/v1/sources/src_8fk2m1/events
```

## Step 3: Create a destination

Open **Destinations** and select **New destination**. Enter the HTTPS URL of the endpoint that should receive events. Plain HTTP URLs are rejected except for `localhost` when you use the development tunnel.

When you save the destination, Relaywise generates a signing secret for it. Copy the secret now if you plan to verify signatures; you can also reveal it again later from the destination's settings.

## Step 4: Connect them with a route

Open **Routes**, select **New route**, then pick the source and the destination you just created. Leave the filter empty so that every event matches.

## Step 5: Send a test event

You need an API key to send events. Create one under **Settings → API keys** with the `events:write` scope, then post a payload:

```bash
curl -X POST https://ingest.relaywise.example/v1/sources/src_8fk2m1/events \
  -H "Authorization: Bearer $RELAYWISE_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"type": "order.created", "order_id": "A-1042"}'
```

A successful request returns `202 Accepted` and an event ID that starts with `evt_`. Open **Events** in the console to watch the delivery. A green status means your endpoint answered with a 2xx response within the timeout.

## Where to go next

- Verify that deliveries really come from Relaywise by checking the signature header.
- Decide how failed deliveries should be retried.
- Invite your teammates and give each of them a role.
- Install the command-line tool if you prefer working from a terminal.
