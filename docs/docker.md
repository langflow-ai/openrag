# Docker Deployment

## Standard Deployment

```bash
# Build and start all services
docker compose build
docker compose up -d
```

## CPU-Only Deployment

For environments without GPU support:

```bash
docker compose -f docker-compose-cpu.yml up -d
```

## Force Rebuild

If you need to reset state or rebuild everything:

```bash
docker compose up --build --force-recreate --remove-orphans
```

## Service URLs

After deployment, services are available at:

- Frontend: http://localhost:3000
- Backend API: http://localhost:8000
- Langflow: http://localhost:7860
- OpenSearch: http://localhost:9200
- OpenSearch Dashboards: http://localhost:5601
