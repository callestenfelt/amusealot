#!/bin/bash
# Deploy scripts to VPS and fix line endings on shell scripts.
# Usage: ./deploy.sh

set -euo pipefail

HOST="root@77.42.40.207"
SSH_KEY="$HOME/.ssh/id_ed25519"
REMOTE="/opt/musemaniac"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/scripts"

echo "Deploying to $HOST..."

# Deploy Python scripts
scp -i "$SSH_KEY" "$SCRIPT_DIR"/*.py "$HOST:$REMOTE/scripts/"

# Deploy shell scripts
scp -i "$SSH_KEY" "$SCRIPT_DIR"/*.sh "$HOST:$REMOTE/scripts/"

# Deploy templates and static files
scp -i "$SSH_KEY" -r "$SCRIPT_DIR/templates" "$HOST:$REMOTE/scripts/"
scp -i "$SSH_KEY" -r "$SCRIPT_DIR/static" "$HOST:$REMOTE/scripts/"

# Strip Windows line endings from all shell scripts
ssh -i "$SSH_KEY" "$HOST" "sed -i 's/\r//' $REMOTE/scripts/*.sh && echo 'Line endings fixed'"

# Restart Flask app to pick up template changes
ssh -i "$SSH_KEY" "$HOST" "systemctl restart musemaniac-subscriber && echo 'Service restarted'"

echo "Done."
