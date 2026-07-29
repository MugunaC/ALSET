# device/run.sh
#!/usr/bin/env bash
set -e

# Load env from .env if present
if [ -f .env ]; then
  export $(grep -v '^#' .env | xargs)
fi

python3 -u device/vehicle_main.py
