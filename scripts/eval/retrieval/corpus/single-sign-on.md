# Single sign-on and user provisioning

Single sign-on (SSO) lets your team log in to the Relaywise console through your company's identity provider instead of with a separate password. It is available on the Scale and Enterprise plans.

## Supported protocols

Relaywise supports SAML 2.0 and OpenID Connect. Both work with the common identity providers. If your provider supports both, prefer OpenID Connect: it is simpler to set up and its certificates rotate automatically.

## Setting up SAML

1. In the console, open **Settings → Security → Single sign-on** and select **Configure SAML**.
2. Copy the two values Relaywise shows you into your identity provider: the Assertion Consumer Service URL and the Entity ID.
3. In your identity provider, map the user's email address to the `NameID` attribute, in email format.
4. Download the provider's metadata file and upload it to Relaywise.
5. Select **Test connection**. Relaywise opens a login window and reports whether the response was valid.
6. When the test passes, select **Enable**.

## Verifying your domain

Before SSO can be enforced, you must prove that you control your email domain. Relaywise gives you a TXT record to add to your DNS. Verification usually completes within an hour of the record being published. One workspace can verify several domains.

## Enforcing SSO

With SSO enabled but not enforced, members can use either SSO or their password. Turning on **Require SSO** removes the password option for everyone whose email address belongs to a verified domain.

Owners keep the ability to log in with a password and a one-time code even when SSO is required. This is a deliberate break-glass path so that a broken identity provider cannot lock you out of your own workspace. Keep at least two Owners for this reason.

## Session length

A console session lasts 12 hours by default. After that the member is sent back to the identity provider. On the Enterprise plan you can set the session length anywhere between 1 hour and 30 days. Idle sessions end after 60 minutes regardless of the overall session length.

## Automatic provisioning with SCIM

SCIM keeps the member list in step with your identity provider, so you do not have to invite or remove people by hand.

- When someone is assigned to the Relaywise application in the identity provider, they are created as a member.
- When someone is unassigned or deactivated, their console access ends within a few minutes and their personal access tokens are revoked.
- Group membership can set the member's role. Map each group to one role in **Settings → Security → Group mapping**.

To enable it, generate a SCIM token under **Settings → Security → Provisioning** and paste it, together with the SCIM base URL, into your identity provider. The token is valid for one year, and Relaywise emails the Owners 30 days before it expires.

Members created by SCIM default to the Viewer role unless a group mapping says otherwise.

## Troubleshooting SSO

- **"Response is not yet valid".** The clocks of the two systems disagree. Check the identity provider's time settings.
- **Login loops back to the login page.** The email address in the response does not belong to a verified domain.
- **A new colleague cannot log in.** They have not been assigned to the application in the identity provider.
