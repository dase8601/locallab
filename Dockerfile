FROM python:3.11-slim

WORKDIR /app

# System dependencies for PDF processing (fitz/PyMuPDF)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libmupdf-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY . .

# Create required directories
RUN mkdir -p db uploads logs

# locallab runs on 5001
EXPOSE 5001

# Ollama must be reachable at http://host.docker.internal:11434
# (set OLLAMA_URL env var to override)
ENV OLLAMA_URL=http://host.docker.internal:11434

CMD ["python", "ui/app.py"]
