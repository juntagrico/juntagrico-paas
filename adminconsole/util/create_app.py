from adminconsole.models import App


def find_port():
    ports = App.objects.all().values_list('port', flat=True)
    port = 8010
    while port in ports:
        port += 1
    return port
