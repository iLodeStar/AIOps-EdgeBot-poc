# EdgeBot Kubernetes Deployment Guide

This guide covers deploying EdgeBot using Helm charts on Kubernetes, including production-grade configurations and at-sea/ship-to-shore topology recommendations.

## Prerequisites

- Kubernetes cluster (v1.23+)
- Helm 3.8+
- kubectl configured for your cluster
- Storage class for persistent volumes (recommended)
- Prometheus Operator (for observability features)

## Quick Start

### 1. Add Required Helm Repositories

```bash
# Add required repositories for dependencies
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo add grafana https://grafana.github.io/helm-charts
helm repo add timescale https://charts.timescale.com/
helm repo update
```

### 2. Deploy Complete Stack (Recommended)

Deploy both mothership and observability stack together:

```bash
# Install complete EdgeBot stack
helm install edgebot ./charts/edgebot-umbrella \
  --create-namespace \
  --namespace edgebot
```

### 3. Access Services

```bash
# Get service URLs
kubectl get svc -n edgebot

# Forward Grafana port for access
kubectl port-forward -n edgebot svc/edgebot-observability-grafana 3000:80

# Forward Mothership port for API access  
kubectl port-forward -n edgebot svc/edgebot-mothership 8080:8080
```

Access Grafana at http://localhost:3000 (admin/admin) to view SLO dashboards.

## Individual Component Deployment

### Deploy Mothership Only

```bash
# Basic mothership deployment
helm install mothership ./charts/mothership \
  --namespace edgebot \
  --create-namespace \
  --set config.database.dsn="postgresql://user:pass@host:5432/mothership"
```

### Deploy Observability Stack Only

```bash
# Observability stack with auto-configured dashboards
helm install observability ./charts/observability \
  --namespace monitoring \
  --create-namespace \
  --set prometheus-stack.grafana.adminPassword="your-password"
```

## Configuration Examples

### Development Environment

```yaml
# dev-values.yaml
profiles:
  development:
    enabled: true

mothership:
  replicaCount: 1
  resources:
    requests:
      cpu: 250m
      memory: 512Mi
    limits:
      cpu: 500m
      memory: 1Gi
  config:
    logging:
      level: "DEBUG"
    database:
      enabled: true
    loki:
      enabled: true

observability:
  prometheus-stack:
    prometheus:
      prometheusSpec:
        retention: 7d
        storageSpec:
          volumeClaimTemplate:
            spec:
              resources:
                requests:
                  storage: 10Gi

timescaledb:
  enabled: true
  persistence:
    size: 10Gi
```

```bash
helm install edgebot ./charts/edgebot-umbrella -f dev-values.yaml
```

### Production Environment

```yaml
# production-values.yaml
profiles:
  production:
    enabled: true

mothership:
  replicaCount: 3
  image:
    repository: your-registry.com/edgebot/mothership
    tag: "1.5.0"
  resources:
    requests:
      cpu: 1000m
      memory: 2Gi
    limits:
      cpu: 2000m
      memory: 4Gi
  autoscaling:
    enabled: true
    minReplicas: 3
    maxReplicas: 10
    targetCPUUtilizationPercentage: 70
  config:
    database:
      dsn: "postgresql://mothership:secure-password@timescaledb:5432/mothership"
    loki:
      enabled: true
      batchSize: 1000
      batchTimeoutSeconds: 10
    llm:
      enabled: true
      apiKey: "your-openai-api-key"
  monitoring:
    serviceMonitor:
      enabled: true
  affinity:
    podAntiAffinity:
      preferredDuringSchedulingIgnoredDuringExecution:
        - weight: 100
          podAffinityTerm:
            labelSelector:
              matchExpressions:
                - key: app.kubernetes.io/name
                  operator: In
                  values: [mothership]
            topologyKey: kubernetes.io/hostname

observability:
  prometheus-stack:
    prometheus:
      prometheusSpec:
        replicas: 2
        retention: 90d
        retentionSize: 200GiB
        resources:
          requests:
            cpu: 2000m
            memory: 8Gi
          limits:
            cpu: 4000m
            memory: 16Gi
        storageSpec:
          volumeClaimTemplate:
            spec:
              storageClassName: "fast-ssd"
              resources:
                requests:
                  storage: 200Gi
    alertmanager:
      alertmanagerSpec:
        replicas: 3
        config:
          global:
            smtp_smarthost: 'smtp.company.com:587'
            smtp_from: 'edgebot-alerts@company.com'
          receivers:
            - name: 'critical-alerts'
              email_configs:
                - to: 'oncall@company.com'
                  subject: 'EdgeBot Critical: {{ .GroupLabels.alertname }}'
              slack_configs:
                - api_url: 'https://hooks.slack.com/services/your/webhook/url'
                  channel: '#alerts-critical'
    grafana:
      replicas: 2
      persistence:
        enabled: true
        size: 20Gi
        storageClassName: "standard"

timescaledb:
  enabled: true
  replicas: 3
  persistence:
    enabled: true
    size: 500Gi
    storageClassName: "fast-ssd"
  resources:
    requests:
      memory: 8Gi
      cpu: 4000m
    limits:
      memory: 16Gi
      cpu: 8000m
```

```bash
helm install edgebot ./charts/edgebot-umbrella -f production-values.yaml
```

## At-Sea/Ship-to-Shore Topology

For maritime deployments with intermittent connectivity:

### Ship Configuration (Edge)

```yaml
# ship-values.yaml
mothership:
  replicaCount: 2  # Redundancy for reliability
  resources:
    requests:
      cpu: 500m
      memory: 1Gi
    limits:
      cpu: 1000m  
      memory: 2Gi
  config:
    database:
      enabled: true
      # Use local TimescaleDB for offline operation
    loki:
      enabled: true
      batchSize: 5000  # Larger batches for efficiency
      batchTimeoutSeconds: 30
    logging:
      level: "INFO"
  # Persistent storage for offline queueing
  persistence:
    enabled: true
    size: 100Gi
    storageClassName: "local-storage"
  # Node affinity for ship nodes
  affinity:
    nodeAffinity:
      requiredDuringSchedulingIgnoredDuringExecution:
        nodeSelectorTerms:
        - matchExpressions:
          - key: topology.kubernetes.io/zone
            operator: In
            values: ["ship"]

# Minimal observability for resource constraints
observability:
  prometheus-stack:
    prometheus:
      prometheusSpec:
        retention: 30d
        storageSpec:
          volumeClaimTemplate:
            spec:
              resources:
                requests:
                  storage: 50Gi
    grafana:
      persistence:
        size: 5Gi

timescaledb:
  enabled: true
  persistence:
    size: 200Gi
    storageClassName: "local-storage"
  resources:
    requests:
      memory: 2Gi
      cpu: 1000m
```

### Shore Configuration (Central)

```yaml
# shore-values.yaml
mothership:
  replicaCount: 5  # High availability for central processing
  resources:
    requests:
      cpu: 2000m
      memory: 4Gi
    limits:
      cpu: 4000m
      memory: 8Gi
  autoscaling:
    enabled: true
    minReplicas: 5
    maxReplicas: 20
    targetCPUUtilizationPercentage: 60
  config:
    database:
      enabled: true
    loki:
      enabled: true
      batchSize: 10000  # High throughput processing
    llm:
      enabled: true  # Full AI capabilities on shore
  # Node affinity for shore infrastructure
  affinity:
    nodeAffinity:
      requiredDuringSchedulingIgnoredDuringExecution:
        nodeSelectorTerms:
        - matchExpressions:
          - key: topology.kubernetes.io/zone
            operator: In
            values: ["shore-datacenter"]

observability:
  # Full observability stack for central monitoring
  prometheus-stack:
    prometheus:
      prometheusSpec:
        replicas: 3
        retention: 180d  # Long-term data retention
        retentionSize: 1TiB
        storageSpec:
          volumeClaimTemplate:
            spec:
              resources:
                requests:
                  storage: 1Ti
```

## Production Recommendations

### Resource Planning

| Component | CPU Request | Memory Request | Storage | Replicas |
|-----------|-------------|----------------|---------|----------|
| Mothership (Dev) | 250m | 512Mi | - | 1 |
| Mothership (Prod) | 1000m | 2Gi | 10Gi (queue) | 3-10 |
| TimescaleDB (Dev) | 500m | 1Gi | 10-50Gi | 1 |
| TimescaleDB (Prod) | 2000m | 8Gi | 200-1000Gi | 3 |
| Prometheus (Dev) | 1000m | 2Gi | 10Gi | 1 |
| Prometheus (Prod) | 2000m | 8Gi | 100-500Gi | 2-3 |
| Grafana | 250m | 512Mi | 1-10Gi | 1-2 |

### High Availability Configuration

```yaml
# HA configuration
mothership:
  replicaCount: 3
  podDisruptionBudget:
    enabled: true
    minAvailable: 2
  affinity:
    podAntiAffinity:
      requiredDuringSchedulingIgnoredDuringExecution:
        - labelSelector:
            matchExpressions:
              - key: app.kubernetes.io/name
                operator: In
                values: [mothership]
          topologyKey: kubernetes.io/hostname

observability:
  prometheus-stack:
    prometheus:
      prometheusSpec:
        replicas: 2
    alertmanager:
      alertmanagerSpec:
        replicas: 3
    grafana:
      replicas: 2

timescaledb:
  replicas: 3
  # Configure streaming replication
```

### Security Hardening

```yaml
mothership:
  securityContext:
    runAsNonRoot: true
    runAsUser: 1001
    readOnlyRootFilesystem: true
    allowPrivilegeEscalation: false
    capabilities:
      drop: ["ALL"]
  podSecurityContext:
    fsGroup: 1001
    runAsUser: 1001
    runAsGroup: 1001
  
  # Network policies (if supported)
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

### Monitoring and Alerting

The observability stack includes pre-configured SLO monitoring:

- **Availability SLO**: 99.9% uptime target
- **Latency SLO**: P95 < 1s, P99 < 2s for ingestion
- **Error Budget**: Fast burn (4h) and slow burn (30d) alerts
- **Data Flow**: Alerts for no ingestion, sink failures

Critical alerts are configured for:
- Service downtime
- SLO breaches
- Error budget exhaustion
- Data pipeline failures

### Backup Strategy

```yaml
# Backup configuration for TimescaleDB
timescaledb:
  backup:
    enabled: true
    schedule: "0 2 * * *"  # Daily at 2 AM
    retention: "30d"
    storage:
      provider: "s3"
      bucket: "edgebot-backups"
      region: "us-west-2"
```

### Upgrade Strategy

```bash
# Rolling upgrade approach
helm upgrade edgebot ./charts/edgebot-umbrella \
  --namespace edgebot \
  -f production-values.yaml \
  --atomic \
  --timeout 10m

# Rollback if needed
helm rollback edgebot 1 --namespace edgebot
```

## Troubleshooting

### Common Issues

**Mothership pods not starting:**
```bash
kubectl describe pod -l app.kubernetes.io/name=mothership -n edgebot
kubectl logs -l app.kubernetes.io/name=mothership -n edgebot --tail=100
```

**Database connection issues:**
```bash
kubectl exec -it deployment/edgebot-mothership -n edgebot -- \
  sh -c 'curl -f http://localhost:8080/healthz || echo "Health check failed"'
```

**Prometheus not scraping:**
```bash
kubectl get servicemonitor -n edgebot
kubectl describe servicemonitor edgebot-mothership -n edgebot
```

**Storage issues:**
```bash
kubectl get pvc -n edgebot
kubectl describe pvc -n edgebot
```

### Debugging Commands

```bash
# Check all EdgeBot resources
kubectl get all -l app.kubernetes.io/part-of=edgebot -n edgebot

# View recent events
kubectl get events -n edgebot --sort-by='.lastTimestamp'

# Check resource usage
kubectl top pods -n edgebot

# Get comprehensive status
helm status edgebot -n edgebot
```

## Migration from Docker Compose

To migrate from the existing Docker Compose setup:

1. **Export data** from existing TimescaleDB (if needed)
2. **Deploy Kubernetes stack** with similar configuration
3. **Import data** to new TimescaleDB instance
4. **Update edge nodes** to point to new Kubernetes mothership service
5. **Verify metrics and dashboards** are working

```bash
# Get Kubernetes service endpoints
kubectl get svc -n edgebot -o wide

# Update edge node configuration to use new endpoints
# mothership_url: http://<k8s-mothership-ip>:8080
```

This completes the Kubernetes deployment guide for EdgeBot with production-ready configurations and maritime topology considerations.