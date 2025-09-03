# OpenRAG First-Run Setup

This document describes the automatic dataset loading feature that initializes OpenRAG with default documents on first startup.

## Overview

OpenRAG now includes a first-run initialization system that automatically loads documents from a default dataset directory when the application starts for the first time.

## Configuration

### Environment Variables

- `DATA_DIRECTORY`: Path to the directory containing default documents to load on first run (default: `./documents`)
- `SKIP_FIRST_RUN_INIT`: Set to `true` to disable automatic first-run initialization (default: `false`)

### External Dataset Loading

You can point `DATA_DIRECTORY` to any external location containing your default datasets. The system will:
- Copy files from the external directory to `./documents` to ensure Docker volume access
- Maintain directory structure during copying
- Only copy newer files (based on modification time)
- Skip files that already exist and are up-to-date

Example with external directory:
```bash
DATA_DIRECTORY=/path/to/my/external/datasets
```

This allows you to maintain your datasets outside the OpenRAG project while still leveraging the automatic loading feature.

### Example .env Configuration

```bash
# Default dataset directory for automatic ingestion on first run
DATA_DIRECTORY=./documents

# Skip first-run initialization (set to true to disable automatic dataset loading)
# SKIP_FIRST_RUN_INIT=false
```

## How It Works

1. **First-Run Detection**: The system checks for a `.openrag_initialized` marker file in the application root
2. **Document Detection**: If no marker file exists and there are no existing documents in the OpenSearch index, first-run initialization triggers
3. **File Copying**: If `DATA_DIRECTORY` points to a different location than `./documents`, files are copied to the documents folder to ensure Docker volume access
4. **File Discovery**: The system scans the documents folder for supported document types (PDF, TXT, DOC, DOCX, MD, RTF, ODT)
5. **Existing Workflow Reuse**: Found files are processed using the same `create_upload_task` method as the manual "Upload Path" feature
6. **Document Ownership**: In no-auth mode, documents owned by anonymous user; in auth mode, documents created without owner (globally accessible)
7. **Initialization Marker**: After successful setup, a marker file is created to prevent re-initialization on subsequent startups

## Docker Configuration

The `DATA_DIRECTORY` environment variable is automatically passed to the Docker containers. The default `./documents` directory is already mounted as a volume in the Docker configuration.

### Docker Compose

Both `docker-compose.yml` and `docker-compose-cpu.yml` have been updated to include:

```yaml
environment:
  - DATA_DIRECTORY=${DATA_DIRECTORY}
volumes:
  - ./documents:/app/documents:Z
```

## File Structure

```
openrag/
├── documents/          # Default dataset directory
│   ├── sample1.pdf
│   ├── sample2.txt
│   └── ...
├── .openrag_initialized  # Created after first successful initialization
└── src/
    └── utils/
        ├── first_run.py          # First-run detection logic
        └── default_ingestion.py  # Dataset ingestion logic
```

## Supported File Types

The first-run initialization supports the following document types:
- PDF (.pdf)
- Plain text (.txt)
- Microsoft Word (.doc, .docx)
- Markdown (.md)
- Rich Text Format (.rtf)
- OpenDocument Text (.odt)

## Behavior

### Normal First Run
1. Application starts
2. OpenSearch index is initialized
3. System checks for existing documents
4. If none found, copies files from `DATA_DIRECTORY` to `./documents` (if different)
5. Scans documents folder for supported files
6. Creates upload task using existing `create_upload_task` method (same as manual "Upload Path")
7. Documents are processed through complete knowledge pipeline (conversion, chunking, embedding, indexing) 
8. Creates `.openrag_initialized` marker file
9. Processing continues asynchronously in the background

### Subsequent Runs
1. Application starts
2. System detects `.openrag_initialized` marker file
3. First-run initialization is skipped
4. Application starts normally

### Skipping Initialization
Set `SKIP_FIRST_RUN_INIT=true` in your environment to disable first-run initialization entirely.

## Monitoring

First-run initialization creates a background task that can be monitored through:
- Console logs with `[FIRST_RUN]` prefix
- Task API endpoints (for system tasks)

## Troubleshooting

### No Documents Were Loaded
1. Check that `DATA_DIRECTORY` points to a valid directory
2. Verify the directory contains supported file types
3. Check console logs for `[FIRST_RUN]` messages
4. Ensure OpenSearch is running and accessible

### Disable First-Run Setup
If you want to prevent automatic initialization:
1. Set `SKIP_FIRST_RUN_INIT=true` in your .env file
2. Or create an empty `.openrag_initialized` file manually

### Files Not Visible in Knowledge List
If first-run files don't appear in the knowledge interface:

**For No-Auth Mode:**
- Files should be owned by "anonymous" user and visible immediately

**For Auth Mode:**
- Files are created without owner field, making them globally accessible
- All authenticated users should see these files in their knowledge list
- Check OpenSearch DLS configuration in `securityconfig/roles.yml`

### Force Re-initialization
To force first-run setup to run again:
1. Stop the application
2. Delete the `.openrag_initialized` file
3. Optionally clear the OpenSearch index
4. Restart the application