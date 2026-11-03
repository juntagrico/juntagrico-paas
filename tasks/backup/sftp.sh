#!/bin/bash
set -euo pipefail

if [ "$#" -lt 1 ]; then
    echo "Usage: $0 <username>@<host>:<absolute_path> [port]"
    exit 1
fi

port=${2:-"22"}

backup_file="$(cat -)"
# batch mode: abort and exit non-zero if the upload fails
sftp -b - -P "${port}" "$1" <<< "put \"$backup_file\""

echo "$backup_file"
