import logging
import os
import sys

import kopf
import kubernetes
import requests
import yaml

from locust_operator.models import Spec

log = logging.getLogger("locust_operator")
logging.basicConfig(level=logging.DEBUG, handlers=[logging.StreamHandler(sys.stdout)])


@kopf.on.create("locusts")
def create_fn(spec, name, namespace, **kwargs):
    spec_data = Spec(**spec)

    controller_cmd = ["locust", "--master", "--locustfile", spec_data.locustfile]
    if spec_data.controller.ui is False:
        controller_cmd.append("--headless")

    worker_cmd = [
        "locust",
        "--worker",
        "--locustfile",
        spec_data.locustfile,
        "--master-host",
        f"{name}-controller-service.{namespace}.svc.cluster.local",
        "--master-port",
        "5557",
    ]

    path = os.path.join(os.path.dirname(__file__), "templates", "deployment.yaml")
    tmpl = open(path, "rt").read()
    controller = tmpl.format(
        name=f"{name}-controller",
        image=spec_data.image,
        label=f"{name}-controller",
        replicas=1,
        controller="locust-operator",
    )
    worker = tmpl.format(
        name=f"{name}-worker",
        image=spec_data.image,
        label=f"{name}-worker",
        replicas=spec_data.worker.replicas,
        controller="locust-operator",
    )

    path = os.path.join(os.path.dirname(__file__), "templates", "service.yaml")
    tmpl = open(path, "rt").read()
    controller_service = tmpl.format(
        name=f"{name}-controller-service",
        label=f"{name}-controller",
        controller="locust-operator",
    )

    api = kubernetes.client.AppsV1Api()
    core_api = kubernetes.client.CoreV1Api()

    data = yaml.safe_load(controller)
    data["spec"]["template"]["spec"]["containers"][0]["command"] = controller_cmd
    kopf.adopt(data)
    api.create_namespaced_deployment(namespace, data)
    log.info("controller deployment created")

    data = yaml.safe_load(controller_service)
    kopf.adopt(data)
    core_api.create_namespaced_service(namespace, data)
    log.info("controller service created")

    data = yaml.safe_load(worker)
    data["spec"]["template"]["spec"]["containers"][0]["command"] = worker_cmd
    kopf.adopt(data)
    api.create_namespaced_deployment(namespace, data)
    log.info("worker deployment created")


@kopf.on.resume("locust")
@kopf.on.update("locusts")
def patch_fn(spec, name, namespace, **kwargs):
    # TODO: this needs to be smarter about reconcile the resources if there is a currently running test.
    spec_data = Spec(**spec)
    log.debug("run local")
    controller_cmd = ["locust", "--master", "--locustfile", spec_data.locustfile]
    if spec_data.controller.ui is False:
        controller_cmd.append("--headless")

    worker_cmd = [
        "locust",
        "--worker",
        "--locustfile",
        spec_data.locustfile,
        "--master-host",
        f"{name}-controller-service.{namespace}.svc.cluster.local",
        "--master-port",
        "5557",
    ]

    path = os.path.join(os.path.dirname(__file__), "templates", "deployment.yaml")
    tmpl = open(path, "rt").read()
    controller = tmpl.format(
        name=f"{name}-controller",
        image=spec_data.image,
        label=f"{name}-controller",
        replicas=1,
        controller="locust-operator",
    )
    worker = tmpl.format(
        name=f"{name}-worker",
        image=spec_data.image,
        label=f"{name}-worker",
        replicas=spec_data.worker.replicas,
        controller="locust-operator",
    )

    path = os.path.join(os.path.dirname(__file__), "templates", "service.yaml")
    tmpl = open(path, "rt").read()
    controller_service = tmpl.format(
        name=f"{name}-controller-service",
        label=f"{name}-controller",
        controller="locust-operator",
    )

    api = kubernetes.client.AppsV1Api()
    core_api = kubernetes.client.CoreV1Api()

    data = yaml.safe_load(controller)
    data["spec"]["template"]["spec"]["containers"][0]["command"] = controller_cmd
    kopf.adopt(data)
    api.patch_namespaced_deployment(f"{name}-controller", namespace, data)
    log.info("controller deployment patched")

    data = yaml.safe_load(controller_service)
    kopf.adopt(data)
    core_api.patch_namespaced_service(f"{name}-controller-service", namespace, data)
    log.info("controller service patched")

    data = yaml.safe_load(worker)
    data["spec"]["template"]["spec"]["containers"][0]["command"] = worker_cmd
    kopf.adopt(data)
    api.patch_namespaced_deployment(f"{name}-worker", namespace, data)
    log.info("worker deployment patched")


@kopf.on.update("service", labels={"controller": "locust-operator"}, field="spec")
def revert_spec(old, name, namespace, **kwargs):
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
def relabel(old, param, name, namespace, **kwargs):
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
def resource_delete(meta, name: str, namespace, param, **kwargs):
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
        path = os.path.join(os.path.dirname(__file__), "templates", "service.yaml")
        tmpl = open(path, "rt").read()
        controller_service = tmpl.format(
            name=name,
            label=f"{resource['metadata']['name']}-controller",
            controller="locust-operator",
        )
        data = yaml.safe_load(controller_service)
        kopf.adopt(data, resource)
        core_api.create_namespaced_service_with_http_info(namespace, data)
        log.info("service created")

    if param == "deployment":
        api = kubernetes.client.AppsV1Api()
        patch = {"metadata": {"finalizers": None}}
        api.patch_namespaced_deployment(name, namespace, patch)
        spec_data = Spec(**resource["spec"])
        path = os.path.join(os.path.dirname(__file__), "templates", "deployment.yaml")
        tmpl = open(path, "rt").read()

        if name.endswith("-controller"):
            controller_cmd = [
                "locust",
                "--master",
                "--locustfile",
                spec_data.locustfile,
            ]
            if spec_data.controller.ui is False:
                controller_cmd.append("--headless")
            controller = tmpl.format(
                name=f"{name}-controller",
                image=spec_data.image,
                label=f"{name}-controller",
                replicas=1,
                controller="locust-operator",
            )
            data = yaml.safe_load(controller)
            data["spec"]["template"]["spec"]["containers"][0][
                "command"
            ] = controller_cmd
            kopf.adopt(data, resource)
            api.create_namespaced_deployment(namespace, data)
            log.info("controller deployment recreated")
        elif name.endswith("-worker"):
            worker_cmd = [
                "locust",
                "--worker",
                "--locustfile",
                spec_data.locustfile,
                "--master-host",
                f"{name}-controller-service.{namespace}.svc.cluster.local",
                "--master-port",
                "5557",
            ]

            worker = tmpl.format(
                name=f"{name}-worker",
                image=spec_data.image,
                label=f"{name}-worker",
                replicas=spec_data.worker.replicas,
                controller="locust-operator",
            )

            data = yaml.safe_load(worker)
            data["spec"]["template"]["spec"]["containers"][0]["command"] = worker_cmd
            kopf.adopt(data, resource)
            api.create_namespaced_deployment(namespace, data)
            log.info("worker deployment recreated")


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
    # TODO should check to see if there is a more rebust way of checking this state.
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
    service = f"{name}-controller-service.{namespace}.svc.cluster.local"
    url = f"http://{service}:8089/stats/requests"

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
