#!/bin/bash

cd /var/django/adminconsole || exit
export $(cat .venv/env.env | xargs)
.venv/bin/python manage.py redeploy --upgrade $1