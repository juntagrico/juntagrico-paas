server {
    listen 80;
    server_name admin.juntagrico.app;

    location = /favicon.ico { access_log off; log_not_found off; }
    location /static/ {
        root /var/django/adminconsole;
    }

    location / {
        include proxy_params;
        proxy_pass http://unix:/run/adminconsole/gunicorn.sock;
    }

    set $can_use_sorp yes;
    include /etc/nginx/snippets/juntagrico-common.conf;
}