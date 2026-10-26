# Roles and permissions

Every member of a workspace has exactly one role. The role decides what that person can see and change in the console and through personal access tokens.

## The four roles

**Owner.** Full control, including billing, deleting the workspace and transferring ownership. A workspace must always have at least one Owner.

**Admin.** Everything an Owner can do except billing, workspace deletion and ownership transfer. Admins manage members, API keys and security settings.

**Developer.** Day-to-day work: creating and editing sources, destinations, routes, filters and transformations, and replaying events. Developers cannot manage members or keys.

**Viewer.** Read-only access to configuration and delivery history. Viewers see event metadata but not payload bodies unless payload access is granted separately.

## Permission matrix

| Action | Owner | Admin | Developer | Viewer |
|---|---|---|---|---|
| View events and delivery attempts | Yes | Yes | Yes | Yes |
| View event payload bodies | Yes | Yes | Yes | Only with payload access |
| Create or edit destinations and routes | Yes | Yes | Yes | No |
| Replay events | Yes | Yes | Yes | No |
| Purge the dead-letter queue | Yes | Yes | No | No |
| Create or revoke API keys | Yes | Yes | No | No |
| Invite or remove members | Yes | Yes | No | No |
| Change security settings | Yes | Yes | No | No |
| Read the audit log | Yes | Yes | No | No |
| Change plan or payment method | Yes | No | No | No |
| Delete the workspace | Yes | No | No | No |

## Inviting a member

Admins and Owners invite people from **Settings → Members**. Enter an email address and pick a role. The invitation link is valid for 7 days. If it lapses, send it again from the same page; the original link stops working when a new one is issued.

A person can belong to several workspaces and may have a different role in each.

## Changing a role

Open the member's row, choose a new role and confirm. The change takes effect on the member's next request; they do not need to log out. An Admin cannot change the role of an Owner.

## Payload access

Event bodies often contain personal data. By default Viewers see only metadata: event type, size, timestamps and delivery outcome. To let a Viewer read bodies, an Admin enables **Payload access** on that member. Each time someone opens a payload, the action is written to the audit log.

## Removing a member

Removing a member ends their sessions at once and revokes their personal access tokens. API keys they created keep working, because keys belong to the workspace and not to the person who made them. Review those keys separately if the departure was not amicable.

## Transferring ownership

Only an Owner can make someone else an Owner. To hand a workspace over, promote the new person first, confirm that they can log in, and then demote yourself. Relaywise refuses to remove the last Owner.

## Custom roles

The Enterprise plan adds custom roles. A custom role starts as a copy of one of the four built-in roles, and you then switch individual permissions on or off. A workspace can define up to 20 custom roles.
