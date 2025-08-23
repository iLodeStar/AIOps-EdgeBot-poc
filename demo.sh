#!/bin/bash
# 
# Complete EdgeBot + Mothership + Loki Demo
# Shows the full data pipeline from edge collection to Grafana visualization
#

set -e

echo "🚀 EdgeBot + Mothership + Loki Demo"
echo "===================================="
echo

# Check if we're in the right directory
if [ ! -d "edge_node" ] || [ ! -d "mothership" ]; then
    echo "❌ Please run this script from the AIOps-EdgeBot-poc root directory"
    exit 1
fi

echo "📦 Installing dependencies..."
cd edge_node && pip install -r requirements.txt --quiet
cd ../mothership && pip install -r requirements.txt --quiet
cd ..

echo "✅ Dependencies installed"
echo

echo "🐳 Starting observability stack (Loki + Grafana)..."
docker-compose -f compose.observability.yml up -d

echo "⏳ Waiting for services to be ready..."
sleep 10

# Check if Loki is ready
if curl -s http://localhost:3100/ready > /dev/null; then
    echo "✅ Loki is ready at http://localhost:3100"
else
    echo "⚠️  Loki may not be ready yet, continuing..."
fi

# Check if Grafana is ready
if curl -s http://localhost:3000/api/health > /dev/null; then
    echo "✅ Grafana is ready at http://localhost:3000 (admin/admin)"
else
    echo "⚠️  Grafana may not be ready yet, continuing..."
fi

echo

echo "🖥️  Starting mothership with dual sinks..."
cd mothership

# Start mothership in background with dual sinks enabled
export LOKI_ENABLED=true
export LOKI_URL=http://localhost:3100
export TSDB_ENABLED=true
export LOG_LEVEL=INFO

echo "   Mothership configuration:"
echo "   - LOKI_ENABLED=true"
echo "   - TSDB_ENABLED=true" 
echo "   - Server: http://localhost:8080"
echo

# Start mothership in background
nohup python main.py > /tmp/mothership.log 2>&1 &
MOTHERSHIP_PID=$!

cd ..

echo "⏳ Waiting for mothership to start..."
sleep 5

# Check mothership health
if curl -s http://localhost:8080/health | jq -r .status > /dev/null 2>&1; then
    echo "✅ Mothership is healthy"
    curl -s http://localhost:8080/health | jq .
else
    echo "⚠️  Mothership health check failed, but continuing..."
fi

echo

echo "📨 Sending test data to mothership..."

# Send some test data
cat << 'EOF' > /tmp/test_payload.json
{
  "messages": [
    {
      "message": "EdgeBot started successfully",
      "timestamp": 1640995200,
      "type": "system",
      "service": "edgebot", 
      "host": "demo-edge-01",
      "site": "demo-site",
      "env": "demo",
      "severity": "info"
    },
    {
      "message": "Syslog server listening on port 5514",
      "timestamp": 1640995260,
      "type": "syslog",
      "service": "edgebot",
      "host": "demo-edge-01", 
      "site": "demo-site",
      "env": "demo",
      "severity": "info",
      "port": 5514
    },
    {
      "message": "Weather data collected: 22.5°C, 65% humidity",
      "timestamp": 1640995320,
      "type": "weather",
      "service": "edgebot",
      "host": "demo-edge-01",
      "site": "demo-site", 
      "env": "demo",
      "severity": "info",
      "temperature": 22.5,
      "humidity": 65
    },
    {
      "message": "Connection timeout to upstream server",
      "timestamp": 1640995380,
      "type": "application",
      "service": "edgebot",
      "host": "demo-edge-01",
      "site": "demo-site",
      "env": "demo", 
      "severity": "error",
      "error_code": "TIMEOUT"
    }
  ],
  "batch_size": 4,
  "timestamp": 1640995200,
  "source": "demo-edge-01",
  "is_retry": false
}
EOF

# Send the payload
RESPONSE=$(curl -s -X POST http://localhost:8080/ingest \
  -H "Content-Type: application/json" \
  -d @/tmp/test_payload.json)

echo "📊 Mothership response:"
echo "$RESPONSE" | jq .
echo

echo "🔍 Checking data in Loki..."
sleep 2

# Query Loki for our test data
LOKI_QUERY='%7Bservice%3D%22edgebot%22%7D'  # {service="edgebot"} URL encoded
LOKI_RESPONSE=$(curl -s "http://localhost:3100/loki/api/v1/query_range?query=${LOKI_QUERY}&start=$(date -d '1 hour ago' +%s)000000000&end=$(date +%s)000000000" || echo "Query failed")

if echo "$LOKI_RESPONSE" | jq -e .data.result[0] > /dev/null 2>&1; then
    LOG_COUNT=$(echo "$LOKI_RESPONSE" | jq '.data.result[0].values | length')
    echo "✅ Found $LOG_COUNT log entries in Loki"
    echo "   Sample log lines:"
    echo "$LOKI_RESPONSE" | jq -r '.data.result[0].values[0:2][] | "   - " + .[1]'
else
    echo "⚠️  Could not retrieve logs from Loki (may need more time)"
fi

echo

echo "🎯 Demo Summary"
echo "==============="
echo
echo "Services running:"
echo "  🖥️  Mothership:  http://localhost:8080"
echo "      - Health:    http://localhost:8080/health"
echo "      - Ingest:    POST http://localhost:8080/ingest"
echo
echo "  📊 Loki:        http://localhost:3100"
echo "      - Ready:     http://localhost:3100/ready"
echo "      - Metrics:   http://localhost:3100/metrics"
echo
echo "  📈 Grafana:     http://localhost:3000"
echo "      - Login:     admin/admin"
echo "      - Explore:   http://localhost:3000/explore"
echo

echo "📋 Next Steps:"
echo "  1. Open Grafana: http://localhost:3000"
echo "  2. Go to Explore and select Loki data source"
echo "  3. Try these LogQL queries:"
echo "     - {service=\"edgebot\"}"
echo "     - {service=\"edgebot\", severity=\"error\"}"
echo "     - {service=\"edgebot\"} |= \"Weather\""
echo "     - sum by (severity) (count_over_time({service=\"edgebot\"}[1h]))"
echo
echo "  4. Configure EdgeBot nodes to send to: http://localhost:8080/ingest"
echo

echo "🧹 Cleanup:"
echo "  To stop everything:"
echo "    kill $MOTHERSHIP_PID"
echo "    docker-compose -f compose.observability.yml down"
echo

# Keep the script running to show logs
echo "📄 Showing mothership logs (Ctrl+C to stop):"
echo "--------------------------------------------"
tail -f /tmp/mothership.log