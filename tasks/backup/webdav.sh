#!/bin/bash
set -euo pipefail

if [ "$#" -ne 2 ]; then
    echo "Usage: $0 <username>:<pwd> <url>"
    exit 1
fi

backup_file="$(cat -)"

tar -czvf "$backup_file.tar.gz" "$backup_file"
curl -T "$backup_file.tar.gz" -u "$1" -H 'X-Requested-With: XMLHttpRequest' "$2"
rm -f "$backup_file.tar.gz"

echo "$backup_file"