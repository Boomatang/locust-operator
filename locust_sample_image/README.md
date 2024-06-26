```shell

podman build . -t locust-demo:latest
podman save -o locust-demo.tar locust-demo:latest
kind load image-archive locust-demo.tar localhost/locust-demo:latest --name locust-dev
``` 
