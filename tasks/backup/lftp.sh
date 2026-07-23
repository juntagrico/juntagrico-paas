#!/bin/bash
set -euo pipefail

if [ "$#" -lt 3 ]; then
    echo "Usage: $0 <username> <host> <destination_path>"
    exit 1
fi

lftp -u "$1" "$2" << EOF
set ssl:verify-certificate no
set sftp:auto-confirm yes
set ftp:ssl-force true
set ftp:ssl-protect-data true

cd "$3"
mkdir -f $(date +%Y%m%d)
cd $(date +%Y%m%d)

put -e "$backup_file"

bye
EOF

echo "$backup_file"
