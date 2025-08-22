FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better layer caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir --trusted-host pypi.org --trusted-host pypi.python.org --trusted-host files.pythonhosted.org -r requirements.txt

# Copy application code
COPY app/ ./app/
COPY config.yaml .

# Create non-root user for security
RUN groupadd -r edgebot && useradd -r -g edgebot -s /bin/false edgebot

# Create directory for logs and data
RUN mkdir -p /var/log/edgebot /var/lib/edgebot && \
    chown -R edgebot:edgebot /var/log/edgebot /var/lib/edgebot

# Switch to non-root user
USER edgebot

# Expose ports
EXPOSE 8080 8081 8082 5514/udp 5515

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8081/healthz || exit 1

# Run the application
CMD ["python", "-m", "app.main", "--config", "config.yaml"]