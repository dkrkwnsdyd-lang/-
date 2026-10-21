"""Lightweight ad concept planning API. No paid model or rendering side effects."""
from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from ..studio.sales_story import build_sales_story


class SalesStoryRequest(BaseModel):
    product: dict[str, Any] = Field(default_factory=dict)


def register_sales_story(app: FastAPI) -> None:
    @app.post("/api/v2/ads/plan")
    def ad_plan(req: SalesStoryRequest):
        try:
            return build_sales_story(req.product)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
