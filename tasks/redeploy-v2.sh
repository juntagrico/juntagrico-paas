#!/bin/bash

cd /var/django/adminconsole
export $(cat .venv/env.env | xargs)
.venv/bin/python manage.py redeploy --upgrade $1