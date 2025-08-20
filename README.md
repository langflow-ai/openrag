## OpenRAG

[![Ask DeepWiki](https://deepwiki.com/badge.svg)](https://deepwiki.com/phact/openrag)

### getting started

Set up your secrets:

    cp .env.example .env

Populate the values in .env

Requirements:

Docker or podman with compose installed.

Run OpenRAG:

    docker compose build

    docker compose up

CPU only:

    docker compose -f docker-compose-cpu.yml up

If you need to reset state:

    docker compose up --build --force-recreate --remove-orphans
