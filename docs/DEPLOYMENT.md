# Deployment Guide

Choose one method:
- One-Click Script (recommended)
- Docker Compose (manual)
- Python Virtual Environment (advanced)

1) One-Click Script
- Run:

```
curl -fsSL https://raw.githubusercontent.com/iLodeStar/AIOps-EdgeBot-poc/main/deploy.sh | bash
```

- The script installs Docker, fetches the repo, and starts EdgeBot.

2) Docker Compose (manual)
- Requirements: Docker + Docker Compose
- Steps:

```
git clone https://github.com/iLodeStar/AIOps-EdgeBot-poc.git
cd AIOps-EdgeBot-poc/edge_node
cp -n config.example.yaml config.yaml
cp -n .env.example .env
mkdir -p data/out data/logs
docker compose up -d --build
```

- Check:

```
curl -f http://localhost:8081/healthz
docker logs -f edgebot
ls -l data/out
```

3) Python Virtual Environment (advanced)
- Useful for development or environments without Docker
- Steps:

```
cd edge_node
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python -m app.main --config config.yaml
```

- Stop with Ctrl+C

Configuration overview
- `edge_node/config.yaml` controls inputs and outputs
- File output (default): `url: file:///var/lib/edgebot/out`
  - Files appear under `edge_node/data/out` on the host
- Server output (optional): set mothership URL and auth token

Networking
- Open these ports if receiving logs from other machines:
  - UDP 5514, TCP 5515 (syslog)
- Health/metrics are on 8081 (local only by default)

Upgrade
- Pull latest code and rebuild:

```
cd edge_node
docker compose build --no-cache
docker compose up -d
```

Uninstall
- Stop and remove containers:

```
cd edge_node && docker compose down
```

- Remove data (optional):

```
rm -rf edge_node/data
```