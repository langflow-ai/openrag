# OpenRAG security policy and responsible disclosure

## Security policy

This security policy applies to all public projects under the langflow-ai organization on GitHub. We prioritize security and continuously work to safeguard our systems. However, vulnerabilities can still exist. If you identify a security issue, please report it to us so we can address it promptly.

### Security and bug fix versions

- Fixes are released either as part of the next minor version (e.g., 1.3.0 → 1.4.0) or as an on-demand patch version (e.g., 1.3.0 → 1.3.1)
- Security fixes are given priority and might be enough to cause a new version to be released

## Report a vulnerability

We encourage responsible disclosure of security vulnerabilities. If you find or suspect a security issue, please discreetly report it to us so we can address it promptly:

### Submit a report

Go to the [OpenRAG Security page](https://github.com/langflow-ai/openrag/security), and then click **Report a vulnerability** to start a private conversation between you and the repository's maintainers.

Provide as many specific details as possible to help us reproduce and fix the issue quickly, including the following:

- Steps to reproduce the issue
- Potential impact or concerns
- Any suggested fixes

Your report is kept confidential, and these details aren't shared without your consent.

### Response timeline

We will acknowledge your report within 5 business days.

We will provide an estimated resolution timeline.

We will keep you updated on our progress.

### Disclosure guidelines

- Don't publicly disclose vulnerabilities until we have assessed, resolved, and notified affected users.
- If you plan to present your research (e.g., at a conference or in a blog), share a draft with us at least 30 days in advance for review.
- Disclosures must not include the following:
  - Data from any OpenRAG customer projects
  - OpenRAG user/customer information
  - Details about OpenRAG employees, contractors, or partners

We appreciate your efforts in helping us maintain a secure platform, and we look forward to working together to resolve any issues responsibly.

## Known vulnerabilities

The following known vulnerabilities are for the OpenRAG codebase.

This list doesn't include vulnerabilities within OpenRAG dependencies like OpenSearch and Langflow.
For Langflow vulnerabilities, see the [Langflow SECURITY.md](https://github.com/langflow-ai/langflow/blob/main/SECURITY.md).

There are no known vulnerabilities exclusive to the OpenRAG application at this time.

## Security configuration guidelines

### Start the Langflow server with authentication enabled

It is recommended that you set a Langflow password (`LANGFLOW_SUPERUSER_PASSWORD`) so the Langflow server starts with authentication enabled and the `langflow superuser` command disabled.

You can set this password when you install OpenRAG, or you can [edit the OpenRAG `.env` file and redeploy the OpenRAG containers](https://docs.openr.ag/reference/configuration#set-environment-variables).

For more information, see [OpenRAG's Langflow settings reference](https://docs.openr.ag/reference/configuration#langflow-settings).