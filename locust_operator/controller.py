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
        resource = api.read_namespaced_deployment(f"{name}-controller", namespace)
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
    api, data = _setup(adopter, api, name, spec)
    api.create_namespaced_deployment(namespace, data)
    log.info("controller deployment created")


def patch(
    name: str,
    namespace: str,
    spec: Spec,
    api: kubernetes.client.AppsV1Api = None,
    adopter=None,
):
    api, data = _setup(adopter, api, name, spec)
    api.patch_namespaced_deployment(f"{name}-controller", namespace, data)
    log.info("controller deployment patched")


def _setup(adopter, api, name, spec):
    if api is None:
        api = kubernetes.client.AppsV1Api()
    command = ["locust", "--master", "--locustfile", spec.locustfile]
    if spec.host is not None:
        command.extend(["--host", spec.host])

    if spec.autostart is not None:
        if spec.autostart.headless:
            command.append("--headless")
        if spec.autostart.start:
            command.append("--autostart")

        if spec.autostart.wait_for_workers:
            command.extend(["--expect-workers", str(spec.worker.replicas)])

    path = os.path.join(os.path.dirname(__file__), "templates", "deployment.yaml")
    tmpl = open(path, "rt").read()
    controller = tmpl.format(
        name=f"{name}-controller",
        image=spec.image,
        label=f"{name}-controller",
        replicas=1,
        controller="locust-operator",
    )
    data = yaml.safe_load(controller)
    data["spec"]["template"]["spec"]["containers"][0]["command"] = command
    if adopter is None:
        kopf.adopt(data)
    else:
        kopf.adopt(data, adopter)
    return api, data
