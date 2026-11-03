#!/bin/bash
set -euo pipefail

DATE=`date +"%m-%d-%y"`

mkdir -p /var/django/backup/full
cd /var/django/backup/full
find . -type f -mtime +30 -exec rm -f {} \;

pg_dumpall -U postgres > ${DATE}_full.bak

echo "/var/django/backup/full/${DATE}_full.bak"
