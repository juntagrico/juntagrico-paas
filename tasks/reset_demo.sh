#!/bin/bash

cd /var/django/adminconsole
docker exec demo python -m manage flush --noinput
./tasks/redeploy-v2.sh demo
docker exec -e DJANGO_SUPERUSER_PASSWORD=admin demo python -m manage createadmin --noinput --email admin@admin.admin --username admin
docker exec demo python -m manage generate_testdata
docker exec demo python -m manage generate_billing_testdata
docker exec demo python -m manage generate_depot_list
docker exec demo python -m manage shell --command="site=Site.objects.first(); site.domain='demo.juntagrico.science'; site.name='Juntagrico Demo'; site.save()"