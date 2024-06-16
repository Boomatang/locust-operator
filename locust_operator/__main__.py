import kopf
import logging
import kubernetes
from .models import Spec
import os
import yaml


@kopf.on.create('locusts')
def create_fn(spec, name, namespace, **kwargs):

    data = Spec(**spec)

    controller_cmd = ["locust", "--master", "--locustfile", data.locustfile]
    if data.controller.ui is False:
        controller_cmd.append("--headless")

    worker_cmd = ["locust",
                  "--worker",
                  "--locustfile", data.locustfile,
                  "--master-host", f"{name}-controller.{namespace}.svc.cluster.local",
                  "--master-port", 80,
                  ]

    path = os.path.join(os.path.dirname(__file__), "templates", "deployment.yaml")
    tmpl = open(path, 'rt').read()
    controller = tmpl.format(
        name=f"{name}-controller",
        image=data.image,
        label=name,
        replicas=1,
        command=controller_cmd,
    )
    worker = tmpl.format(
        name=f"{name}-worker",
        image=data.image,
        label=name,
        replicas=data.worker.replicas,
        command=worker_cmd,
    )

    path = os.path.join(os.path.dirname(__file__), "templates", "service.yaml")
    tmpl = open(path, 'rt').read()
    controller_service = tmpl.format()  # TODO this is the next set up to do.

    api = kubernetes.client.AppsV1Api()
    core_api = kubernetes.client.CoreV1Api()

    data = yaml.safe_load(controller)
    obj = api.create_namespaced_deployment(namespace, data)
    logging.info(f"controller deployment created: {obj}")

    data = yaml.safe_load(controller_service)
    obj = core_api.create_namespaced_service(namespace, data)
    logging.info(f"controller service created: {obj}")

    data = yaml.safe_load(worker)
    obj = api.create_namespaced_deployment(namespace, data)
    logging.info(f"worker deployment created: {obj}")
