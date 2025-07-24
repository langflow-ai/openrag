FROM node:18-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    python3-venv \
    python3-dev \
    build-essential \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

# Create a virtual environment
RUN python3 -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Set working directory
WORKDIR /app

# Install PyTorch and related packages
RUN pip install --no-cache-dir torch==2.0.1 torchvision==0.15.2 --index-url https://download.pytorch.org/whl/cpu
RUN pip install --no-cache-dir triton==2.0.0 || echo "Triton installation failed but continuing"
RUN pip install --no-cache-dir numpy pillow scipy

# Copy Python dependencies and source code directly
COPY src/ ./src/
COPY pyproject.toml uv.lock ./

# Install common packages that might be needed
RUN pip install --no-cache-dir \
    pandas \
    scikit-learn \
    transformers \
    requests \
    flask \
    flask-cors \
    langchain \
    || echo "Some packages failed to install, continuing anyway"

# Copy sample document and warmup script
COPY documents/2506.08231v1.pdf ./
COPY warm_up_docling.py ./
RUN python warm_up_docling.py || echo "Warmup script failed, continuing anyway"
RUN rm -f warm_up_docling.py 2506.08231v1.pdf

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
python src/app.py &\n\
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
