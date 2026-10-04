# Verify Authorized Domains for Google OAuth App

“**Verify authorized domains**” means Google wants proof that the domains shown or used by your OAuth app are domains you control. Google says OAuth verification requires verification of domains associated with the app’s **homepage, privacy policy, terms of service, authorized redirect URIs, and authorized JavaScript origins**.

For OpenRAG, this item consists of the following.

## 1. Identify every domain used by the OAuth app

You need to list all domains used in these places:

| Area | Example | Must be verified? |
|---|---|---:|
| App/homepage URL | `https://openr.ag` or `https://docs.openr.ag` | Yes |
| Privacy policy URL | `https://openr.ag/privacy` | Yes |
| Terms of service URL | `https://openr.ag/terms` | Yes, if provided |
| OAuth redirect URI | `https://app.openr.ag/api/auth/google/callback` | Yes |
| JavaScript origin | `https://app.openr.ag` | Yes |
| Production app URL | `https://openrag.example.com` | Yes |

Google’s OAuth consent screen has an **App Domain** section where you provide homepage, privacy policy, and terms links; for external production apps, these links are required before verification submission.

## 2. Verify domain ownership in Google Search Console

For every domain listed in the OAuth consent screen’s **Authorized domains** section, a Google Cloud project **owner or editor** must verify ownership using Google Search Console.

Typical methods:

| Method | What you need |
|---|---|
| DNS TXT record | Access to DNS provider |
| HTML file upload | Access to web hosting |
| HTML meta tag | Ability to edit homepage HTML |
| Google Analytics / Tag Manager | Existing verified setup |

For enterprise/IBM-owned domains, the hard part is usually not technical OAuth config — it is finding the team that can verify the domain in Search Console or add the DNS TXT record.

## 3. Add only the top/private domain in Authorized Domains

Usually, you add the root/registrable domain, not every subdomain.

Example:

| URL used | Authorized domain to add |
|---|---|
| `https://app.openr.ag/oauth/callback` | `openr.ag` |
| `https://docs.openr.ag/privacy` | `openr.ag` |
| `https://openrag.ibm.com/callback` | `ibm.com` |
| `https://openrag.cloud.ibm.com/callback` | `ibm.com` or possibly `cloud.ibm.com`, depending on Google Console validation |

In practice, Google Cloud Console will guide what it accepts, but the important point is: **the domain must be owned/verified by the same account or organization connected to the OAuth project**.

## 4. Ensure homepage and privacy policy are on verified domains

For verification, Google cares that the app’s public-facing pages match the verified app identity.

Avoid this kind of mismatch:

```text
Homepage:       https://docs.openr.ag
Privacy policy: https://some-random-doc-site.com/privacy
Redirect URI:   https://temporary-test-url.ngrok.io/oauth/callback
```

A cleaner setup is:

```text
Homepage:       https://openr.ag
Privacy policy: https://openr.ag/privacy
Redirect URI:   https://app.openr.ag/api/connectors/google-drive/oauth/callback
Authorized domain: openr.ag
```

The privacy policy should be visible to users, hosted within the same domain as the application homepage, and linked from the OAuth consent screen.

## 5. Make sure redirect URIs and JavaScript origins use verified domains

For the Google Drive connector, your OAuth client will likely include something like:

```text
Authorized redirect URI:
https://<openrag-domain>/api/connectors/google-drive/oauth/callback
```

That domain must be part of the verified authorized domains. Domains used by redirect URIs or JavaScript origins must also be verified.

Do not use temporary domains for production verification, such as:

```text
ngrok.io
localhost
temporary QA URLs
random cloud preview URLs
```

`localhost` may be fine for local development, but not for production verification.

## 6. Remove unused domains before submission

Before submitting verification, clean up:

- Old test redirect URIs.
- QA/pre-prod callback URLs not used in production.
- Temporary URLs.
- Domains you cannot verify.
- Domains from old OAuth clients in the same Google Cloud project.

If a domain is used by OAuth clients, you must first remove redirect URIs or JavaScript origins referencing that domain before removing it from Authorized Domains.

## OpenRAG-specific recommendation

For the first Google Drive connector verification, use one clean production domain set:

```text
Homepage:
https://openr.ag

Privacy policy:
https://openr.ag/privacy

App / connector callback:
https://app.openr.ag/api/connectors/google-drive/oauth/callback

Authorized domain:
openr.ag
```

If IBM SaaS will use an IBM-owned production domain, then the required action is:

> Get the IBM domain owner/team to verify the domain in Google Search Console and make sure the Google Cloud project owner/editor account has access to that verification.

## Acceptance criteria

This item is complete when:

- The homepage domain is verified.
- The privacy policy domain is verified.
- The OAuth redirect URI domain is verified.
- The JavaScript origin domain is verified, if used.
- The OAuth consent screen Authorized Domains list contains only domains you own/control.
- No test, staging, localhost, ngrok, or unrelated domains remain in the production OAuth client.
- The Google Cloud project owner/editor can see the verified domain in Google Search Console.
- The OAuth consent screen accepts the homepage and privacy policy URLs without domain ownership warnings.
