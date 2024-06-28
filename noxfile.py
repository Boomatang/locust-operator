import os

import nox
from pathlib import Path


@nox.session
def setup(session):
    session.run('kind', 'create', 'cluster', '--name', 'locust-dev', '--config', 'kind-config.yaml', external=True)
    session.run('kubectl', 'apply', '-f', './manifests/locust.yaml', external=True)
    session.run('kubectl', 'apply', '-f', './samples/echoserver.yaml', external=True)


@nox.session
def deploy(session: nox.Session):
    session.run('podman', 'build', '.', '-t', 'localhost/locust-operator:latest', external=True)
    tar = Path('locust-operator.tar')
    if tar.exists():
        os.remove(tar)
    session.run('podman', 'save', '-o', 'locust-operator.tar', 'localhost/locust-operator:latest', external=True)
    session.run('kind', 'load', 'image-archive', 'locust-operator.tar', 'localhost/locust-operator:latest', '--name', 'locust-dev', external=True)
    session.run('kubectl', 'apply', '-f', './manifests/deployment.yaml', external=True)
    session.run('kubectl', 'apply', '-f', './manifests/rbac.yaml', external=True)


@nox.session
def teardown(session):
    session.run('kind', 'delete', 'cluster', '--name', 'locust-dev', external=True)
