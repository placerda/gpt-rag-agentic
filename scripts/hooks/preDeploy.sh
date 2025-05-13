#!/usr/bin/env bash
# ------------------------------------------------------------------------------
# predeploy.sh — validate env, optionally load App Config, then build & push
# ------------------------------------------------------------------------------

set -euo pipefail

YELLOW='\033[0;33m'
BLUE='\033[0;34m'
GREEN='\033[0;32m'
NC='\033[0m' # No Color

echo
echo "🔍 Fetching all 'azd' environment values…"
# This must succeed or we cannot continue
ENV_VALUES="$(azd env get-values)"

# Temporarily allow greps to fail without exiting
set +e
AZURE_CONTAINER_REGISTRY_NAME="$(echo "$ENV_VALUES" \
  | grep '^AZURE_CONTAINER_REGISTRY_NAME=' \
  | cut -d '=' -f2- \
  | tr -d '"')"
AZURE_CONTAINER_REGISTRY_ENDPOINT="$(echo "$ENV_VALUES" \
  | grep '^AZURE_CONTAINER_REGISTRY_ENDPOINT=' \
  | cut -d '=' -f2- \
  | tr -d '"')"
AZURE_RESOURCE_GROUP="$(echo "$ENV_VALUES" \
  | grep '^AZURE_RESOURCE_GROUP=' \
  | cut -d '=' -f2- \
  | tr -d '"')"
set -e

# Check for any missing
missing=()
[[ -z "$AZURE_CONTAINER_REGISTRY_NAME" ]]           && missing+=("AZURE_CONTAINER_REGISTRY_NAME")
[[ -z "$AZURE_CONTAINER_REGISTRY_ENDPOINT" ]]       && missing+=("AZURE_CONTAINER_REGISTRY_ENDPOINT")
[[ -z "$AZURE_RESOURCE_GROUP" ]]                    && missing+=("AZURE_RESOURCE_GROUP")
[[ -z "$AZURE_APP_CONFIG_ENDPOINT" ]]               && missing+=("AZURE_APP_CONFIG_ENDPOINT")

if [[ ${#missing[@]} -gt 0 ]]; then
  echo -e "${YELLOW}⚠️  Missing required environment variables:${NC}"
  for var in "${missing[@]}"; do
    echo "    • $var"
  done
  echo
  echo "Please set them before running this script, e.g.:"
  echo "  azd env set <NAME> <VALUE>"
  exit 1
fi

echo -e "${GREEN}✅ All required azd env values are set.${NC}"
echo

echo
echo -e "${GREEN}🔐 Logging into ACR (${AZURE_CONTAINER_REGISTRY_NAME})…${NC}"
az acr login --name "${AZURE_CONTAINER_REGISTRY_NAME}"

echo -e "${BLUE}🛢️ Defining TAG…${NC}"
TAG="${TAG:-$(git rev-parse --short HEAD)}"
azd env set TAG "${TAG}"
echo -e "${GREEN}✅ TAG set to: ${TAG}${NC}"

echo
echo -e "${GREEN}🛠️  Building Docker image…${NC}"
docker build \
  -t "${AZURE_CONTAINER_REGISTRY_ENDPOINT}/azure-gpt-rag/orchestrator-build:${TAG}" \
  .

echo
echo -e "${GREEN}📤 Pushing image…${NC}"
docker push "${AZURE_CONTAINER_REGISTRY_ENDPOINT}/azure-gpt-rag/orchestrator-build:${TAG}"

echo
echo -e "${GREEN}🧩 Ensuring runtime settings are complete…${NC}"
echo -e "${BLUE}📦 Creating temporary virtual environment…${NC}"
python -m venv scripts/appconfig/.venv_temp
chmod a+r scripts/appconfig/.venv_temp/bin/activate
source scripts/appconfig/.venv_temp/bin/activate
echo -e "${BLUE}⬇️  Installing requirements…${NC}"
pip install --upgrade pip
pip install -r scripts/appconfig/requirements.txt
echo -e "${BLUE}🚀 Running app_defaults.py…${NC}"
python -m scripts.appconfig.app_defaults
echo -e "${GREEN}✅ Finished app settings validation.${NC}"

# clean up venv only if we created it
if [[ -n "${AZURE_APP_CONFIG_ENDPOINT:-}" ]]; then
  echo
  echo -e "${BLUE}🧹 Cleaning up…${NC}"
  deactivate
  rm -rf scripts/appconfig/.venv_temp
fi