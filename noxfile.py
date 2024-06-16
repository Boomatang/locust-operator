import nox

@nox.session
def setup(session):
    session.run('kind', 'create', 'cluster', '--name', 'locust-dev', external=True)
    session.run('kubectl', 'apply', '-f', './manifests/locust.yaml', external=True)

@nox.session
def teardown(session):
    session.run('kind', 'delete', 'cluster', '--name', 'locust-dev', external=True)
