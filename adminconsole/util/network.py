import docker
from django.conf import settings
from docker.errors import NotFound

# Docker network for apps with network isolation (setting APPS_NETWORK overrides single values).
# The gateway is the server as seen from the apps: Postgres listens on it, and the firewall rule
# (setup/juntagrico-apps-firewall) refers to the bridge name. See README "App network isolation".
APPS_NETWORK = {
    'name': 'juntagrico-apps',
    'subnet': '172.30.0.0/22',
    'gateway': '172.30.0.1',
    'bridge': 'br-juntagrico',
}
# memory limit of an isolated app (setting APPS_MEMORY_LIMIT)
APPS_MEMORY_LIMIT = '600m'


class NetworkMismatch(Exception):
    pass


def apps_network():
    return {**APPS_NETWORK, **getattr(settings, 'APPS_NETWORK', {})}


def apps_memory_limit():
    return getattr(settings, 'APPS_MEMORY_LIMIT', APPS_MEMORY_LIMIT)


def ensure_apps_network(client):
    """
    Returns the network for isolated apps and creates it if it is missing.
    An existing network must have exactly the expected settings, as Postgres and the firewall rely on them.
    """
    config = apps_network()
    options = {
        'com.docker.network.bridge.enable_icc': 'false',  # no traffic between the apps
        'com.docker.network.bridge.name': config['bridge'],
    }
    try:
        network = client.networks.get(config['name'])
    except NotFound:
        ipam = docker.types.IPAMConfig(pool_configs=[
            docker.types.IPAMPool(subnet=config['subnet'], gateway=config['gateway'])
        ])
        return client.networks.create(config['name'], driver='bridge', ipam=ipam, options=options)

    ipam_configs = (network.attrs.get('IPAM') or {}).get('Config') or [{}]
    actual = {
        'driver': network.attrs.get('Driver'),
        'subnet': ipam_configs[0].get('Subnet'),
        'gateway': ipam_configs[0].get('Gateway'),
        'options': {key: (network.attrs.get('Options') or {}).get(key) for key in options},
    }
    expected = {'driver': 'bridge', 'subnet': config['subnet'], 'gateway': config['gateway'], 'options': options}
    if actual != expected:
        raise NetworkMismatch(f'Docker network {config["name"]} has {actual}, expected {expected}')
    return network
