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
APP_CONFIG_ENDPOINT="$(echo "$ENV_VALUES" \
  | grep '^AZURE_APP_CONFIG_ENDPOINT=' \
  | cut -d '=' -f2- \
  | tr -d '"')"
set -e

# Check for any missing
missing=()
[[ -z "$APP_CONFIG_ENDPOINT" ]]           && missing+=("APP_CONFIG_ENDPOINT")

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
echo -e "${GREEN}🧩 Ensuring runtime settings are complete…${NC}"

echo -e "${BLUE}📦 Creating temporary virtual environment…${NC}"
python -m venv evaluation/.venv_temp
chmod a+r evaluation/.venv_temp/bin/activate
source evaluation/.venv_temp/bin/activate
echo -e "${BLUE}⬇️  Installing requirements…${NC}"
pip install --upgrade pip
pip install -r evaluation/requirements.txt


echo -e "${BLUE}🚀 Running evaluate.py…${NC}"
python -m evaluation.evaluate
echo -e "${GREEN}✅ Finished evaluation.${NC}"

# clean up venv only if we created it
if [[ -n "${AZURE_APP_CONFIG_ENDPOINT:-}" ]]; then
  echo
  echo -e "${BLUE}🧹 Cleaning up…${NC}"
  deactivate
  rm -rf evaluation/.venv_temp
fi