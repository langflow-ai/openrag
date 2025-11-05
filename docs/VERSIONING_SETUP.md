# Docusaurus versioning setup

Docs versioning is currently **DISABLED** but configured and ready to enable.
The configuration is found in `docusaurus.config.js` with commented-out sections.

To enable versioning, do the following:

1. Open `docusaurus.config.js`
2. Find the versioning configuration section (around line 57)
3. Uncomment the versioning configuration:

```javascript
docs: {
  // ... other config
  lastVersion: 'current', // Use 'current' to make ./docs the latest version
  versions: {
    current: {
      label: 'Next (unreleased)',
      path: 'next',
    },
  },
  onlyIncludeVersions: ['current'], // Limit versions for faster builds
},
```

## Create docs versions

See the [Docusaurus docs](https://docusaurus.io/docs/versioning) for more info.

1. Use the Docusaurus CLI command to create a version.
You can use `yarn` instead of `npm`.
```bash
# Create version 1.0.0 from current docs
npm run docusaurus docs:version 1.0.0
```

This command will:
- Copy the full `docs/` folder contents into `versioned_docs/version-1.0.0/`
- Create a versioned sidebar file at `versioned_sidebars/version-1.0.0-sidebars.json`
- Append the new version to `versions.json`

2. After creating a version, update the Docusaurus configuration to include multiple versions.
`lastVersion:'1.0.0'` makes the '1.0.0' release the `latest` version.
`current` is the work-in-progress docset, accessible at `/docs/next`.
To remove a version, remove it from `onlyIncludeVersions`.

```javascript
docs: {
  // ... other config
  lastVersion: '1.0.0', // Make 1.0.0 the latest version
  versions: {
    current: {
      label: 'Next (unreleased)',
      path: 'next',
    },
    '1.0.0': {
      label: '1.0.0',
      path: '1.0.0',
    },
  },
  onlyIncludeVersions: ['current', '1.0.0'], // Include both versions
},
```

3. Test the deployment locally.

```bash
npm run build
npm run serve
```

4. To add subsequent versions, repeat the process, first running the CLI command then updating `docusaurus.config.js`.

```bash
# Create version 2.0.0 from current docs
npm run docusaurus docs:version 2.0.0
```

After creating a new version, update `docusaurus.config.js`.

```javascript
docs: {
  lastVersion: '2.0.0', // Make 2.0.0 the latest version
  versions: {
    current: {
      label: 'Next (unreleased)',
      path: 'next',
    },
    '2.0.0': {
      label: '2.0.0',
      path: '2.0.0',
    },
    '1.0.0': {
      label: '1.0.0',
      path: '1.0.0',
    },
  },
  onlyIncludeVersions: ['current', '2.0.0', '1.0.0'], // Include all versions
},
```

## Disable versioning

1. Remove the `versions` configuration from `docusaurus.config.js`.
2. Delete the `docs/versioned_docs/` and `docs/versioned_sidebars/` directories.
3. Delete `docs/versions.json`.

## References

- [Official Docusaurus Versioning Documentation](https://docusaurus.io/docs/versioning)
- [Docusaurus Versioning Best Practices](https://docusaurus.io/docs/versioning#recommended-practices)