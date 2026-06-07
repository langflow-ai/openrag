#!/bin/bash
set -e

# =============================================================================
# Axioma-2.0 — Setup inicial para Digital Ocean Droplet (Ubuntu 22.04+)
#
# Uso:
#   bash scripts/setup-droplet.sh
#
# Qué hace:
#   1. Instala Docker y Docker Compose
#   2. Clona el repositorio
#   3. Crea el .env desde .env.example
#   4. Sugiere generación de secretos de producción
#   5. Levanta servicios con overlay de producción
# =============================================================================

REPO_URL="https://github.com/javi2481/Axioma-2.0.git"
APP_DIR="/opt/axioma"

echo "==> Actualizando paquetes..."
apt-get update -y

echo "==> Instalando dependencias..."
apt-get install -y ca-certificates curl gnupg lsb-release git

# --- Docker ---
if ! command -v docker &> /dev/null; then
    echo "==> Instalando Docker..."
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    chmod a+r /etc/apt/keyrings/docker.gpg
    echo \
      "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
      https://download.docker.com/linux/ubuntu \
      $(lsb_release -cs) stable" | tee /etc/apt/sources.list.d/docker.list > /dev/null
    apt-get update -y
    apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
    systemctl enable docker
    systemctl start docker
    echo "==> Docker instalado: $(docker --version)"
else
    echo "==> Docker ya instalado: $(docker --version)"
fi

# --- vm.max_map_count para OpenSearch ---
echo "==> Configurando vm.max_map_count para OpenSearch..."
sysctl -w vm.max_map_count=262144
echo "vm.max_map_count=262144" >> /etc/sysctl.conf

# --- Clonar repositorio ---
if [ -d "$APP_DIR" ]; then
    echo "==> Actualizando repositorio existente en $APP_DIR..."
    git -C "$APP_DIR" pull origin main
else
    echo "==> Clonando repositorio en $APP_DIR..."
    git clone "$REPO_URL" "$APP_DIR"
fi

cd "$APP_DIR"

# --- Archivo .env ---
if [ ! -f ".env" ]; then
    echo "==> Creando .env desde .env.example..."
    cp .env.example .env
    echo ""
    echo "  IMPORTANTE: Editá el archivo .env antes de continuar."
    echo "  Como mínimo configurá:"
    echo "    - OPENSEARCH_PASSWORD"
    echo "    - OPENRAG_ENCRYPTION_KEY"
    echo "    - LANGFLOW_SECRET_KEY"
    echo "    - SESSION_SECRET"
    echo "    - VALKEY_PASSWORD"
    echo "    - Credenciales del proveedor LLM/embedding"
    echo ""
    echo "  Sugerencia: scripts/generate-secrets.sh --write .env"
    echo ""
    read -p "  ¿Ya editaste el .env? Presioná Enter para continuar o Ctrl+C para salir y editarlo primero..."
else
    echo "==> .env ya existe, saltando..."
fi

# --- Levantar servicios ---
echo "==> Levantando servicios con Docker Compose..."
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build

echo ""
echo "==> Deploy completado."
echo ""
echo "  Servicios disponibles:"
echo "    Frontend (publicar via Caddy/Nginx): http://127.0.0.1:3000"
echo "    Backend API (interno via frontend):  http://openrag-backend:8000"
echo "    Langflow (admin local/VPN):          http://127.0.0.1:7860"
echo "    OpenSearch Dashboards (admin):       http://127.0.0.1:5601"
echo ""
echo "  Para ver logs:   docker compose logs -f"
echo "  Para detener:    docker compose down"
