#!/usr/bin/env bash
# Set up the control node from nothing. Managed nodes need no bootstrapping:
# Python and sshd is the whole requirement, which is Ansible's main advantage
# over an agent-based tool.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

VENV="${VENV:-.venv}"

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 is required but not installed." >&2
  exit 1
fi

echo "==> Creating the virtual environment in ${VENV}"
python3 -m venv "${VENV}"
"${VENV}/bin/pip" install --quiet --upgrade pip
"${VENV}/bin/pip" install --quiet -r requirements.txt

echo "==> Installing Galaxy collections"
"${VENV}/bin/ansible-galaxy" install -r requirements.yml

echo "==> Verifying the installation"
"${VENV}/bin/ansible" --version | head -1
"${VENV}/bin/ansible-lint" --version | head -1

cat <<'NEXT'

Done. Next steps:

  source .venv/bin/activate

  make check                         # lint, syntax, unit tests
  make dry-run                       # converge dev in check mode
  make tags                           # see what you can target

  ansible-playbook -i inventories/production playbooks/site.yml \
      -e confirm=production          # production needs this flag

NEXT
