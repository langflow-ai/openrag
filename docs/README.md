# Website

This website is built using [Docusaurus](https://docusaurus.io/), a modern static website generator.

## Installation

```bash
npm install
```

## Local Development

```bash
npm start
```

This command starts a local development server and opens up a browser window. Most changes are reflected live without having to restart the server.

## Build

```bash
npm run build
```

This command generates static content into the `build` directory and can be served using any static contents hosting service.

## Deployment

Using SSH:

```bash
USE_SSH=true npm run deploy
```

Not using SSH:

```bash
GIT_USER=<Your GitHub username> npm run deploy
```

If you are using GitHub pages for hosting, this command is a convenient way to build the website and push to the `gh-pages` branch.

## Update the OpenRAG documentation PDF

The documentation PDF at `openrag/openrag-documents/openrag-documentation.pdf` is used by the OpenRAG application, so keep it up to date.

To update the PDF, do the following:

1. Remove elements from the `docs/*.mdx` files.
Content in tabs, details, and summary elements is hidden from PDF builds and it must be included.
To remove these items, give the following prompt or something similar to your IDE.

   ```
   Flatten documentation for PDF: remove tabs and details elements
   In all MDX files in docs/docs/, flatten interactive elements:
   Remove all <Tabs> and <TabItem> components:
   Convert each tab's content to a regular section with an appropriate heading (### for subsections, ## for main sections)
   Show all tab content sequentially
   Remove the import statements for Tabs and TabItem where they're no longer used
   Remove all <details> and <summary> elements:
   Convert details content to regular text with an appropriate heading (### for subsections)
   Show all content directly (no collapsible sections)
   Keep all content visible — nothing should be hidden or collapsed
   Maintain proper formatting and structure
   Apply this to all documentation files that contain tabs or details elements so the content is fully flat and visible for PDF generation.
   ```

2. Check your `.mdx` files to confirm these elements are removed.
Don't commit the changes.

3. From `openrag/docs`, run this command to build the site with the changes, and create a PDF at `openrag/openrag-documents`.

   ```
   npm run build:pdf
   ```

4. Check the PDF's content, then commit and create a pull request.