#!/usr/bin/env bash
set -euo pipefail

# EdgeBot One-Click Deployment Script
# - Installs Docker and Compose if needed
# - Fetches the repo (if not present)
# - Creates required folders
# - Starts EdgeBot with docker compose
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/iLodeStar/AIOps-EdgeBot-poc/main/deploy.sh | bash
#   OR run locally from repo root: ./deploy.sh
#
# Requirements:
#   - Linux server with outbound internet access
#   - A user with sudo privileges

REPO_URL="https://github.com/iLodeStar/AIOps-EdgeBot-poc.git"
INSTALL_DIR="/opt/edgebot"
COMPOSE_DIR="edge_node"
COMPOSE_FILE="${COMPOSE_DIR}/docker-compose.yaml"
DATA_DIR_REL="${COMPOSE_DIR}/data"
ENV_FILE="${COMPOSE_DIR}/.env"
ENV_EXAMPLE="${COMPOSE_DIR}/.env.example"
CONFIG_FILE="${COMPOSE_DIR}/config.yaml"
CONFIG_EXAMPLE="${COMPOSE_DIR}/config.example.yaml"

need_cmd() { command -v "$1" >/dev/null 2>&1; }

header() {
  echo "==============================================="
  echo "$1"
  echo "==============================================="
}

ensure_sudo() {
  if [ "${EUID}" -ne 0 ]; then
    if need_cmd sudo; then
      SUDO="sudo"
    else
      echo "This script needs root privileges (sudo). Please install sudo or run as root."
      exit 1
    fi
  else
    SUDO=""
  fi
}

install_docker() {
  header "Checking Docker and Docker Compose"
  if ! need_cmd docker; then
    echo "Docker not found. Installing Docker..."
    ${SUDO} sh -c "curl -fsSL https://get.docker.com | sh"
  else
    echo "Docker already installed."
  fi

  if ! docker ps >/dev/null 2>&1; then
    echo "Adding current user to docker group..."
    ${SUDO} usermod -aG docker "${USER}" || true
    echo "You may need to log out and back in for docker group permissions to apply."
  fi

  if docker compose version >/dev/null 2>&1; then
    echo "Docker Compose plugin is available."
  elif need_cmd docker-compose; then
    echo "Legacy docker-compose is available."
  else
    echo "Installing Docker Compose plugin..."
    if need_cmd apt; then
      ${SUDO} apt-get update -y
      ${SUDO} apt-get install -y docker-compose-plugin
    fi
    if ! docker compose version >/dev/null 2>&1; then
      echo "Could not install Docker Compose plugin automatically."
      echo "Please install Docker Compose and re-run this script."
      exit 1
    fi
  fi
}

fetch_repo_if_missing() {
  header "Fetching repository if needed"
  if [ -f "${COMPOSE_FILE}" ]; then
    echo "Found compose file at ${COMPOSE_FILE} (running from existing repo)."
    return
  fi
  echo "Repo not found in current directory. Installing to ${INSTALL_DIR} ..."
  ${SUDO} mkdir -p "${INSTALL_DIR}"
  if [ ! -d "${INSTALL_DIR}/.git" ]; then
    ${SUDO} rm -rf "${INSTALL_DIR:?}"/*
    ${SUDO} git clone --depth 1 "${REPO_URL}" "${INSTALL_DIR}"
  fi
  cd "${INSTALL_DIR}"
}

prepare_files_and_folders() {
  header "Preparing configuration and data directories"
  mkdir -p "${DATA_DIR_REL}/out" "${DATA_DIR_REL}/logs"
  if [ ! -f "${ENV_FILE}" ]; then
    if [ -f "${ENV_EXAMPLE}" ]; then
      cp -n "${ENV_EXAMPLE}" "${ENV_FILE}"
      echo "Created ${ENV_FILE} from example."
    else
      echo "EDGEBOT_HOST=0.0.0.0" > "${ENV_FILE}"
      echo "Created minimal ${ENV_FILE}."
    fi
  fi
  if [ ! -f "${CONFIG_FILE}" ]; then
    if [ -f "${CONFIG_EXAMPLE}" ]; then
      cp -n "${CONFIG_EXAMPLE}" "${CONFIG_FILE}"
      echo "Created ${CONFIG_FILE} from example."
    else
      echo "Using default config.yaml inside image if present."
    fi
  fi
}

start_services() {
  header "Starting EdgeBot with Docker Compose"
  if docker compose -f "${COMPOSE_FILE}" up -d --build; then
    echo "EdgeBot is starting..."
  else
    echo "Falling back to legacy docker-compose..."
    docker-compose -f "${COMPOSE_FILE}" up -d --build
  fi
  echo
  echo "Checking container status..."
  if docker compose -f "${COMPOSE_FILE}" ps || docker-compose -f "${COMPOSE_FILE}" ps; then
    echo "EdgeBot should be up shortly."
  fi
  echo
  echo "Next steps:"
  echo "- Health check:   curl -f http://localhost:8081/healthz"
  echo "- Metrics:        curl -s http://localhost:8081/metrics | head"
  echo "- Logs (docker):  docker logs -f edgebot"
  echo "- Data payloads:  $(pwd)/${DATA_DIR_REL}/out"
  echo
  echo "Admin Guide: docs/ADMIN_GUIDE.md"
  echo "Deployment:  docs/DEPLOYMENT.md"
}

main() {
  ensure_sudo
  install_docker
  fetch_repo_if_missing
  prepare_files_and_folders
  start_services
}

main "$@"