from pydantic import BaseModel, Field
from typing import Optional


class Metadata(BaseModel):
    name: str
    namespace: Optional[str]


class Crd(BaseModel):
    metadata: Metadata
    apiVersion: str
    kind: str


class AutoStart(BaseModel):
    start: bool
    wait_for_workers: bool


class Controller(BaseModel):
    ui: bool
    autostart: Optional[AutoStart]


class Worker(BaseModel):
    replicas: int = Field(ge=1)


class Spec(BaseModel):
    image: str
    locustfile: str
    controller: Controller
    worker: Worker


class LocustCrd(Crd):
    spec: Spec


class OwnerReference(BaseModel):
    apiVersion: str
    kind: str
    name: str


class OwnerReferences(BaseModel):
    ownerReferences: list[OwnerReference]