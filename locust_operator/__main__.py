import pprint

import kopf
import logging
import kubernetes
from locust_operator.models import Spec
import os
import yaml


@kopf.on.create('locusts')
def create_fn(spec, name, namespace, **kwargs):

    spec_data = Spec(**spec)

    controller_cmd = ["locust", "--master", "--locustfile", spec_data.locustfile]
    if spec_data.controller.ui is False:
        controller_cmd.append("--headless")

    worker_cmd = ["locust",
                  "--worker",
                  "--locustfile", spec_data.locustfile,
                  "--master-host", f"{name}-controller-service.{namespace}.svc.cluster.local",
                  "--master-port", '5557',
                  ]

    path = os.path.join(os.path.dirname(__file__), "templates", "deployment.yaml")
    tmpl = open(path, 'rt').read()
    controller = tmpl.format(
        name=f"{name}-controller",
        image=spec_data.image,
        label=f"{name}-controller",
        replicas=1,
    )
    worker = tmpl.format(
        name=f"{name}-worker",
        image=spec_data.image,
        label=f"{name}-worker",
        replicas=spec_data.worker.replicas,
    )

    path = os.path.join(os.path.dirname(__file__), "templates", "service.yaml")
    tmpl = open(path, 'rt').read()
    controller_service = tmpl.format(
        name=f"{name}-controller-service",
        label=f"{name}-controller",
    )

    api = kubernetes.client.AppsV1Api()
    core_api = kubernetes.client.CoreV1Api()

    data = yaml.safe_load(controller)
    data['spec']['template']['spec']['containers'][0]['command'] = controller_cmd
    kopf.adopt(data)
    obj = api.create_namespaced_deployment(namespace, data)
    logging.info(f"controller deployment created: {obj}")

    data = yaml.safe_load(controller_service)
    kopf.adopt(data)
    obj = core_api.create_namespaced_service(namespace, data)
    logging.info(f"controller service created: {obj}")

    data = yaml.safe_load(worker)
    data['spec']['template']['spec']['containers'][0]['command'] = worker_cmd
    pprint.pprint(data)
    kopf.adopt(data)
    obj = api.create_namespaced_deployment(namespace, data)
    logging.info(f"worker deployment created: {obj}")


@kopf.on.resume('locust')
@kopf.on.update('locusts')
def patch_fn(spec, name, namespace, **kwargs):
    # TODO: this needs to be smarter about reconcile the resources if there is a currently running test.
    spec_data = Spec(**spec)

    controller_cmd = ["locust", "--master", "--locustfile", spec_data.locustfile]
    if spec_data.controller.ui is False:
        controller_cmd.append("--headless")

    worker_cmd = ["locust",
                  "--worker",
                  "--locustfile", spec_data.locustfile,
                  "--master-host", f"{name}-controller-service.{namespace}.svc.cluster.local",
                  "--master-port", '5557',
                  ]

    path = os.path.join(os.path.dirname(__file__), "templates", "deployment.yaml")
    tmpl = open(path, 'rt').read()
    controller = tmpl.format(
        name=f"{name}-controller",
        image=spec_data.image,
        label=f"{name}-controller",
        replicas=1,
    )
    worker = tmpl.format(
        name=f"{name}-worker",
        image=spec_data.image,
        label=f"{name}-worker",
        replicas=spec_data.worker.replicas,
    )

    path = os.path.join(os.path.dirname(__file__), "templates", "service.yaml")
    tmpl = open(path, 'rt').read()
    controller_service = tmpl.format(
        name=f"{name}-controller-service",
        label=f"{name}-controller",
    )

    api = kubernetes.client.AppsV1Api()
    core_api = kubernetes.client.CoreV1Api()

    data = yaml.safe_load(controller)
    data['spec']['template']['spec']['containers'][0]['command'] = controller_cmd
    kopf.adopt(data)
    obj = api.patch_namespaced_deployment(f"{name}-controller", namespace, data)
    logging.info(f"controller deployment patched: {obj}")

    data = yaml.safe_load(controller_service)
    kopf.adopt(data)
    obj = core_api.patch_namespaced_service(f"{name}-controller-service", namespace, data)
    logging.info(f"controller service patched: {obj}")

    data = yaml.safe_load(worker)
    data['spec']['template']['spec']['containers'][0]['command'] = worker_cmd
    kopf.adopt(data)
    obj = api.patch_namespaced_deployment(f"{name}-worker", namespace, data)
    logging.info(f"worker deployment patched: {obj}")


@kopf.on.update('service',
                labels={'controller': 'locust-operator'},
                field='spec')
def revert_spec(old, name, namespace, **kwargs):

    core_api = kubernetes.client.CoreV1Api()
    obj = core_api.patch_namespaced_service(name, namespace, old)
    logging.info(f"service patched: {obj}")


@kopf.on.field('service', param='service', field='metadata.labels')
@kopf.on.field('deployment', param='deployment', field='metadata.labels')
def relabel(diff, param, name, namespace, **kwargs):
    patch = None
    for entry in diff:
        if len(entry[1]) == 0 or entry[1][0] == 'controller':
            patch = {'metadata': {'labels': {'controller': 'locust-operator'}}}

    if patch and param == 'service':
        core_api = kubernetes.client.CoreV1Api()
        obj = core_api.patch_namespaced_service(name, namespace, patch)
        logging.info(f"service labels patched: {obj}")

    if patch and param == 'deployment':
        api = kubernetes.client.AppsV1Api()
        obj = api.patch_namespaced_deployment(name, namespace, patch)
        logging.info(f"deployment labels patched: {obj}")
