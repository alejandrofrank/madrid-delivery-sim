"""Explicit, keyless Google Vertex adapter; offline remains the default."""

import os

from google.adk.models.base_llm import BaseLlm
from google.adk.models.google_llm import Gemini
from google.genai import types

from delivery.adk_contracts import RestaurantBrain, VertexProfile
from delivery.adk_offline import OfflineRestaurantModel


def approved_vertex_profile(brain: RestaurantBrain) -> VertexProfile:
    if os.environ.get("DELIVERY_ADK_VERTEX_ENABLED") != "1":
        raise PermissionError("Vertex restaurant inference is disabled by deployment policy")
    if os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY"):
        raise PermissionError("Vertex restaurant inference requires keyless ADC")
    profile = VertexProfile.model_validate_json(os.environ.get("DELIVERY_ADK_VERTEX_PROFILE", "{}"))
    if brain.provider != "vertex" or brain.vertex != profile or brain.usd_limit <= 0:
        raise PermissionError("Restaurant model profile differs from approved deployment policy")
    return profile


def create_restaurant_model(brain: RestaurantBrain) -> BaseLlm:
    if brain.provider == "offline":
        return OfflineRestaurantModel()
    profile = approved_vertex_profile(brain)
    return Gemini(
        model=profile.model,
        api_version="v1",
        client_kwargs={"vertexai": True, "project": profile.project, "location": profile.location},
        retry_options=types.HttpRetryOptions(attempts=1),
    )


def validate_model(brain: RestaurantBrain, model: BaseLlm) -> None:
    if brain.provider == "offline":
        if not isinstance(model, OfflineRestaurantModel):
            raise PermissionError("Only approved offline model adapters are admitted")
        return
    profile = approved_vertex_profile(brain)
    if (
        type(model) is not Gemini
        or model.model != profile.model
        or model.client_kwargs
        != {
            "vertexai": True,
            "project": profile.project,
            "location": profile.location,
        }
        or model.base_url is not None
        or model.client is not None
        or model.use_interactions_api
        or model.api_version != "v1"
    ):
        raise PermissionError("Vertex adapter must use the approved keyless deployment profile")
    if model.retry_options is None or model.retry_options.attempts != 1:
        raise PermissionError("Automatic provider retries are disabled")
