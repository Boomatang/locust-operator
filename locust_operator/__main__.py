import os

import kopf
import kubernetes
import requests

from locust_operator import controller, service, worker
from locust_operator.logs import get_logger
from locust_operator.models import Spec

log = get_logger()


@kopf.on.create("locusts")
def create_fn(spec, name, namespace, **_):
    spec_data = Spec(**spec)

    api = kubernetes.client.AppsV1Api()
    controller.create(name, namespace, spec_data, api)
    worker.create(name, namespace, spec_data, api)
    service.create(name, namespace)


@kopf.on.resume("locust")
@kopf.on.update("locusts")
def patch_fn(spec, name, namespace, **_):
    spec_data = Spec(**spec)

    api = kubernetes.client.AppsV1Api()
    controller_cr = controller.get(name, namespace, api)
    if controller_cr is None:
        controller.create(name, namespace, spec_data, api)
    else:
        controller.patch(name, namespace, spec_data, api)

    worker_cr = worker.get(name, namespace, api)
    if worker_cr is None:
        worker.create(name, namespace, spec_data, api)
    else:
        worker.patch(name, namespace, spec_data, api)

    core_api = kubernetes.client.CoreV1Api()
    service_cr = service.get(name, namespace, core_api)
    if service_cr is None:
        service.create(name, namespace, core_api)
    else:
        service.patch(name, namespace, core_api)


@kopf.on.update("service", labels={"controller": "locust-operator"}, field="spec")
def revert_spec(old, name, namespace, **_):
    core_api = kubernetes.client.CoreV1Api()
    core_api.patch_namespaced_service(name, namespace, old)
    log.info("service patched")


@kopf.on.field(
    "service",
    param="service",
    field="metadata.labels.controller",
    old="locust-operator",
)
@kopf.on.field(
    "deployment",
    param="deployment",
    field="metadata.labels.controller",
    old="locust-operator",
)
@kopf.on.field("deployment", param="deployment_app", field="metadata.labels.app")
def relabel(old, param, name, namespace, **_):
    patch = {"metadata": {"labels": {"controller": "locust-operator"}}}
    if param == "deployment_app":
        if old is None:
            return
        patch["metadata"]["labels"]["app"] = old
        param = "deployment"

    if patch and param == "service":
        core_api = kubernetes.client.CoreV1Api()
        core_api.patch_namespaced_service(name, namespace, patch)
        log.info("service labels patched")

    if patch and param == "deployment":
        api = kubernetes.client.AppsV1Api()
        api.patch_namespaced_deployment(name, namespace, patch)
        log.info("deployment labels patched")


@kopf.on.delete("service", labels={"controller": "locust-operator"}, param="service")
@kopf.on.delete(
    "deployment", labels={"controller": "locust-operator"}, param="deployment"
)
def resource_delete(meta, name: str, namespace, param, **_):
    owner = next(
        filter(lambda x: x.get("kind") == "Locust", meta["ownerReferences"]), {}
    )
    log.info(f"resource_delete owner: {owner.get('name')}")

    api = kubernetes.client.CustomObjectsApi()
    api_version = owner.get("apiVersion").split("/")
    resource = {}
    try:
        resource = api.get_namespaced_custom_object(
            api_version[0], api_version[1], namespace, "locusts", owner.get("name")
        )
    except kubernetes.client.exceptions.ApiException as e:
        if e.status == 404:
            return

    if param == "service":
        core_api = kubernetes.client.CoreV1Api()
        patch = {"metadata": {"finalizers": None}}
        core_api.patch_namespaced_service_with_http_info(name, namespace, patch)
        log.info("service finalizers patched")
        log.info("recreating controller service")
        service.create(owner.get("name"), namespace, adopter=resource)

    if param == "deployment":
        spec_data = Spec(**resource["spec"])
        api = kubernetes.client.AppsV1Api()
        patch = {"metadata": {"finalizers": None}}
        api.patch_namespaced_deployment(name, namespace, patch)
        if name.endswith("-controller"):
            log.info("recreating controller deployment")
            controller.create(
                owner.get("name"), namespace, spec_data, api, adopter=resource
            )
        elif name.endswith("-worker"):
            worker.create(
                owner.get("name"), namespace, spec_data, api, adopter=resource
            )
            log.info("recreating worker deployment")


@kopf.on.update(
    "deployment", labels={"controller": "locust-operator"}, field="status.conditions"
)
@kopf.on.create(
    "deployment", labels={"controller": "locust-operator"}, field="status.conditions"
)
@kopf.on.resume(
    "deployment", labels={"controller": "locust-operator"}, field="status.conditions"
)
def deployment_update(status, meta, name, namespace, **_):
    owner = next(
        filter(lambda x: x.get("kind") == "Locust", meta["ownerReferences"]), {}
    )
    log.debug(f"owner: {owner.get('name')}")

    available = next(
        filter(lambda e: e.get("type") == "Available", status["conditions"]), None
    )
    patch = {"status": {name: available}}

    api = kubernetes.client.CustomObjectsApi()
    api_version = owner.get("apiVersion").split("/")
    api.patch_namespaced_custom_object(
        api_version[0],
        api_version[1],
        namespace,
        "locusts",
        owner.get("name"),
        patch,
    )


def is_running_in_cluster():
    """
    Checks to see if the controller is in cluster.
    Useful for features that require on cluster resources such as service routes.
    """
    # TODO should check to see if there is a more robust way of checking this state.
    if os.getenv("KUBERNETES_SERVICE_HOST"):
        return True
    return False


def slower_if_local(interval):
    """
    increase the interval if the operator is running locally.
    x10 increase
    """
    if is_running_in_cluster():
        return interval
    return interval * 10


@kopf.timer("locust", interval=slower_if_local(10), initial_delay=5)
def locust_deployment(name, namespace, **_):
    log.debug(f"ping_test_runner: {name}")
    if not is_running_in_cluster():
        log.debug("running controller locally, exit early.")
        return
    service_url = f"{name}-controller-service.{namespace}.svc.cluster.local"
    url = f"http://{service_url}:8089/stats/requests"

    response = requests.get(url, timeout=10)
    if response.status_code == 200:
        data = response.json()
        response = {
            "state": data["state"],
            "fail_ratio": data["fail_ratio"],
            "total_rps": data["total_rps"],
            "workers": data["workers"],
        }

        aggregated = next(filter(lambda e: e["name"] == "Aggregated", data["stats"]))
        if response["state"] == "running":
            response["current_rps"] = aggregated["current_rps"]

        return response


def run():
    kopf.run(clusterwide=True)


if __name__ == "__main__":
    run()
