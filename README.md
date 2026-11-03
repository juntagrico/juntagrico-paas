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


### Install from Source

create local user with required permissions
```
useradd -m -g www-data -s /bin/bash juntagrico
usermod -aG docker juntagrico
install -d -o juntagrico -g www-data /var/django/projects
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

Make the scripts executable

```
chmod +x tasks/*.sh
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

prepare the socket
```
mkdir -p /run/adminconsole
chown juntagrico:www-data /run/adminconsole
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

Set permissions
```
chown juntagrico /etc/nginx/sites-*
```

copy the config file and open it to change `server_name` to your domain.
```
cp setup/admin.juntagrico.app /etc/nginx/sites-available/admin.juntagrico.app
nano /etc/nginx/sites-available/admin.juntagrico.app
```

copy the global juntagrico config:
```
cp setup/nginx/juntagrico-global.conf /etc/nginx/snippets/
cp setup/nginx/juntagrico-security-maps.conf /etc/nginx/conf.d/
```

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

To release unused docker images add this cronjob
`5 1 * * * docker image prune -f`

### Enable staging auto-stop

Add this cronjob to stop expired staging app containers regularly
`0 2 * * * /var/django/adminconsole/tasks/stop_staging.sh`


## Create Demo App

The juntagrico demo app can be installed like any other app from https://github.com/juntagrico/juntagrico-demo

Make sure the instance is re-initialized at least every day using a cronjob:
`0 4 * * * /var/django/adminconsole/tasks/reset_demo.sh`


## Auto Upgrade Apps

If desired, add this to crontab for apps that should upgrade automatically
`0 2 * * * /var/django/adminconsole/tasks/redeploy-v2.sh <app-name>`


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


## Upgrading an existing installation

Some changes require one-time steps on existing servers. Run them right after deploying the new code.

### Certificates via wrapper script

The user `juntagrico` may only request certificates through a wrapper script, which accepts exactly one domain.
Run as root in `/var/django/adminconsole`:
```
install -o root -g root -m 0755 setup/juntagrico-certbot /usr/local/sbin/juntagrico-certbot
install -o root -g root -m 0440 setup/50-juntagrico-paas /etc/sudoers.d/50-juntagrico-paas
visudo -c
```

### GitHub tokens

GitHub tokens are no longer stored in the app repositories. Remove the ones stored by earlier versions:
```
su - juntagrico
cd /var/django/adminconsole
export $(cat .venv/env.env | xargs)
.venv/bin/python manage.py remove_git_credentials
```

Then revoke all tokens issued so far in the settings of the GitHub OAuth app ("Revoke all user tokens").
Users are asked to authorize the app again the next time they select a repository.


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

Make backup scripts executable

```
cd /var/django/adminconsole/tasks/backup
chmod +x *.sh
```

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
