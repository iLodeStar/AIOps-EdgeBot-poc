# EdgeBot Deployment Examples

This directory contains example values files for different EdgeBot deployment scenarios.

## Available Examples

### `dev-values.yaml`
Development environment with minimal resources and debug logging.

```bash
helm install edgebot ./charts/edgebot-umbrella -f examples/dev-values.yaml
```

**Features:**
- Single replica deployments
- Debug logging enabled
- Minimal storage and resource allocation
- Local TimescaleDB instance
- Basic observability stack

**Resource Requirements:** ~2 CPU, 4GB RAM, 20GB storage

### `production-values.yaml`
Production environment with high availability and performance optimization.

```bash
helm install edgebot ./charts/edgebot-umbrella -f examples/production-values.yaml
```

**Features:**
- Multi-replica deployments with auto-scaling
- Production logging levels
- High availability configurations
- Extended data retention
- Comprehensive alerting setup
- Pod anti-affinity rules

**Resource Requirements:** ~15 CPU, 40GB RAM, 1TB+ storage

### `ship-values.yaml`
Maritime ship deployment optimized for at-sea operation with intermittent connectivity.

```bash
helm install edgebot ./charts/edgebot-umbrella -f examples/ship-values.yaml
```

**Features:**
- Resource-efficient configuration
- Large batch sizes for efficiency
- Local storage for offline operation
- Extended data retention for sync windows
- Node affinity for ship hardware
- Minimal alerting (local logging)

**Resource Requirements:** ~3 CPU, 8GB RAM, 350GB storage

### `shore-values.yaml`
Maritime shore deployment for central data processing and fleet monitoring.

```bash
helm install edgebot ./charts/edgebot-umbrella -f examples/shore-values.yaml
```

**Features:**
- High-throughput processing capabilities
- Multi-ship monitoring dashboards
- Long-term data retention (180d)
- Advanced alerting with ship-specific routing
- High availability database cluster
- Automated backup configurations

**Resource Requirements:** ~30 CPU, 80GB RAM, 3TB+ storage

## Customization

You can combine multiple values files or override specific values:

```bash
# Combine production base with custom overrides
helm install edgebot ./charts/edgebot-umbrella \
  -f examples/production-values.yaml \
  -f your-custom-values.yaml \
  --set mothership.image.tag=1.6.0

# Override specific values inline
helm install edgebot ./charts/edgebot-umbrella \
  -f examples/dev-values.yaml \
  --set observability.prometheus-stack.grafana.adminPassword=mypassword
```

## Environment-Specific Configurations

### Cloud Provider Optimizations

**AWS:**
```yaml
timescaledb:
  persistence:
    storageClassName: "gp3"
observability:
  prometheus-stack:
    prometheus:
      prometheusSpec:
        storageSpec:
          volumeClaimTemplate:
            spec:
              storageClassName: "gp3"
```

**GCP:**
```yaml
timescaledb:
  persistence:
    storageClassName: "ssd"
observability:
  prometheus-stack:
    prometheus:
      prometheusSpec:
        storageSpec:
          volumeClaimTemplate:
            spec:
              storageClassName: "ssd"
```

**Azure:**
```yaml
timescaledb:
  persistence:
    storageClassName: "managed-premium"
observability:
  prometheus-stack:
    prometheus:
      prometheusSpec:
        storageSpec:
          volumeClaimTemplate:
            spec:
              storageClassName: "managed-premium"
```

### Security Configurations

For enhanced security in production:

```yaml
mothership:
  podSecurityContext:
    runAsUser: 1001
    runAsGroup: 1001
    fsGroup: 1001
  securityContext:
    allowPrivilegeEscalation: false
    readOnlyRootFilesystem: true
    runAsNonRoot: true
    capabilities:
      drop: ["ALL"]
      
  networkPolicy:
    enabled: true
    ingress:
      - from:
          - namespaceSelector:
              matchLabels:
                name: edgebot
        ports:
          - protocol: TCP
            port: 8080
```

### Monitoring Integrations

**External Prometheus:**
```yaml
mothership:
  monitoring:
    serviceMonitor:
      enabled: true
      namespace: monitoring
      labels:
        prometheus: external

observability:
  enabled: false  # Use external monitoring
```

**External Grafana:**
```yaml
observability:
  prometheus-stack:
    grafana:
      enabled: false  # Use external Grafana
      
  # Export dashboards as ConfigMaps
  dashboards:
    enabled: true
    namespace: grafana-system
```

## Validation

Test your values files before deployment:

```bash
# Template validation
helm template test ./charts/edgebot-umbrella -f examples/production-values.yaml

# Dry-run installation
helm install test ./charts/edgebot-umbrella -f examples/production-values.yaml --dry-run

# Lint with custom values
helm lint ./charts/edgebot-umbrella -f examples/production-values.yaml
```