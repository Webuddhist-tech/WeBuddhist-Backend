from collections import defaultdict

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi

TAG_GROUP_ORDER = ("Texts", "Public", "User","CMS")

TEXT_TAGS = frozenset(
    {
        "Segments",
        "segments-v2",
        "Texts",
        "texts-v2",
        "Sheets",
        "Search",
        "collections",
        "collections-v2",
        "Text Mapping",
        "Groups",
        "Share",
        "Recitations",
        "CMS Text Uploader",
        "CMS Cataloger",
    }
)

# Tags that live under /users paths but do not use a "User " prefix in the router.
USER_TAGS = frozenset(
    {
        "Bookmarks",
        "Push Devices",
        "Mantra Counts",
        "Recitation Collections",
        "Daily Log",
    }
)


BEARER_SECURITY_SCHEME = "BearerAuth"


def normalize_openapi_security_schemes(schema: dict) -> None:
    """Collapse HTTP bearer schemes into a single documented BearerAuth entry."""
    components = schema.setdefault("components", {})
    schemes = components.get("securitySchemes", {})
    bearer_keys = [
        name
        for name, scheme in schemes.items()
        if scheme.get("type") == "http" and scheme.get("scheme") == "bearer"
    ]
    if not bearer_keys:
        components["securitySchemes"] = {
            BEARER_SECURITY_SCHEME: {
                "type": "http",
                "scheme": "bearer",
                "bearerFormat": "JWT",
                "description": "Auth0 access token for the WeBuddhist API.",
            }
        }
        return

    components["securitySchemes"] = {
        BEARER_SECURITY_SCHEME: {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "JWT",
            "description": "Auth0 access token for the WeBuddhist API.",
        }
    }

    def _replace_security(node) -> None:
        if isinstance(node, dict):
            security = node.get("security")
            if isinstance(security, list):
                updated_requirements = []
                for requirement in security:
                    if not isinstance(requirement, dict):
                        updated_requirements.append(requirement)
                        continue
                    if any(key in bearer_keys for key in requirement):
                        scopes = next(
                            (requirement[key] for key in bearer_keys if key in requirement),
                            [],
                        )
                        updated_requirements.append({BEARER_SECURITY_SCHEME: scopes})
                    else:
                        updated_requirements.append(requirement)
                node["security"] = updated_requirements
            for value in node.values():
                _replace_security(value)
        elif isinstance(node, list):
            for item in node:
                _replace_security(item)

    _replace_security(schema.get("paths", {}))


def classify_openapi_tag(tag: str) -> str:
    if tag.startswith("User "):
        return "User"
    if tag in USER_TAGS:
        return "User"
    if tag in TEXT_TAGS:
        return "Texts"
    if tag.startswith("CMS "):
        return "CMS"
    if tag.startswith("Public "):
        return "Public"
    return "Public"


def collect_openapi_tags(schema: dict) -> list[str]:
    tags: set[str] = set()
    for tag_info in schema.get("tags", []):
        tags.add(tag_info["name"])
    for path_item in schema.get("paths", {}).values():
        for operation in path_item.values():
            if isinstance(operation, dict):
                tags.update(operation.get("tags", []))
    return sorted(tags)


def build_x_tag_groups(schema: dict) -> list[dict]:
    grouped: dict[str, list[str]] = defaultdict(list)
    for tag in collect_openapi_tags(schema):
        grouped[classify_openapi_tag(tag)].append(tag)
    return [
        {"name": group_name, "tags": grouped[group_name]}
        for group_name in TAG_GROUP_ORDER
        if grouped[group_name]
    ]


def configure_openapi_tag_groups(app: FastAPI) -> None:
    def custom_openapi() -> dict:
        if app.openapi_schema:
            return app.openapi_schema

        openapi_schema = get_openapi(
            title=app.title,
            version=app.version,
            openapi_version=app.openapi_version,
            description=app.description,
            routes=app.routes,
        )
        openapi_schema["x-tagGroups"] = build_x_tag_groups(openapi_schema)
        normalize_openapi_security_schemes(openapi_schema)
        app.openapi_schema = openapi_schema
        return app.openapi_schema

    app.openapi = custom_openapi
