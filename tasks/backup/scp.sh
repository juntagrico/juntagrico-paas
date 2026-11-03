#!/bin/bash
set -euo pipefail

if [ "$#" -ne 1 ]; then
    echo "Usage: $0 <username>@<host>:<absolute_path>"
    exit 1
fi

backup_file="$(cat -)"
scp -B -o StrictHostKeyChecking=yes "$backup_file" "$1" || scp_status=$?

echo "$backup_file"
exit "${scp_status:-0}"
