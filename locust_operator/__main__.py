import kopf
import kubernetes
import requests

from locust_operator import controller, service, worker
from locust_operator.helpers import is_running_in_cluster, slower_if_local
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
def locust_resume_fn(spec, name, namespace, **_):
    spec_data = Spec(**spec)

    api = kubernetes.client.AppsV1Api()
    controller_cr = controller.get(name, namespace, api)
    if controller_cr is None:
        controller.create(name, namespace, spec_data, api)

    worker_cr = worker.get(name, namespace, api)
    if worker_cr is None:
        worker.create(name, namespace, spec_data, api)

    core_api = kubernetes.client.CoreV1Api()
    service_cr = service.get(name, namespace, core_api)
    if service_cr is None:
        service.create(name, namespace, core_api)


@kopf.on.update("locusts")
def patch_fn(spec, name, namespace, **_):
    # TODO this should be smart and work of the diff
    spec_data = Spec(**spec)

    api = kubernetes.client.AppsV1Api()
    controller.patch(name, namespace, spec_data, api)
    worker.patch(name, namespace, spec_data, api)
    service.patch(name, namespace)


@kopf.on.update("service", labels={"controller": "locust-operator"}, field="spec")
def revert_spec(name, namespace, **_):
    log.warn(f"{name}/{namespace}: service spec updated")
    log.info("We trust the updater to know what they are doing.")


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
    locust_cr = {}
    try:
        locust_cr = api.get_namespaced_custom_object(
            api_version[0], api_version[1], namespace, "locusts", owner.get("name")
        )
    except kubernetes.client.exceptions.ApiException as e:
        if e.status in (404, 403):
            log.info("resource_delete owner not found")
            return
        else:
            log.error(e)

    if param == "service":
        core_api = kubernetes.client.CoreV1Api()
        patch = {"metadata": {"finalizers": None}}
        core_api.patch_namespaced_service_with_http_info(name, namespace, patch)
        log.info("service finalizers patched")
        log.info("recreating controller service")
        service.create(owner.get("name"), namespace, api=core_api, adopter=locust_cr)

    if param == "deployment":
        _spec = Spec(**locust_cr["spec"])
        api = kubernetes.client.AppsV1Api()
        patch = {"metadata": {"finalizers": None}}
        api.patch_namespaced_deployment(name, namespace, patch)
        if name.endswith("-controller"):
            log.info("recreating controller deployment")
            controller.create(
                owner.get("name"), namespace, _spec, api=api, adopter=locust_cr
            )
        elif name.endswith("-worker"):
            worker.create(
                owner.get("name"), namespace, _spec, api=api, adopter=locust_cr
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


@kopf.timer("locust", interval=slower_if_local(10), initial_delay=5)
def locust_deployment(name, namespace, **_):
    log.debug(f"ping_test_runner: {name}")
    service_url = f"{name}-controller-service.{namespace}.svc.cluster.local"
    url = f"http://{service_url}:8089/stats/requests"
    if not is_running_in_cluster():
        log.debug("running controller locally, refresh is delayed")
        url = "http://localhost:8090/stats/requests"

    try:
        response = requests.get(url, timeout=10)
    except requests.exceptions.ConnectionError as e:
        if not is_running_in_cluster():
            log.error(
                f"running controller locally, no locust instances found. check {url} is accessible"
            )
        log.error(e)
        return False

    if response.status_code == 200:
        data = response.json()
        status = {
            "state": data["state"],
            "fail_ratio": data["fail_ratio"],
            "total_rps": data["total_rps"],
            "workers": data["workers"],
        }

        aggregated = next(filter(lambda i: i["name"] == "Aggregated", data["stats"]))
        if status["state"] == "running":
            status["current_rps"] = aggregated["current_rps"]

        return status
    else:
        log.error(f"failed to get stats for {name}")
        log.error(f"response: {response}")


@kopf.on.update("deployment", labels={"controller": "locust-operator"}, field="spec")
def deployment_spec(name, namespace, **_):
    log.warn(f"{name}/{namespace}: deployment spec updated")
    log.info("We trust the updater to know what they are doing.")


def run():
    kopf.run(clusterwide=True)


if __name__ == "__main__":
    run()
