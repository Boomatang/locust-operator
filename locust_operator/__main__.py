import kopf
import logging
import kubernetes


@kopf.on.create('locusts')
def create_fn(spec, name, namespace, **kwargs):

    replicas = spec.get('replicas')
    if not replicas:
        raise kopf.PermanentError(f"Replicas must be set. Got {replicas!r}")
    body = kubernetes.client.V1Deployment()
    body.metadata = kubernetes.client.V1ObjectMeta(name=name)
    body.spec = kubernetes.client.V1DeploymentSpec(
        replicas=replicas,
        selector=kubernetes.client.V1LabelSelector(match_labels={'app': 'echostore'}),
        template=kubernetes.client.V1PodTemplateSpec(
            metadata=kubernetes.client.V1ObjectMeta(
                name=name,
                labels=kubernetes.client.V1ObjectMeta({'app/echostore'}),
            ),
            spec=kubernetes.client.V1PodSpec(
                containers=[
                    kubernetes.client.V1Container(
                        name=name,
                        image='quay.io/3scale/authorino:echo-api',

                    )
                ]
            )
        )
    )

    api = kubernetes.client.AppsV1Api()
    obj = api.create_namespaced_deployment(namespace, body)

    logging.info(f"deployment created: {obj}")
