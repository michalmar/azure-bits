from __future__ import annotations

from dataclasses import dataclass
import os


DEFAULT_SUBSCRIPTION_ID = "00000000-0000-0000-0000-000000000000"
DEFAULT_RESOURCE_GROUP = "example-resource-group"
DEFAULT_ACCOUNT_NAME = "example-foundry-account"
DEFAULT_LOCATION = "swedencentral"
DEFAULT_PROJECT_URL = "https://example.invalid/api/projects/example-project"
DEFAULT_BASE_URL = "https://example.invalid"

ALLOWED_MODELS = (
    "gpt-image-2.5-sunburst",
    "MAI-Image-2.6-Flash",
    "MAI-Image-2.6",
    "MAI-Image-2.5",
    "gpt-image-2",
)

MODEL_PROVIDER = {
    "gpt-image-2.5-sunburst": "openai",
    "gpt-image-2": "openai",
    "MAI-Image-2.6-Flash": "mai",
    "MAI-Image-2.6": "mai",
    "MAI-Image-2.5": "mai",
}

MODEL_DEPLOYMENT = {
    "gpt-image-2.5-sunburst": "gpt-image-2.5-sunburst",
    "gpt-image-2": "gpt-image-2",
}

CAPABILITY_CACHE_SECONDS = int(os.getenv("FOUNDRY_CAPABILITY_CACHE_SECONDS", "30"))
UPSTREAM_TIMEOUT_SECONDS = float(os.getenv("FOUNDRY_UPSTREAM_TIMEOUT_SECONDS", "300"))
MAX_PROMPT_LENGTH = int(os.getenv("FOUNDRY_MAX_PROMPT_LENGTH", "4000"))
MAX_IMAGE_BYTES = int(os.getenv("FOUNDRY_MAX_IMAGE_BYTES", "900000"))
MAX_MULTIPART_BYTES = MAX_IMAGE_BYTES + MAX_PROMPT_LENGTH + 65536

MGMT_API_VERSION = "2025-06-01"
OPENAI_API_VERSION = "2025-04-01-preview"
DATA_SCOPE = "https://cognitiveservices.azure.com/.default"
MANAGEMENT_SCOPE = "https://management.azure.com/.default"


@dataclass(frozen=True, slots=True)
class FoundryDefaults:
    subscription_id: str = DEFAULT_SUBSCRIPTION_ID
    resource_group: str = DEFAULT_RESOURCE_GROUP
    account_name: str = DEFAULT_ACCOUNT_NAME
    location: str = DEFAULT_LOCATION
    project_url: str = DEFAULT_PROJECT_URL
    base_url: str = DEFAULT_BASE_URL


def get_defaults() -> FoundryDefaults:
    return FoundryDefaults(
        subscription_id=os.getenv("FOUNDRY_SUBSCRIPTION_ID", DEFAULT_SUBSCRIPTION_ID),
        resource_group=os.getenv("FOUNDRY_RESOURCE_GROUP", DEFAULT_RESOURCE_GROUP),
        account_name=os.getenv("FOUNDRY_ACCOUNT_NAME", DEFAULT_ACCOUNT_NAME),
        location=os.getenv("FOUNDRY_LOCATION", DEFAULT_LOCATION),
        project_url=os.getenv("FOUNDRY_PROJECT_URL", DEFAULT_PROJECT_URL),
        base_url=os.getenv("FOUNDRY_BASE_URL", DEFAULT_BASE_URL),
    )
