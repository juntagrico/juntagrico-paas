#!/bin/bash
set -euo pipefail

if [ "$#" -ne 1 ]; then
    echo "Usage: $0 <container>"
    exit 1
fi

DATE=`date +"%m-%d-%y"`

mkdir -p "/var/django/backup/ind/$1"
cd "/var/django/backup/ind/$1"
find . -type f -mtime +5 -exec rm -f {} \;

pg_dump -U postgres "$1" > ${DATE}_${1}.bak
echo "/var/django/backup/ind/$1/${DATE}_$1.bak"
