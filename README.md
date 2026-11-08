# juntagrico PaaS

## Installation

The following installation steps have been tested on Ubuntu 26.04 LTS.

### Prepare Database

Using postgres

`apt install postgresql`

Create a new superuser `juntagrico`

`sudo -u postgres createuser -s --pwprompt juntagrico`

Create a database

`sudo -u postgres createdb adminconsole`


### Install Docker

The juntagrico apps will need docker to run.
See https://docs.docker.com/engine/install/ubuntu/

Set up a persistent log-driver.
Add this to `/etc/docker/daemon.json` or create the file if it doesn't exist.
```
{
  "log-driver": "journald"
}
```

To release unused Docker images, install the systemd timer:
```
cp setup/timers/juntagrico-docker-prune.timer /etc/systemd/system/
cp setup/timers/juntagrico-docker-prune.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now juntagrico-docker-prune.timer
```


### Install from Source

create local user with required permissions
```
useradd -m -g www-data -s /bin/bash juntagrico
usermod -aG docker juntagrico
install -d -o juntagrico -g www-data /var/django/projects
install -d -o juntagrico /var/django/domains
```

allow the user to request certificates. The script must be a copy owned by root, never a symlink into the repository
```
install -o root -g root -m 0755 setup/juntagrico-certbot /usr/local/sbin/juntagrico-certbot
install -o root -g root -m 0440 setup/50-juntagrico-paas /etc/sudoers.d/50-juntagrico-paas
visudo -c
```

install with git
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

copy the config variables and define all values. Then save the file.
```
cp setup/env.env /var/django/adminconsole/.venv/env.env
nano /var/django/adminconsole/.venv/env.env
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

Install gunicorn
```
apt install gunicorn
```


copy the configuration:

```
cp setup/gunicorn.service /etc/systemd/system/gunicorn.service
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

copy the config file and open it to change `server_name` to your domain.
```
cp setup/admin.juntagrico.app /etc/nginx/sites-available/admin.juntagrico.app
nano /etc/nginx/sites-available/admin.juntagrico.app
```

copy the global juntagrico config:
```
cp setup/nginx/juntagrico-http.conf /etc/nginx/conf.d/
cp setup/nginx/juntagrico-common.conf /etc/nginx/snippets/
cp setup/nginx/juntagrico-domain.conf /etc/nginx/snippets/
```

The `juntagrico-common.conf` snippet contains shared security headers and probe-blocking rules used by both the admin site and app domains.
The `juntagrico-domain.conf` snippet contains app-specific server configuration: maintenance mode, static/media locations, and proxy pass. It includes `juntagrico-common.conf` for the shared parts.
The `juntagrico-http.conf` file contains map directives, rate-limiting zones, a default server block that rejects unmatched hostnames on HTTP (80) with return 444 and on HTTPS (443) with `ssl_reject_handshake`, and the include for all domain configs.
Per-domain variables (`$juntagrico_app_name`, `$juntagrico_app_port`) are set via `set` directives in each domain's nginx config, which is generated automatically from the `domain.txt` template when a domain is added through the admin interface.

enable the site
```
ln -s /etc/nginx/sites-available/admin.juntagrico.app /etc/nginx/sites-enabled/
nginx -t && systemctl reload nginx
```

If nginx is the public facing proxy it is recommended to set `X-Forwarded-For` to the real IP address.
Modify `/etc/nginx/proxy_params` and change this line:
```
proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
```
to:
```
proxy_set_header X-Forwarded-For $remote_addr;
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


### Enable staging auto-stop

Install the systemd timer to stop expired staging app containers daily at 02:00:
```
cp setup/timers/juntagrico-stop-staging.timer /etc/systemd/system/
cp setup/timers/juntagrico-stop-staging.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now juntagrico-stop-staging.timer
```


## Create Demo App

The juntagrico demo app can be installed like any other app from https://github.com/juntagrico/juntagrico-demo

Make sure the instance is re-initialized daily at 04:00 using the systemd timer:
```
cp setup/timers/juntagrico-reset-demo.timer /etc/systemd/system/
cp setup/timers/juntagrico-reset-demo.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now juntagrico-reset-demo.timer
```

Also activate the automatic redeploy cronjob for the demo app.

## Refresh docker base images

To pull updated Docker images for supported Python versions weekly:
```
cp setup/timers/juntagrico-docker-pull.timer /etc/systemd/system/
cp setup/timers/juntagrico-docker-pull.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now juntagrico-docker-pull.timer
```

To view all scheduled timers and their next run time:
```
systemctl list-timers --all
```

## Install other services

install the `redeploy@` systemd template service:
```
cp setup/redeploy@.service /etc/systemd/system/
systemctl daemon-reload
```

## Maintenance Mode

On the first time, copy the maintenance page and customize it if needed:
```
cp setup/maintenance.html /var/www/
```

To turn maintenance mode on do
```
touch /var/www/MAINTENANCE_MODE
systemctl reload nginx
```

To turn it off do
```
rm -f /var/www/MAINTENANCE_MODE
systemctl reload nginx
```


## App network isolation

By default an app runs in the network of the server (`network_mode=host`) and can reach every service on it.
With network isolation, an app runs in the Docker network `juntagrico-apps` (172.30.0.0/22, gateway 172.30.0.1):
apps cannot reach each other, they reach only their own database on the server, and they have a memory limit
(600 MB). nginx, cron jobs and the settings of the app stay the same.

The switch is per app ("network isolation" in the Django admin, off by default) and takes effect when the
container is created again by `manage.py restart` (the button "Neustart" only restarts the existing container).

### Set up the server once

Run as root in `/var/django/adminconsole`.

Let Postgres listen on the gateway address before Docker has created the network:
```
install -o root -g root -m 0644 setup/99-juntagrico-nonlocal-bind.conf /etc/sysctl.d/
sysctl --system
```

Postgres: listen on the gateway, and allow each app role only its own database from the app network:
```
sudo -u postgres psql -c "ALTER SYSTEM SET listen_addresses = 'localhost,172.30.0.1'"
echo "host sameuser all 172.30.0.0/22 scram-sha-256" >> "$(sudo -u postgres psql -Atc 'SHOW hba_file')"
systemctl restart postgresql
```

TODO
Firewall: from the app network only Postgres may be reached on the server:
```
install -o root -g root -m 0755 setup/juntagrico-apps-firewall /usr/local/sbin/juntagrico-apps-firewall
install -o root -g root -m 0644 setup/juntagrico-apps-firewall.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now juntagrico-apps-firewall
```

Check: Postgres listens on `172.30.0.1` and the rule is active:
```
ss -tlnp | grep 5432
iptables -S JUNTAGRICO-APPS
iptables -S INPUT | grep JUNTAGRICO-APPS
```
If you change the network in the settings (`APPS_NETWORK`), change Postgres and the firewall script accordingly.

### Switch an app

1. In the Django admin, open the app, check "network isolation" and save.
2. Create the container again, as `juntagrico`:
   ```
   cd /var/django/adminconsole
   export $(cat .venv/env.env | xargs)
   .venv/bin/python manage.py restart <app>
   ```
3. Check:
   ```
   docker inspect -f '{{.HostConfig.NetworkMode}} {{.HostConfig.Memory}}' <app>
   docker exec <app> python -m manage showmigrations juntagrico | tail -1
   docker exec <app> python -c "import socket; socket.create_connection(('172.30.0.1', 22), 3)"
   ```
   The first shows `juntagrico-apps 629145600`, the second a migration (the database is reachable), the third
   must fail with a timeout (sshd is not reachable). Then open the site, log in and check the logs of the app.

Undo: uncheck "network isolation", save, and run `manage.py restart <app>` again.

Start with the demo app, then a staging app, then the other apps one by one.


## Backups

Setup backup location

```
install -d -o postgres /var/django/backup
```

Test running a full backup

```
sudo -u postgres /var/django/adminconsole/tasks/backup/full.sh
```

The backup should be copied to a different location, e.g. using scp:

It's recommended to use a keyfile for login. Set up a key and move it to the backup server something like this.
```
sudo -u postgres ssh-keygen
sudo -u postgres ssh-copy-id <username>@<host>
```

Test the full backup and copy. Make sure /juntagrico/backup exists on the backup server.
```
sudo -u postgres ./full.sh | sudo -u postgres ./scp.sh <username>@<host>:/juntagrico/backup
```

Make it cronjob on the postgres user
```
sudo -u postgres crontab -e
```

add this to run the backup once per day at 0:10
```
10 0 * * * /var/django/adminconsole/tasks/backup/full.sh | /var/django/adminconsole/tasks/backup/scp.sh <username>@<host>:/juntagrico/backup
```

The following scripts are provided and can be adjusted to your needs:

- `full.sh` does a dumpall of the database
- `database.sh` dumps only the selected database
- `scp.sh` transfers the backup using scp
- `sftp.sh` transfers the backup using sftp
- `lftp.sh` alternative to sftp
- `webdav.sh` transfers the backup using webdav (e.g. to Nextcloud)


The transfer commands can be chained in case you want to copy the backup to multiple locations
```
./full.sh | ./scp.sh <username1>@<host1>:/juntagrico/backup | ./sftp.sh <username2>@<host2>:/juntagrico/backup <port>
```
