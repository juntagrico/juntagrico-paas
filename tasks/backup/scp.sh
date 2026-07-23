#!/bin/bash
set -euo pipefail

if [ "$#" -ne 1 ]; then
    echo "Usage: $0 <username>@<host>:<absolute_path>"
    exit 1
fi

backup_file="$(cat -)"
scp "$backup_file" "$1"

echo "$backup_file"