import os

import kopf
import kubernetes
import yaml

from locust_operator.logs import get_logger
from locust_operator.models import Spec

log = get_logger()


def get(name, namespace, api: kubernetes.client.AppsV1Api = None):
    if api is None:
        api = kubernetes.client.AppsV1Api()
    try:
        resource = api.read_namespaced_deployment(f"{name}-worker", namespace)
        return resource
    except kubernetes.client.ApiException as e:
        if e.status == 404:
            return None
        log.error(e)


def create(
    name: str,
    namespace: str,
    spec: Spec,
    api: kubernetes.client.AppsV1Api = None,
    adopter=None,
):
    api, data = _setup(adopter, api, name, namespace, spec)
    api.create_namespaced_deployment(namespace, data)
    log.info("worker deployment created")


def patch(
    name: str,
    namespace: str,
    spec: Spec,
    api: kubernetes.client.AppsV1Api = None,
    adopter=None,
):
    api, data = _setup(adopter, api, name, namespace, spec)
    api.patch_namespaced_deployment(f"{name}-worker", namespace, data)
    log.info("worker deployment patched")


def _setup(adopter, api, name, namespace, spec):
    if api is None:
        api = kubernetes.client.AppsV1Api()
    command = [
        "locust",
        "--worker",
        "--locustfile",
        spec.locustfile,
        "--master-host",
        f"{name}-controller-service.{namespace}.svc.cluster.local",
        "--master-port",
        "5557",
    ]

    if spec.host is not None:
        command.extend(["--host", spec.host])

    path = os.path.join(os.path.dirname(__file__), "templates", "deployment.yaml")
    tmpl = open(path, "rt").read()
    worker = tmpl.format(
        name=f"{name}-worker",
        image=spec.image,
        label=f"{name}-worker",
        replicas=spec.worker.replicas,
        controller="locust-operator",
    )
    data = yaml.safe_load(worker)
    data["spec"]["template"]["spec"]["containers"][0]["command"] = command
    if adopter is not None:
        kopf.adopt(data, adopter)
    else:
        kopf.adopt(data)
    return api, data
