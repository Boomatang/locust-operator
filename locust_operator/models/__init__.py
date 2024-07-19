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
    headless: Optional[bool] = False
    start: bool
    wait_for_workers: bool


class Spec(BaseModel):
    image: str
    locustfile: str
    host: Optional[str]
    replicas: int = Field(ge=1)
    autostart: Optional[AutoStart] = None


class LocustCrd(Crd):
    spec: Spec
