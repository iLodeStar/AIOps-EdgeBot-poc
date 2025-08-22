# EdgeBot Admin Guide (Non-Technical)

This guide helps you install, start, stop, and check EdgeBot on a server. No programming required.

What is EdgeBot?
- A small program that listens for system logs and other data.
- It saves the data in small files or sends it to a central server.
- It is safe, efficient, and runs as a normal (non-admin) user inside a container.

Before you start
- You need a Linux server (Ubuntu, Debian, RHEL, or similar).
- You need internet access to download the software.
- You need a user account with "sudo" (admin) rights.

Install in one step
- Copy and paste this command into your server terminal:

```
curl -fsSL https://raw.githubusercontent.com/iLodeStar/AIOps-EdgeBot-poc/main/deploy.sh | bash
```

What the script does
- Installs Docker (if missing)
- Downloads EdgeBot (if not already present)
- Starts EdgeBot automatically
- Sets up folders for data and logs

How to check it's running
- Health check:

```
curl -f http://localhost:8081/healthz
```

If you get "OK" or a success response code, it is healthy.

- See the latest logs:

```
docker logs -f edgebot
```

- Where are the data files?

```
edge_node/data/out
```

You will see files like payload-2025-01-01T12-00-00Z.json.gz and .json

How to stop and start EdgeBot
- Stop:

```
cd edge_node
docker compose down
```

- Start:

```
cd edge_node
docker compose up -d
```

How to update EdgeBot
- Pull the latest version:

```
cd /opt/edgebot   # or your repo folder
git pull
cd edge_node
docker compose build --no-cache
docker compose up -d
```

Your data and logs remain in edge_node/data

How to change basic settings
- Edit the file: edge_node/config.yaml
- Common changes:
  - Turn on or off the syslog listener
  - Change which port to listen on (default UDP 5514, TCP 5515)
  - Save data to files (default) or send to a server
- After changes, restart:

```
cd edge_node && docker compose up -d
```

Backups
- Your data files are in edge_node/data
- To back up:
  - Stop the app: `cd edge_node && docker compose down`
  - Copy the folder `edge_node/data` to backup storage
  - Start again: `docker compose up -d`

Security tips
- Ports 5514/udp and 5515/tcp will accept logs from your network
- If you only collect logs from the same server, you can close those ports to the network
- If you send data to a cloud server, use HTTPS with a token (ask your security team for the URL and token)

Troubleshooting
- The app won't start:
  - Run: `docker compose ps`
  - Check the logs: `docker logs edgebot`
- Health check fails:
  - Run: `curl -v http://localhost:8081/healthz`
  - Check that port 8081 is open locally
- No data files appear:
  - Check folder: `edge_node/data/out`
  - Send a test syslog message (see User Guide)
- Ports already in use:
  - Change the ports in `edge_node/docker-compose.yaml` and `edge_node/config.yaml`

Support
- Open a GitHub issue with what you tried and any error messages

Glossary
- Container: A lightweight, isolated program
- Port: A numbered door on your server that programs use to talk
- Syslog: A standard way servers send their logs