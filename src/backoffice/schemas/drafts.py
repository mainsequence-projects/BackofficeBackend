"""Partial extraction contracts derived from canonical field metadata, recursively."""

from copy import deepcopy
from functools import cache, reduce
from operator import or_
from types import UnionType
from typing import Annotated, Union, get_args, get_origin

from pydantic import BaseModel, create_model

from ..models.common import ContractModel
from .registry import get_document_model


def _partial_type(annotation):
    origin = get_origin(annotation)
    args = get_args(annotation)
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return partial_model(annotation)
    if origin is list:
        return list[_partial_type(args[0])]
    if origin is Annotated:
        return Annotated[_partial_type(args[0]), *args[1:]]
    if origin in (Union, UnionType):
        return reduce(or_, (_partial_type(arg) for arg in args))
    return annotation


@cache
def partial_model(model: type[BaseModel]) -> type[BaseModel]:
    """Keep field validation but defer complete-model validators until submission."""
    fields = {}
    for name, original in model.model_fields.items():
        field = deepcopy(original)
        annotation = _partial_type(original.annotation)
        if name != "document_type":
            annotation = annotation | None
            field.default = None
            field.default_factory = None
        fields[name] = (annotation, field)
    return create_model(f"{model.__name__}Draft", __base__=ContractModel, **fields)


def get_draft_model(document_type: str, schema_version: int = 1) -> type[BaseModel]:
    return partial_model(get_document_model(document_type, schema_version))


def complete_draft(document_type: str, payload: dict, schema_version: int = 1) -> BaseModel:
    """Promote only by revalidating the complete canonical contract."""
    return get_document_model(document_type, schema_version).model_validate(payload)
