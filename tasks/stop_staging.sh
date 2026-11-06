#!/bin/bash

cd /var/django/adminconsole || exit
export $(cat .venv/env.env | xargs)
.venv/bin/python manage.py stop_staging