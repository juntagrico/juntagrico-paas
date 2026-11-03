#!/bin/bash

cd /var/django/adminconsole
export $(cat .venv/env.env | xargs)
.venv/bin/python manage.py stop_staging