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

    add_header Referrer-Policy $django_fallback_same_origin_referrer_policy always;
    include /etc/nginx/snippets/juntagrico-common.conf;
}