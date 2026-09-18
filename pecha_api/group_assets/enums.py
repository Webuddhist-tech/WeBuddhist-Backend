import enum

from sqlalchemy import Enum


class GroupAssetType(enum.Enum):
    AUDIO = "AUDIO"
    # Reserved: covers, post media and event images are all group-owned files
    # that can move into this table later. v1 accepts AUDIO only.
    IMAGE = "IMAGE"
    VIDEO = "VIDEO"


GroupAssetTypeEnum = Enum(
    GroupAssetType,
    name="group_asset_type",
)
