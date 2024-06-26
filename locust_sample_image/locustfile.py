from locust import HttpUser, task


class HelloWorld(HttpUser):
    @task
    def hello_world(self):
        self.client.get("/hello")
        self.client.get("/world")
