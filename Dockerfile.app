FROM node:18-slim

# Install Python, uv, and curl
RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install uv
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:$PATH"

# Set working directory
WORKDIR /app

# Copy Python dependencies
COPY pyproject.toml uv.lock ./
RUN uv sync

# Copy Python source
COPY src/ ./src/

# Copy sample document and warmup script
COPY documents/2506.08231v1.pdf ./
COPY warm_up_docling.py ./
RUN uv run python warm_up_docling.py && rm warm_up_docling.py 2506.08231v1.pdf

# Copy frontend dependencies
COPY frontend/package*.json ./frontend/
RUN cd frontend && npm install

# Copy frontend source
COPY frontend/ ./frontend/

# Build frontend
RUN cd frontend && npm run build

# Create startup script
RUN echo '#!/bin/bash\n\
set -e\n\
echo "Starting Python backend..."\n\
uv run python src/app.py &\n\
BACKEND_PID=$!\n\
echo "Waiting for backend to be ready..."\n\
until curl -f http://localhost:8000/search -X POST -H "Content-Type: application/json" -d "{\"query\":\"test\"}" > /dev/null 2>&1; do\n\
  echo "Backend not ready yet, waiting..."\n\
  sleep 2\n\
done\n\
echo "Backend is ready! Starting Frontend..."\n\
cd frontend && npm start &\n\
wait' > /app/start.sh && chmod +x /app/start.sh

# Expose only frontend port
EXPOSE 3000

# Start both services
CMD ["/app/start.sh"]