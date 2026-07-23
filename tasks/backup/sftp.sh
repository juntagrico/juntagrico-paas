#!/bin/bash
set -euo pipefail

if [ "$#" -lt 1 ]; then
    echo "Usage: $0 <username>@<host>:<absolute_path> [port]"
    exit 1
fi

port=${2:-"22"}

sftp -P "${port}" "$1" <<< "put $backup_file"

echo "$backup_file"
