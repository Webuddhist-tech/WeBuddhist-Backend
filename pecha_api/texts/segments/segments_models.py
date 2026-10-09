from typing import List, Optional, Dict
import re
import uuid
from pydantic import BaseModel, Field
from beanie import Document

from .segments_enum import SegmentType

class Mapping(BaseModel):
    text_id: str
    segments: List[str]


class Segment(Document):
    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    pecha_segment_id: Optional[str] = None
    text_id: str
    content: str
    mapping: Optional[List[Mapping]] = None
    type: SegmentType

    class Settings:
        collection = "segments"
        indexes = [
            "text_id",
            "mapping.segments",
        ]

    @classmethod
    async def get_segment_by_id(cls, segment_id: str) -> Optional["Segment"]:
        return await cls.find_one(cls.id == uuid.UUID(segment_id))
    
    @classmethod
    async def get_segment_by_pecha_segment_id(cls, pecha_segment_id: str) -> Optional["Segment"]:
        # Dict query: Pydantic v2's model metaclass does not expose
        # `cls.pecha_segment_id` as a Beanie ExpressionField, so
        # `cls.pecha_segment_id == value` raises AttributeError.
        return await cls.find_one({"pecha_segment_id": pecha_segment_id})

    @classmethod
    async def get_segments_by_text_id(cls, text_id: str) -> List["Segment"]:
        return await cls.find(cls.text_id == text_id).to_list()

    @classmethod
    async def search_segments_by_content(cls, content: str, limit: int = 10) -> List["Segment"]:
        return await cls.find(
            {"content": {"$regex": re.escape(content)}}
        ).limit(limit).to_list()

    @classmethod
    async def get_first_segment_by_text_id(cls, text_id: str) -> Optional["Segment"]:
        return await cls.find_one({"text_id": text_id})

    @classmethod
    async def check_exists(cls, segment_id: uuid.UUID) -> bool:
        segment = await cls.find_one(cls.id == segment_id)
        return segment is not None

    
    @classmethod
    async def exists_all(cls, segment_ids: List[uuid.UUID], batch_size: int = 100) -> bool:
        if not segment_ids:
            return False
        found_segments = await cls.find({"_id": {"$in": segment_ids}}).to_list()
        found_ids = {segment.id for segment in found_segments}
        for segment_id in segment_ids:
            if segment_id not in found_ids:
                return False
        return True

    @classmethod
    async def get_segments_by_ids(cls, segment_ids: List[str]) -> List["Segment"]:
        segment_ids = [uuid.UUID(segment_id) for segment_id in segment_ids]
        return await cls.find({"_id": {"$in": segment_ids}}).to_list(length=len(segment_ids))

    @classmethod
    async def get_related_mapped_segments(cls, parent_segment_id: str) -> List["Segment"]:
        # Find segments where:
        # 1. There exists a mapping object with text_id matching parent_text_id
        # 2. Within that same mapping object, segments list contains parent_segment_id
        query = {
            "mapping": {
                "$elemMatch": {
                    "segments": {"$in": [parent_segment_id]}
                }
            }
        }
        return await cls.find(query).to_list()
    
    @classmethod
    async def get_segments_by_pecha_ids(
        cls, 
        pecha_segment_ids: List[str],
        text_id: Optional[str] = None
    ) -> List["Segment"]:

        query = {"pecha_segment_id": {"$in": pecha_segment_ids}}
        if text_id:
            query["text_id"] = text_id
        
        return await cls.find(query).to_list()

    @classmethod
    async def get_related_mapped_segments_batch(
        cls, 
        parent_segment_ids: List[str],
        text_types: Optional[List[str]] = None
    ) -> Dict[str, List["Segment"]]:

        if not parent_segment_ids:
            return {}
        
        query = {
            "mapping": {
                "$elemMatch": {
                    "segments": {"$in": parent_segment_ids}
                }
            }
        }
        
        segments = await cls.find(query).to_list()
        
        result: Dict[str, List["Segment"]] = {pid: [] for pid in parent_segment_ids}
        
        for segment in segments:
            if segment.mapping:
                for mapping in segment.mapping:
                    for parent_id in parent_segment_ids:
                        if parent_id in mapping.segments:
                            if segment not in result[parent_id]:
                                result[parent_id].append(segment)
        
        return result

    @staticmethod
    def _partition_segment_identifiers(
        segment_ids: List[str],
    ) -> tuple[List[uuid.UUID], List[str]]:
        segment_uuids: List[uuid.UUID] = []
        pecha_segment_ids: List[str] = []
        seen_uuids: set[uuid.UUID] = set()
        seen_pecha_ids: set[str] = set()

        for segment_id in segment_ids:
            if not segment_id:
                continue
            try:
                parsed_uuid = uuid.UUID(segment_id)
            except ValueError:
                if segment_id not in seen_pecha_ids:
                    pecha_segment_ids.append(segment_id)
                    seen_pecha_ids.add(segment_id)
                continue

            if parsed_uuid not in seen_uuids:
                segment_uuids.append(parsed_uuid)
                seen_uuids.add(parsed_uuid)

        return segment_uuids, pecha_segment_ids

    @classmethod
    async def _load_projected_segment_contents(
        cls,
        *,
        segment_uuids: List[uuid.UUID],
        pecha_segment_ids: List[str],
    ) -> Dict[str, tuple[str, str]]:
        contents: Dict[str, tuple[str, str]] = {}

        if segment_uuids:
            segments = await cls.find({"_id": {"$in": segment_uuids}}).to_list()
            for segment in segments:
                contents[str(segment.id)] = (segment.text_id, segment.content)

        if pecha_segment_ids:
            cursor = cls.get_motor_collection().find(
                {"pecha_segment_id": {"$in": pecha_segment_ids}},
                {"text_id": 1, "content": 1, "pecha_segment_id": 1},
            )
            async for document in cursor:
                pecha_segment_id = document.get("pecha_segment_id")
                if not pecha_segment_id:
                    continue
                contents[pecha_segment_id] = (
                    document.get("text_id", ""),
                    document.get("content", ""),
                )

        return contents

    @classmethod
    async def get_segment_contents_by_ids(
        cls,
        segment_ids: List[str],
    ) -> Dict[str, tuple[str, str]]:
        """Fetch only text_id and content for Mongo UUID or pecha segment identifiers."""
        if not segment_ids:
            return {}

        segment_uuids, pecha_segment_ids = cls._partition_segment_identifiers(segment_ids)
        return await cls._load_projected_segment_contents(
            segment_uuids=segment_uuids,
            pecha_segment_ids=pecha_segment_ids,
        )

    @classmethod
    async def get_version_translation_contents_by_parent_ids(
        cls,
        parent_segment_ids: List[str],
        version_text_id: str,
    ) -> Dict[str, str]:
        """Map parent segment id -> translation content for a specific version text."""
        if not parent_segment_ids or not version_text_id:
            return {}

        query = {
            "text_id": version_text_id,
            "mapping": {
                "$elemMatch": {
                    "segments": {"$in": parent_segment_ids},
                }
            },
        }
        cursor = cls.get_motor_collection().find(
            query,
            {"content": 1, "mapping": 1},
        )

        translations: Dict[str, str] = {}
        async for document in cursor:
            content = document.get("content", "")
            for mapping in document.get("mapping") or []:
                for parent_id in mapping.get("segments") or []:
                    if parent_id in parent_segment_ids and parent_id not in translations:
                        translations[parent_id] = content
        return translations