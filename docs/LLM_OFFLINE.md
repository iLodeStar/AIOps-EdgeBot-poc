# Offline LLM Enrichment with Ollama

This guide covers setting up fully offline LLM enrichment on edge nodes using Ollama, removing the dependency on external OpenAI-compatible services.

## Overview

The EdgeBot mothership now supports two LLM backends:

- **OpenAI-compatible**: For cloud-based or external LLM services (default)
- **Ollama**: For local, offline LLM inference on edge hardware

## Quick Setup

### 1. Install Ollama

#### On Linux (recommended for edge nodes)
```bash
curl -fsSL https://ollama.ai/install.sh | sh
```

#### On Docker
```bash
docker run -d \
  --name ollama \
  -p 11434:11434 \
  -v ollama:/root/.ollama \
  --restart unless-stopped \
  ollama/ollama
```

### 2. Pull a Recommended Model

For shipboard/edge CPUs with limited resources:

```bash
# Primary recommendation: Llama 3.1 8B (4-bit quantized)
ollama pull llama3.1:8b-instruct-q4_0

# Alternative: Qwen2 7B (multilingual support)
ollama pull qwen2:7b-instruct-q4_0

# For higher-end hardware
ollama pull llama3.1:8b-instruct-q8_0
```

### 3. Configure Mothership

Set environment variables to use Ollama backend:

```bash
# Core LLM settings
export MOTHERSHIP_LLM_ENABLED=true
export LLM_BACKEND=ollama

# Ollama-specific settings
export OLLAMA_BASE_URL=http://localhost:11434
export OLLAMA_MODEL=llama3.1:8b-instruct-q4_0
export OLLAMA_TIMEOUT_MS=30000
export OLLAMA_MAX_TOKENS=150
```

Or in your YAML configuration:

```yaml
llm:
  enabled: true
  backend: ollama  # 'openai' or 'ollama'
  confidence_threshold: 0.8
  
  # Ollama-specific settings
  ollama_base_url: "http://localhost:11434"
  ollama_model: "llama3.1:8b-instruct-q4_0"
  ollama_timeout_ms: 30000
  ollama_max_tokens: 150
```

## Model Recommendations

### Resource Requirements

| Model | RAM Requirement | CPU Cores | Inference Speed | Use Case |
|-------|----------------|-----------|-----------------|----------|
| `llama3.1:8b-instruct-q4_0` | 5-6 GB | 4+ | Fast | General purpose, shipboard |
| `llama3.1:8b-instruct-q8_0` | 8-9 GB | 6+ | Medium | Higher accuracy |
| `qwen2:7b-instruct-q4_0` | 4-5 GB | 4+ | Fast | Multilingual support |
| `phi3:3.8b-mini-instruct-q4_0` | 2-3 GB | 2+ | Very Fast | Resource constrained |

### Quantization Levels

- **q4_0**: 4-bit quantization, good balance of size/quality
- **q8_0**: 8-bit quantization, higher quality, larger size
- **fp16**: Full precision, highest quality, largest size

### Model Selection Guidelines

**For Production Edge Deployments:**
```bash
# Primary choice - best balance
ollama pull llama3.1:8b-instruct-q4_0

# Backup for resource constraints  
ollama pull phi3:3.8b-mini-instruct-q4_0
```

**For Development/Testing:**
```bash
# Quick testing
ollama pull phi3:3.8b-mini-instruct-q4_0

# Full featured
ollama pull llama3.1:8b-instruct-q8_0
```

## Configuration Options

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `LLM_BACKEND` | `openai` | Backend type: `openai` or `ollama` |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama server endpoint |
| `OLLAMA_MODEL` | `llama3.1:8b-instruct-q4_0` | Model identifier |
| `OLLAMA_TIMEOUT_MS` | `30000` | Request timeout in milliseconds |
| `OLLAMA_MAX_TOKENS` | `150` | Maximum response tokens |

### YAML Configuration

```yaml
llm:
  enabled: true
  backend: ollama
  confidence_threshold: 0.8
  
  # Circuit breaker for reliability
  circuit_breaker:
    enabled: true
    failure_threshold: 5
    reset_timeout: 60
  
  # Ollama settings
  ollama_base_url: "http://localhost:11434"
  ollama_model: "llama3.1:8b-instruct-q4_0" 
  ollama_timeout_ms: 45000
  ollama_max_tokens: 200
  temperature: 0.0
```

## Testing Your Setup

### 1. Verify Ollama Installation

```bash
# Check service status
curl http://localhost:11434/api/tags

# Test model availability
curl -X POST http://localhost:11434/api/generate \
  -H "Content-Type: application/json" \
  -d '{
    "model": "llama3.1:8b-instruct-q4_0",
    "prompt": "Hello world",
    "stream": false
  }'
```

### 2. Test Mothership Integration

```bash
# Start mothership with Ollama backend
LLM_BACKEND=ollama OLLAMA_MODEL=llama3.1:8b-instruct-q4_0 python main.py

# Send test event
curl -X POST http://localhost:8443/ingest \
  -H "Content-Type: application/json" \
  -d '{
    "events": [{
      "message": "User login failed for admin",
      "type": "auth",
      "timestamp": "2024-01-01T12:00:00Z"
    }]
  }'
```

### 3. Check Health Status

```bash
curl http://localhost:8443/healthz
```

Look for LLM enricher status and verify no external network dependencies.

## Production Deployment

### Hardware Sizing

**Minimum Requirements:**
- 4 CPU cores
- 8 GB RAM (6 GB available for model)
- 10 GB disk space
- No external network required

**Recommended:**
- 6+ CPU cores  
- 12+ GB RAM
- 20 GB disk space
- SSD storage for model loading

### Docker Compose Example

```yaml
version: '3.8'
services:
  ollama:
    image: ollama/ollama
    ports:
      - "11434:11434"
    volumes:
      - ollama_data:/root/.ollama
    restart: unless-stopped
    
  mothership:
    image: mothership:latest
    ports:
      - "8443:8443"
    environment:
      - MOTHERSHIP_LLM_ENABLED=true
      - LLM_BACKEND=ollama
      - OLLAMA_BASE_URL=http://ollama:11434
      - OLLAMA_MODEL=llama3.1:8b-instruct-q4_0
    depends_on:
      - ollama
    restart: unless-stopped

volumes:
  ollama_data:
```

### Performance Tuning

```bash
# Optimize for CPU inference
export OLLAMA_NUM_PARALLEL=2
export OLLAMA_MAX_LOADED_MODELS=1

# Memory management
export OLLAMA_MAX_VRAM=0  # Force CPU-only
```

## Fallback Strategy

### Hybrid Configuration

Configure automatic fallback from offline to cloud when needed:

```yaml
llm:
  enabled: true
  backend: ollama
  
  # Fallback configuration
  fallback:
    enabled: true
    backend: openai
    endpoint: "https://api.openai.com/v1"
    api_key: "${OPENAI_API_KEY}"
    conditions:
      - ollama_unavailable
      - high_confidence_required
```

### Circuit Breaker

The circuit breaker automatically switches to fallback on failures:

```yaml
llm:
  circuit_breaker:
    enabled: true
    failure_threshold: 3  # Switch after 3 failures
    reset_timeout: 120    # Try Ollama again after 2 minutes
```

## Troubleshooting

### Common Issues

**Model Not Found:**
```bash
# List available models
ollama list

# Pull missing model
ollama pull llama3.1:8b-instruct-q4_0
```

**Connection Refused:**
```bash
# Check Ollama service
systemctl status ollama

# Start if needed
systemctl start ollama
```

**Out of Memory:**
```bash
# Check available RAM
free -h

# Try smaller model
ollama pull phi3:3.8b-mini-instruct-q4_0
```

**Slow Inference:**
```bash
# Increase timeout
export OLLAMA_TIMEOUT_MS=60000

# Reduce token limit
export OLLAMA_MAX_TOKENS=100
```

### Monitoring

```bash
# Check Ollama resource usage
curl http://localhost:11434/api/ps

# Monitor system resources
htop

# Check mothership logs
journalctl -u mothership -f
```

## Security Considerations

### Network Isolation

- Ollama runs entirely offline
- No external API keys required
- Models downloaded once, cached locally
- Perfect for air-gapped environments

### Model Validation

```bash
# Verify model integrity
ollama show llama3.1:8b-instruct-q4_0

# Check model source
curl -s http://localhost:11434/api/show \
  -d '{"name": "llama3.1:8b-instruct-q4_0"}' | \
  jq .details
```

## Migration from OpenAI

### 1. Backup Current Configuration

```bash
cp config.yaml config.yaml.backup
```

### 2. Gradual Migration

```bash
# Start with dual testing
export LLM_BACKEND=ollama
export OLLAMA_MODEL=llama3.1:8b-instruct-q4_0

# Keep OpenAI as fallback initially
export OPENAI_FALLBACK_ENABLED=true
```

### 3. Validate Results

Compare enrichment quality between backends before full migration.

### 4. Full Switch

```bash
# Remove OpenAI dependency
unset OPENAI_API_KEY
export LLM_BACKEND=ollama
```

## Performance Benchmarks

Typical inference times on standard hardware:

| Hardware | Model | Time per Event | Throughput |
|----------|-------|---------------|------------|
| 4 Core CPU, 8GB RAM | llama3.1:8b-q4_0 | 2-5 seconds | 12-30 events/min |
| 8 Core CPU, 16GB RAM | llama3.1:8b-q4_0 | 1-3 seconds | 20-60 events/min |
| 8 Core CPU, 16GB RAM | phi3:3.8b-q4_0 | 0.5-1 second | 60-120 events/min |

## Getting Help

1. Check Ollama documentation: https://ollama.ai/docs
2. Review mothership logs for LLM enricher messages
3. Test with simple models first (phi3:3.8b-mini)
4. Monitor system resources during inference
5. Use circuit breaker for automatic fallback

## Advanced Configuration

### Custom Model Fine-tuning

For specialized log analysis, consider fine-tuning:

```bash
# Create custom model with log analysis training
ollama create custom-log-analyzer -f ./Modelfile
```

### Multi-Model Setup

Run multiple models for different log types:

```yaml
llm:
  models:
    security: "llama3.1:8b-instruct-q4_0"  
    system: "phi3:3.8b-mini-instruct-q4_0"
    network: "qwen2:7b-instruct-q4_0"
```

This completes the offline LLM setup. Your edge nodes can now perform intelligent log enrichment without any external dependencies or network requirements.