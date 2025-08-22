# User Guide

What EdgeBot does
- Listens for logs and other data
- Groups them into small batches
- Saves them to files (default) or sends to a server

Find your data files
- Default location: `edge_node/data/out`
- Each batch creates:
  - A readable JSON file: `payload-... .json`
  - A compressed file: `payload-... .json.gz`
- These files are identical after decompressing the .gz

Send a test log (from the same machine)
- UDP syslog:

```
echo "<34>Oct 11 22:14:15 mymachine su: 'su root' failed for lonvick on /dev/pts/8" | nc -u localhost 5514
```

- TCP syslog:

```
echo "<165>1 2003-08-24T05:14:15.000003-07:00 192.0.2.1 myproc 8710 - - %% It's time to make the do-nuts." | nc localhost 5515
```

Check health and metrics
- Health: `curl -f http://localhost:8081/healthz`
- Metrics: `curl -s http://localhost:8081/metrics | head`

Change basic settings
- Edit `edge_node/config.yaml`
  - Turn inputs on/off, change ports, change output (file vs HTTPS)
- Restart: `cd edge_node && docker compose up -d`

Send to a server (optional)
- Ask your admin for:
  - Ingest URL (HTTPS)
  - Auth token
- Edit config.yaml:

```
output:
  mothership:
    url: "https://your-server/ingest"
    auth_token: "your-token"
    compression: true
    tls_verify: true
```

- Restart the app

Troubleshooting
- App logs: `docker logs -f edgebot`
- No files created:
  - Check `edge_node/data/out` exists and is writable
  - Make sure inputs are enabled, or send a test log
- Ports in use:
  - Change ports in `edge_node/docker-compose.yaml` and `edge_node/config.yaml`