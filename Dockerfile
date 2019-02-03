#This docker file can be used to test the application
#It also serves as instalation guide in order to setup a paas on an ubuntu server
FROM ubuntu:18.04
ENV JS_DATABASE_NAME=adminconsole
ENV JS_DATABASE_USER=adminconsole
ENV JS_DATABASE_PASSWORD=password
ENV JS_DATABASE_HOST=localhost
ENV JS_KEY=jssecret
#docker specifiv envs
ENV DEBIAN_FRONTEND=noninteractive
ENV DJANGO_SETTINGS_MODULE=adminconsole.local_settings
USER root
RUN apt-get update -y &&\
#    apt-get upgrade -y &&\ #not used in docker but you should do it during an installation on an normal ubuntu system
    apt-get install -y apt-utils python3-pip python3-dev libpq-dev postgresql postgresql-contrib nginx git wget curl systemd
RUN apt-get update -qq && apt-get install -qqy \
    apt-transport-https \
    ca-certificates \
    curl \
    lxc \
    iptables
# Install Docker from Docker Inc. repositories.
RUN curl -sSL https://get.docker.com/ | sh

RUN pip3 install --upgrade pip
RUN pip3 install virtualenv
WORKDIR /root/
RUN wget https://dl.eff.org/certbot-auto &&\
    chmod a+x ./certbot-auto
WORKDIR /tmp/
USER postgres
RUN /etc/init.d/postgresql start &&\
    psql --command "CREATE DATABASE adminconsole;"&&\
    psql --command "CREATE USER adminconsole WITH PASSWORD 'password';"&&\
    psql --command "ALTER ROLE adminconsole SET client_encoding TO 'utf8';"&&\
    psql --command "ALTER ROLE adminconsole SET default_transaction_isolation TO 'read committed';"&&\
    psql --command "ALTER ROLE adminconsole SET timezone TO 'CET';"&&\
    psql --command "GRANT ALL PRIVILEGES ON DATABASE adminconsole TO adminconsole;"&&\
    psql --command "alter user adminconsole createdb;"&&\
    psql --command "alter user adminconsole createrole;"
USER root
WORKDIR /var/
RUN mkdir django
WORKDIR django
RUN mkdir adminconsole
RUN mkdir projects
WORKDIR adminconsole
ADD . .
# on a normal ubuntu just source the virtual environment and dont do it that complicated, it is a docker thing again
RUN virtualenv venv &&\
    pwd &&\
    venv/bin/pip install --upgrade -r requirements.txt
RUN /etc/init.d/postgresql start &&\
    venv/bin/python -m manage migrate&&\
    venv/bin/python -m manage shell -c 'from django.contrib.auth.models import User; User.objects.create_superuser("admin", "admin@admin.com", "admin")'
COPY docker_resources/env.env /var/django/adminconsole/venv/
COPY docker_resources/gunicorn.service /etc/systemd/system/
#does not work inside docker
#RUN systemctl start gunicorn &&\
#    systemctl enable gunicorn
COPY docker_resources/default /etc/nginx/sites-available/default
RUN rm -rf /etc/nginx/sites-enabled/default && ln -s /etc/nginx/sites-available/default /etc/nginx/sites-enabled/default
EXPOSE 80
CMD /etc/init.d/postgresql start &&\
 #that would be the production command
 #systemctl restart gunicorn &&
 #systemctl restart nginx
 #that just how it is done in docker &&\
 /etc/init.d/nginx start &&\
 venv/bin/python -m manage migrate &&\
 venv/bin/python -m manage collectstatic -c &&\
 /var/django/adminconsole/venv/bin/gunicorn --access-logfile - --workers 1 --bind unix:/var/django/adminconsole/adminconsole.sock adminconsole.wsgi:application
