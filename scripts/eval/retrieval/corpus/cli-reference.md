# Command-line tool reference

`rwctl` is the Relaywise command-line tool. Anything you can do in the console you can also do with `rwctl`, which makes it the natural choice for scripts, pipelines and local development.

## Installing

`rwctl` is a single binary for Linux, macOS and Windows. Download it from the console under **Settings → Developer tools**, or install it with your system's package manager. Check the installation with:

```bash
rwctl version
```

To update, run `rwctl self-update`. The tool tells you when a newer release exists, but it never updates itself without being asked.

## Signing in

```bash
rwctl login
```

This opens a browser window so that you can approve the session. It then stores a personal access token in your operating system's keychain. The token has the same permissions as your role in the workspace.

In a pipeline, where no browser is available, set the `RELAYWISE_API_KEY` environment variable to an automation key instead. When the variable is set, `rwctl` uses it and ignores any stored login.

## Profiles

If you work with several workspaces, give each one a profile:

```bash
rwctl profile add staging --workspace acme-staging
rwctl profile add production --workspace acme-prod
rwctl profile use staging
```

Add `--profile production` to any command to run it against another profile without switching. The `RELAYWISE_PROFILE` environment variable does the same for a whole shell session.

## Everyday commands

| Command | What it does |
|---|---|
| `rwctl sources list` | List the sources in the workspace |
| `rwctl destinations create --url <url>` | Create a destination |
| `rwctl routes create --source <id> --destination <id>` | Connect a source to a destination |
| `rwctl events send --source <id> --data @payload.json` | Send one event |
| `rwctl events tail` | Show events as they arrive |
| `rwctl events get <event-id>` | Show one event and all its delivery attempts |
| `rwctl dlq list --destination <id>` | List events in a dead-letter queue |
| `rwctl dlq replay --destination <id> --since 2h` | Replay failed events |
| `rwctl keys rotate <key-name> --overlap 24h` | Rotate an API key |
| `rwctl config set <key> <value>` | Change a setting |
| `rwctl config explain <key>` | Show the value in force for a setting and where it comes from |
| `rwctl config export > workspace.yaml` | Save the workspace configuration to a file |
| `rwctl config import workspace.yaml` | Apply a configuration file |
| `rwctl network egress-ips` | Print the addresses deliveries are sent from |

## Developing on your own machine

Your laptop cannot normally be reached from the internet, so Relaywise cannot deliver to it directly. The `listen` command opens a tunnel:

```bash
rwctl listen --forward-to localhost:4000/webhooks
```

While the command runs, events sent with a test key are forwarded to that local address. The command prints each delivery and the response your application gave. Press Ctrl+C to close the tunnel.

Add `--events "order.*"` to forward only some event types. Add `--print-secret` to show the temporary signing secret for the tunnel, so that you can test signature verification locally.

## Output formats

Commands print a table by default. Add `--output json` for output a program can read, or `--output yaml`. Combine it with `--quiet` to suppress progress messages, which keeps the output safe to pipe into another program.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | Success |
| 1 | General error |
| 2 | Wrong usage, such as an unknown flag or a missing argument |
| 3 | Not signed in, or the credentials were rejected |
| 4 | The thing you asked for does not exist |
| 5 | Rate limited; try again later |
| 6 | The operation was only partly completed, for example a bulk replay in which some events failed |

Scripts should check for code 5 and wait before trying again.

## Getting help

Every command accepts `--help`. Add `--debug` to print the HTTP requests the tool makes, with credentials masked. Include that output when you contact support.
