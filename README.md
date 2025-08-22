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


For podman on mac you may have to increase your VM memory (`podman stats` should not show limit at only 2gb):

    podman machine stop
    podman machine rm
    podman machine init --memory 8192   # example: 8 GB
    podman machine start
