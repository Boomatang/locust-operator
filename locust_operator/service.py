import os

import kopf
import kubernetes
import yaml

from locust_operator.logs import get_logger

log = get_logger()


def get(name, namespace, api: kubernetes.client.CoreV1Api = None):
    if api is None:
        api = kubernetes.client.CoreV1Api()
    try:
        resource = api.read_namespaced_service(f"{name}-controller-service", namespace)
        return resource
    except kubernetes.client.ApiException as e:
        if e.status == 404:
            return None
        log.error(e)


def create(
    name: str, namespace: str, api: kubernetes.client.CoreV1Api = None, adopter=None
):
    api, data = _setup(adopter, api, name)
    api.create_namespaced_service(namespace, data)
    log.info("controller service created")


def patch(
    name: str, namespace: str, api: kubernetes.client.CoreV1Api = None, adopter=None
):
    api, data = _setup(adopter, api, name)
    api.patch_namespaced_service(f"{name}-controller-service", namespace, data)
    log.info("controller service patched")


def _setup(adopter, api, name):
    if api is None:
        api = kubernetes.client.CoreV1Api()
    path = os.path.join(os.path.dirname(__file__), "templates", "service.yaml")
    tmpl = open(path, "rt").read()
    controller_service = tmpl.format(
        name=f"{name}-controller-service",
        label=f"{name}-controller",
        controller="locust-operator",
    )
    data = yaml.safe_load(controller_service)
    if adopter is None:
        kopf.adopt(data)
    else:
        kopf.adopt(data, adopter)
    return api, data
