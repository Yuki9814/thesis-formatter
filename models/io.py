from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Type, TypeVar

from pydantic import BaseModel

ModelT = TypeVar("ModelT", bound=BaseModel)


def model_to_dict(model: BaseModel) -> dict:
    if hasattr(model, "model_dump"):
        return model.model_dump()
    return model.dict()


def model_to_json(model: BaseModel) -> str:
    return json.dumps(model_to_dict(model), ensure_ascii=False, indent=2, sort_keys=True)


def write_model(path: str | Path, model: BaseModel) -> None:
    Path(path).write_text(model_to_json(model), encoding="utf-8")


def load_model(path: str | Path, model_type: Type[ModelT]) -> ModelT:
    data: Any = json.loads(Path(path).read_text(encoding="utf-8"))
    if hasattr(model_type, "model_validate"):
        return model_type.model_validate(data)
    return model_type.parse_obj(data)

