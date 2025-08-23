#!/bin/bash
# Synthetic Alert Test Script for EdgeBot Email Notifications
# This script creates a temporary test alert to verify email delivery

set -e

echo "🧪 EdgeBot Email Notification Test"
echo "=================================="

# Check if required commands exist
command -v docker >/dev/null 2>&1 || { echo "❌ Docker is required but not installed."; exit 1; }

# Check if observability stack is running
if ! docker compose -f compose.observability.yml ps | grep -q alertmanager; then
    echo "⚠️  Alertmanager is not running. Starting observability stack..."
    docker compose -f compose.observability.yml up -d
    echo "⏳ Waiting 30s for services to start..."
    sleep 30
fi

echo "📋 Current Email Configuration:"
echo "   SMTP Host: ${ALERT_SMTP_HOST:-'Not set'}"
echo "   SMTP Port: ${ALERT_SMTP_PORT:-'Not set'}"
echo "   From Email: ${ALERT_EMAIL_FROM:-'Not set'}"
echo "   To Email: ${ALERT_EMAIL_TO:-'Not set'}"
echo ""

if [[ -z "${ALERT_EMAIL_TO}" ]]; then
    echo "❌ Email configuration missing. Please set up your .env file first."
    echo "   Copy .env.example to .env and configure your SMTP settings."
    exit 1
fi

echo "🚀 Creating temporary test alert..."

# Backup original alerts
cp prometheus/alerts.yml prometheus/alerts.yml.backup

# Add test alert to the existing alerts file
cat >> prometheus/alerts.yml << 'EOF'

      # Temporary test alert for email verification
      - alert: EmailTestAlert
        expr: vector(1)  # Always fires immediately
        for: 0m
        labels:
          severity: warning
          component: test
          category: email-test
        annotations:
          summary: "Email notification test alert"
          description: "This is a synthetic test alert to verify email notifications are working properly. If you receive this email, your EdgeBot email alerts are configured correctly."
EOF

echo "📨 Restarting Prometheus to load test alert..."
docker compose -f compose.observability.yml restart prometheus

echo "⏳ Waiting 60 seconds for alert to fire and email to be sent..."
sleep 60

# Check if alert is active
echo "🔍 Checking alert status..."
if curl -s http://localhost:9093/api/v1/alerts | grep -q "EmailTestAlert"; then
    echo "✅ Test alert is active in Alertmanager"
    echo "📧 Check your email inbox for the test notification"
    echo "🔗 View alerts: http://localhost:9093/#/alerts"
else
    echo "⚠️  Test alert may not have fired yet. Check http://localhost:9093/#/alerts"
fi

echo ""
echo "🧹 Cleaning up..."
# Restore original alerts
mv prometheus/alerts.yml.backup prometheus/alerts.yml
docker compose -f compose.observability.yml restart prometheus

echo "✅ Test complete!"
echo ""
echo "📋 Next steps:"
echo "   1. Check your email inbox for the test alert"
echo "   2. If no email received, check troubleshooting steps in docs/OBSERVABILITY.md"
echo "   3. View current alerts: http://localhost:9093/#/alerts"
echo "   4. Check Alertmanager logs: docker compose -f compose.observability.yml logs alertmanager"