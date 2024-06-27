import asyncio
import pprint
from time import sleep

import kopf
import logging
import kubernetes
from locust_operator.models import Spec, OwnerReferences, OwnerReference
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
    tmpl = open(path, 'rt').read()
    controller_service = tmpl.format(
        name=f"{name}-controller-service",
        label=f"{name}-controller",
        controller="locust-operator",
    )

    api = kubernetes.client.AppsV1Api()
    core_api = kubernetes.client.CoreV1Api()

    data = yaml.safe_load(controller)
    data['spec']['template']['spec']['containers'][0]['command'] = controller_cmd
    kopf.adopt(data)
    obj = api.create_namespaced_deployment(namespace, data)
    logging.info(f"controller deployment created")

    data = yaml.safe_load(controller_service)
    kopf.adopt(data)
    obj = core_api.create_namespaced_service(namespace, data)
    logging.info(f"controller service created")

    data = yaml.safe_load(worker)
    data['spec']['template']['spec']['containers'][0]['command'] = worker_cmd
    kopf.adopt(data)
    obj = api.create_namespaced_deployment(namespace, data)
    logging.info(f"worker deployment created")


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
    tmpl = open(path, 'rt').read()
    controller_service = tmpl.format(
        name=f"{name}-controller-service",
        label=f"{name}-controller",
        controller="locust-operator",
    )

    api = kubernetes.client.AppsV1Api()
    core_api = kubernetes.client.CoreV1Api()

    data = yaml.safe_load(controller)
    data['spec']['template']['spec']['containers'][0]['command'] = controller_cmd
    kopf.adopt(data)
    obj = api.patch_namespaced_deployment(f"{name}-controller", namespace, data)
    logging.info(f"controller deployment patched")

    data = yaml.safe_load(controller_service)
    kopf.adopt(data)
    obj = core_api.patch_namespaced_service(f"{name}-controller-service", namespace, data)
    logging.info(f"controller service patched")

    data = yaml.safe_load(worker)
    data['spec']['template']['spec']['containers'][0]['command'] = worker_cmd
    kopf.adopt(data)
    obj = api.patch_namespaced_deployment(f"{name}-worker", namespace, data)
    logging.info(f"worker deployment patched")


@kopf.on.update('service',
                labels={'controller': 'locust-operator'},
                field='spec')
def revert_spec(old, name, namespace, **kwargs):

    core_api = kubernetes.client.CoreV1Api()
    obj = core_api.patch_namespaced_service(name, namespace, old)
    logging.info(f"service patched")


@kopf.on.field('service', param='service', field='metadata.labels.controller', old='locust-operator')
@kopf.on.field('deployment', param='deployment', field='metadata.labels.controller', old='locust-operator')
@kopf.on.field('deployment', param='deployment_app', field='metadata.labels.app')
def relabel(old, param, name, namespace, **kwargs):
    patch = {'metadata': {'labels': {'controller': 'locust-operator'}}}
    if param == 'deployment_app':
        if old is None:
            return
        patch['metadata']['labels']['app'] = old
        param = 'deployment'

    if patch and param == 'service':
        core_api = kubernetes.client.CoreV1Api()
        obj = core_api.patch_namespaced_service(name, namespace, patch)
        logging.info(f"service labels patched")

    if patch and param == 'deployment':
        api = kubernetes.client.AppsV1Api()
        obj = api.patch_namespaced_deployment(name, namespace, patch)
        logging.info(f"deployment labels patched")


@kopf.on.delete('service', labels={'controller': 'locust-operator'}, param='service')
@kopf.on.delete('deployment', labels={'controller': 'locust-operator'}, param='deployment')
def resource_delete(meta, name: str, namespace, param, **kwargs):
    owners = OwnerReferences(ownerReferences=meta['ownerReferences'])
    owner: OwnerReference = next(filter(lambda x: x.kind == "Locust", owners.ownerReferences))
    logging.info(f"resource_delete owner: {owner}")

    api = kubernetes.client.CustomObjectsApi()
    api_version = owner.apiVersion.split('/')
    resource = {}
    try:
        resource = api.get_namespaced_custom_object(api_version[0], api_version[1], namespace, f'{owner.kind}s'.lower(), owner.name)
    except kubernetes.client.exceptions.ApiException as e:
        if e.status == 404:
            return

    if param == 'service':
        core_api = kubernetes.client.CoreV1Api()
        patch = {'metadata': {'finalizers': None}}
        obj = core_api.patch_namespaced_service_with_http_info(name, namespace, patch)
        logging.info("service finalizers patched")
        path = os.path.join(os.path.dirname(__file__), "templates", "service.yaml")
        tmpl = open(path, 'rt').read()
        controller_service = tmpl.format(
            name=name,
            label=f"{resource['metadata']['name']}-controller",
            controller="locust-operator",
        )
        data = yaml.safe_load(controller_service)
        kopf.adopt(data, resource)
        obj = core_api.create_namespaced_service_with_http_info(namespace, data)
        logging.info(f"service created")

    if param == 'deployment':

        api = kubernetes.client.AppsV1Api()
        patch = {'metadata': {'finalizers': None}}
        obj = api.patch_namespaced_deployment(name, namespace, patch)
        spec_data = Spec(**resource['spec'])
        path = os.path.join(os.path.dirname(__file__), "templates", "deployment.yaml")
        tmpl = open(path, 'rt').read()

        if name.endswith('-controller'):
            controller_cmd = ["locust", "--master", "--locustfile", spec_data.locustfile]
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
            data['spec']['template']['spec']['containers'][0]['command'] = controller_cmd
            kopf.adopt(data, resource)
            obj = api.create_namespaced_deployment(namespace, data)
            logging.info(f"controller deployment recreated")
        elif name.endswith('-worker'):
            worker_cmd = ["locust",
                          "--worker",
                          "--locustfile", spec_data.locustfile,
                          "--master-host", f"{name}-controller-service.{namespace}.svc.cluster.local",
                          "--master-port", '5557',
                          ]

            worker = tmpl.format(
                name=f"{name}-worker",
                image=spec_data.image,
                label=f"{name}-worker",
                replicas=spec_data.worker.replicas,
                controller="locust-operator",
            )

            data = yaml.safe_load(worker)
            data['spec']['template']['spec']['containers'][0]['command'] = worker_cmd
            kopf.adopt(data, resource)
            obj = api.create_namespaced_deployment(namespace, data)
            logging.info(f"worker deployment recreated")
