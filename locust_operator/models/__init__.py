from typing import Optional

from pydantic import BaseModel, Field


class Metadata(BaseModel):
    name: str
    namespace: Optional[str] = None


class Crd(BaseModel):
    metadata: Metadata
    apiVersion: str
    kind: str


class AutoStart(BaseModel):
    start: bool
    wait_for_workers: bool


class Controller(BaseModel):
    ui: bool
    autostart: Optional[AutoStart] = None


class Worker(BaseModel):
    replicas: int = Field(ge=1)


class Spec(BaseModel):
    image: str
    locustfile: str
    controller: Controller
    worker: Worker


class LocustCrd(Crd):
    spec: Spec
