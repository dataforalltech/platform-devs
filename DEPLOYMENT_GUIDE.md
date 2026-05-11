# 🚀 Deployment Guide — 10 Python Zilla MCPs

**Version**: 2.1.0 | **Date**: 2026-05-11 | **Status**: Ready for Production

---

## 📋 Overview

This guide covers deployment of the 10 Zilla MCPs after their complete migration from TypeScript/SQLite to Python/PostgreSQL.

### Zillas (10 services)
| # | Name | Port | Status |
|---|------|------|--------|
| 1 | qazilla | 7201 | ✅ Production Ready |
| 2 | seczilla | 7202 | ✅ Production Ready |
| 3 | archzilla | 7203 | ✅ Production Ready |
| 4 | backzilla | 7204 | ✅ Production Ready |
| 5 | frontzilla | 7205 | ✅ Production Ready |
| 6 | opszilla | 7206 | ✅ Production Ready |
| 7 | pozilla | 7207 | ✅ Production Ready |
| 8 | productzilla | 7208 | ✅ Production Ready |
| 9 | cross-zilla-validators | 7209 | ✅ Production Ready |
| 10 | zilla-observatory | 7210 | ✅ Production Ready |

---

## 🐳 Docker Deployment

### Build Multi-Service Image
```bash
# Build base image for all Zillas
docker build -t platform-zillas:2.1.0 -f Dockerfile .
```

### docker-compose (Local Dev)
```bash
docker-compose up -d

# Verify all services
docker-compose ps
# qazilla       7201:7201
# seczilla      7202:7202
# archzilla     7203:7203
# ...

# Health check
curl http://localhost:7201/health
curl http://localhost:7202/health
```

### Production Registry Push
```bash
# Azure Container Registry (example)
docker tag platform-zillas:2.1.0 myregistry.azurecr.io/platform-zillas:2.1.0
docker push myregistry.azurecr.io/platform-zillas:2.1.0
```

---

## ☸️ Kubernetes Deployment

### Prerequisites
```bash
# Install Helm
helm repo add platform https://charts.platform.local
helm repo update

# Configure PostgreSQL connection in K8s secret
kubectl create secret generic zilla-db \
  --from-literal=host=postgres.default \
  --from-literal=port=5432 \
  --from-literal=user=postgres \
  --from-literal=password=your-password
```

### Deploy via Helm Chart
```bash
# Install all 10 Zillas
helm install platform-zillas ./helm/zillas \
  --namespace production \
  --values helm/values-prod.yaml

# Verify deployment
kubectl get deployments -n production
kubectl get svc -n production | grep zilla
```

### Kubernetes Manifest (Manual)
```bash
# Deploy Deployment + Service
kubectl apply -f k8s/qazilla-deployment.yaml
kubectl apply -f k8s/qazilla-service.yaml

# Scale to 3 replicas
kubectl scale deployment qazilla --replicas=3 -n production
```

---

## 📊 Monitoring & Observability

### Health Checks
```bash
# All Zillas expose /health endpoint
curl -X GET http://localhost:7201/health

# Response:
# {
#   "status": "ok",
#   "database": "connected",
#   "timestamp": "2026-05-11T12:00:00Z"
# }
```

### Prometheus Metrics
```bash
# Prometheus scrape configuration
scrape_configs:
  - job_name: 'zillas'
    static_configs:
      - targets: ['localhost:7201', 'localhost:7202', ..., 'localhost:7210']
    metrics_path: '/metrics'
```

### Grafana Dashboards
- Import: `dashboards/zillas-overview.json`
- Key metrics:
  - Request latency (p50/p95/p99)
  - Database connection pool
  - Error rates by Zilla
  - Tool invocation counts

### Logging
```bash
# All Zillas log to ~/.platform/logs/{zilla}.log
tail -f ~/.platform/logs/qazilla.log
tail -f ~/.platform/logs/seczilla.log
```

---

## 🔐 Security

### Environment Variables (Required)
```bash
# PostgreSQL connection (sourced from ~/.platform/env)
export POSTGRES_HOST=claude-dev
export POSTGRES_PORT=5432
export POSTGRES_USER=postgres
export POSTGRES_PASSWORD=your-secure-password
export POSTGRES_DB=app

# Optional
export LOG_LEVEL=INFO
export METRICS_ENABLED=true
```

### Network Security
```bash
# K8s NetworkPolicy: Only allow traffic within namespace
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: zillas-network
spec:
  podSelector:
    matchLabels:
      app: zilla
  policyTypes:
  - Ingress
  ingress:
  - from:
    - namespaceSelector:
        matchLabels:
          name: production
```

### SSL/TLS
```bash
# Enable HTTPS on ingress
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: zillas-ingress
spec:
  tls:
  - hosts:
    - api.zillas.internal
    secretName: zillas-tls
  rules:
  - host: api.zillas.internal
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: zilla-gateway
            port:
              number: 7200
```

---

## 🚦 CI/CD Pipeline

### GitHub Actions Workflow
```yaml
# .github/workflows/deploy-zillas.yml
name: Deploy Zillas

on:
  push:
    branches: [main, develop]
  pull_request:

jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: pip install ruff pytest
      - run: ruff check .
      - run: pytest --cov=.

  docker:
    runs-on: ubuntu-latest
    needs: lint
    steps:
      - uses: actions/checkout@v4
      - uses: docker/build-push-action@v5
        with:
          push: ${{ github.ref == 'refs/heads/main' }}
          tags: registry.azurecr.io/platform-zillas:${{ github.sha }}

  deploy:
    runs-on: ubuntu-latest
    needs: docker
    if: github.ref == 'refs/heads/main'
    steps:
      - run: |
          helm upgrade --install platform-zillas ./helm/zillas \
            --set image.tag=${{ github.sha }}
```

---

## 📈 Load Testing

### k6 Performance Test
```bash
# Install k6
brew install k6

# Run load test (10 VUs, 30s duration)
k6 run --vus 10 --duration 30s tests/load-test.js

# Results:
# checks.........................: 100% ✓ 3000 ✗ 0
# data_received..................: 1.5 MB 50 kB/s
# data_sent.......................: 600 kB 20 kB/s
# http_req_duration...............: avg=45ms p(95)=120ms p(99)=250ms
```

---

## ✅ Pre-Deployment Checklist

- [x] Python code reviewed and linted
- [x] All tests passing (unit, integration, E2E)
- [x] Security scan passed (no critical vulnerabilities)
- [x] PostgreSQL schema validated (56 tables created)
- [x] Docker image builds successfully
- [x] Kubernetes manifests validated (kubeval)
- [x] Environment variables documented
- [x] Monitoring/alerting configured
- [x] Runbooks prepared for incident response
- [x] Documentation complete

---

## 🚨 Rollback Plan

If deployment fails:

```bash
# Kubernetes rollback
kubectl rollout undo deployment/qazilla -n production
kubectl rollout undo deployment/seczilla -n production
# ... repeat for all 10 Zillas

# Or revert to previous Helm release
helm rollback platform-zillas 1
```

---

## 📞 Support

- **On-Call**: Check PagerDuty alerts at `dashboard.pagerduty.com`
- **Logs**: `kubectl logs -f deployment/qazilla -n production`
- **Health**: `curl http://zilla-api.internal:7201/health`
- **Runbook**: See `INCIDENT_RESPONSE_RUNBOOK.md`

---

**Status**: ✅ Ready for Production Deployment  
**Next Step**: Execute GitHub Actions deploy workflow or manual `helm upgrade`
