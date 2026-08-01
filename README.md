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
cp setup/juntagrico-global.conf /etc/nginx/snippets/
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


## Backups

Make backup scripts executable

```
cd var/django/adminconsole/tasks/backup
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
./full.sh | ./scp.sh <username1>@<host1>:/juntagrico/backup | ./sftp <username2>@<host2>:/juntagrico/backup <port>
```
