# juntagrico PaaS

## Installation

The following installation steps have been tested on Ubuntu 26.04 LTS.

### Prepare Database

Using postgres

`apt install postgresql`

Create a new superuser `adminconsole`

`sudo -u postgres createuser --interactive --pwprompt`

Create a database

`sudo -u postgres createdb adminconsole`


### Install from Source

```
mkdir -p /var/django/adminconsole
cd /var/django/adminconsole
git clone https://github.com/juntagrico/juntagrico-paas.git .
```

open `adminconsole/settings.py` and add your domain to the `ALLOWED_HOSTS`

### Create virtual environment

```
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

create `/var/django/adminconsole/.venv/env.env` and define all the config variables.

```
JS_DATABASE_NAME=
JS_DATABASE_USER=
JS_DATABASE_PASSWORD=
JS_DATABASE_HOST=localhost
JS_KEY=
JUNTAGRICO_EMAIL_HOST=
JUNTAGRICO_EMAIL_USER=
JUNTAGRICO_EMAIL_PASSWORD=
JUNTAGRICO_EMAIL_PORT=
JUNTAGRICO_EMAIL_TLS=
JUNTAGRICO_EMAIL_SSL=
GITHUB_CLIENT_ID=
GITHUB_CLIENT_SECRET=
```

### Collect static files

Enter venv if not done already
`source .venv/bin/activate`

`python manage.py collectstatic`

### Initialize database

Enter venv if not done already
`source .venv/bin/activate`

Load env
```
while IFS== read -r key value; do
  printf -v "$key" %s "$value" && export "$key"
done <.venv/env.env
```

Initialize database
`python manage.py migrate`

Create superuser

`python manage.py createsuperuser`

### setup Gunicorn

create `/etc/systemd/system/gunicorn.service` and paste the following:

```
[Unit]
Description=gunicorn daemon
After=network.target

[Service]
User=root
Group=www-data
EnvironmentFile=/var/django/adminconsole/.venv/env.env
WorkingDirectory=/var/django/adminconsole/
ExecStart=/var/django/adminconsole/.venv/bin/gunicorn --access-logfile - --workers 1 --bind unix:/var/django/adminconsole/adminconsole.sock adminconsole.wsgi:application -t 60000

[Install]
WantedBy=multi-user.target
```

enable and start:

```
systemctl daemon-reload
systemctl enable gunicorn
systemctl start gunicorn
systemctl status gunicorn
```

### Setup reverse proxy

Using nginx

`apt install nginx`

Create `/etc/nginx/sites-available/admin.juntagrico.app` and paste the following:

use your actual domain (server_name)
```
server {
    listen 80;
    server_name admin.juntagrico.app;

    location = /favicon.ico { access_log off; log_not_found off; }
    location /static/ {
        root /var/django/adminconsole;
    }

    location / {
        include proxy_params;
        proxy_pass http://unix:/var/django/adminconsole/adminconsole.sock;
    }
}
```

enable the site
```
ln -s /etc/nginx/sites-available/admin.juntagrico.app /etc/nginx/sites-enabled/
nginx -t
systemctl reload nginx
```

### Enable HTTPS

using certbot

```
snap install --classic certbot
ln -s /snap/bin/certbot /usr/local/bin/certbot
```

remove the default site as it may disturb certbot
```
rm /etc/nginx/sites-enabled/default
```

Use your domain
```
certbot --nginx -d admin.juntagrico.app
```

### Open in browser

You can now open your juntagrico PaaS in the browser.

### Install Docker

The juntagrico apps will need docker to run.
See https://docs.docker.com/engine/install/ubuntu/

To release unused docker images add this to the crontab
`5 1 * * * docker image prune -f`

### Enable staging auto-stop

Add this to the crontab to stop expired staging app containers
`0 2 * * * /var/django/adminconsole/tasks/stop_staging.sh`


## Create Demo App

The juntagrico demo app can be installed like any other app from https://github.com/juntagrico/juntagrico-demo

Make sure the instance is reset at least every day:
`0 4 * * * /var/django/adminconsole/tasks/reset_demo.sh`

## Auto Upgrade

If desired, add this to crontab for apps that should upgrade automatically
`0 2 * * * /var/django/adminconsole/tasks/redeploy-v2.sh <app-name>`
