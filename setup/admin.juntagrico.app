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

    include /etc/nginx/snippets/juntagrico-*.conf;
}