# Locust Operator

## Setup Example
Setting up a kind cluster and adding the resources required to run the example local.
```shell
nox -s setup demo_locust deploy
```
This will set up the operator, echo server and add an image with the sample locust files

Next would be to apply the locust CR which will trigger the locust tests.
```shell
kubectl apply -f samples/basic.yaml
```

Get access to the locust UI on port 8090:
```shell
kubectl port-forward svc/testing-locust-controller-service 8090:8089 -n default
```

To remove the kind cluster.
```shell
nox -s teardown
```