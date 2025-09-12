# Troubleshooting

## Podman on macOS

If using Podman on macOS, you may need to increase VM memory:

```bash
podman machine stop
podman machine rm
podman machine init --memory 8192   # 8 GB example
podman machine start
```

## Common Issues

1. OpenSearch fails to start: Check that `OPENSEARCH_PASSWORD` is set and meets requirements
2. Langflow connection issues: Verify `LANGFLOW_SUPERUSER` credentials are correct
3. Out of memory errors: Increase Docker memory allocation or use CPU-only mode
4. Port conflicts: Ensure ports 3000, 7860, 8000, 9200, 5601 are available
