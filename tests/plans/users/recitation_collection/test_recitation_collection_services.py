import pytest
from unittest.mock import patch, MagicMock
from uuid import uuid4
from fastapi import HTTPException
from pydantic import ValidationError
from starlette import status

from pecha_api.plans.users.recitation_collection.recitation_collection_service import (
    get_user_collections_service,
    get_collection_detail_service,
    create_collection_service,
    update_collection_service,
    upload_collection_image_service,
    add_items_to_collection_service,
    delete_collection_service,
    delete_collection_item_service,
    update_collection_item_display_order_service,
    _generate_presigned_url
)
from pecha_api.plans.users.recitation_collection.recitation_collection_response_models import (
    RecitationCollectionsResponse,
    RecitationCollectionDTO,
    RecitationCollectionDetailDTO,
    RecitationCollectionItemDTO,
    CreateCollectionRequest,
    CreateCollectionResponse,
    UpdateCollectionRequest,
    UpdateCollectionItemRequest,
    AddItemsRequest,
    AddItemsResponse
)
from pecha_api.plans.media.media_response_models import ImageUrlModel, PlanUploadResponse


class MockUser:
    def __init__(self, id=None):
        self.id = id or uuid4()


class MockCollection:
    def __init__(self, id=None, user_id=None, name="Test Collection", img_url="images/test.jpg", created_at="2025-06-09T10:00:00", updated_at="2025-06-09T10:00:00"):
        self.id = id or uuid4()
        self.user_id = user_id or uuid4()
        self.name = name
        self.img_url = img_url
        self.created_at = created_at
        self.updated_at = updated_at


class MockCollectionItem:
    def __init__(self, id=None, recitation_collection_id=None, text_id=None, display_order=1):
        self.id = id or uuid4()
        self.recitation_collection_id = recitation_collection_id or uuid4()
        self.text_id = str(text_id or uuid4())
        self.display_order = display_order


class MockTextDTO:
    def __init__(self, title="Test Text", language="bo", type="root_text"):
        self.title = title
        self.language = language
        self.type = type


class TestGeneratePresignedUrl:

    def test_returns_none_when_key_is_empty(self):
        assert _generate_presigned_url("") is None
        assert _generate_presigned_url(None) is None

    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_service.get')
    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_service.generate_presigned_access_url')
    def test_returns_presigned_url_on_success(self, mock_generate, mock_get):
        mock_get.return_value = "test-bucket"
        mock_generate.return_value = "https://signed.example.com/img.jpg"

        result = _generate_presigned_url("images/test.jpg")

        assert result == "https://signed.example.com/img.jpg"
        mock_generate.assert_called_once_with(
            bucket_name="test-bucket",
            s3_key="images/test.jpg"
        )

    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_service.get')
    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_service.generate_presigned_access_url')
    def test_returns_none_when_generation_raises(self, mock_generate, mock_get):
        mock_get.return_value = "test-bucket"
        mock_generate.side_effect = Exception("S3 boom")

        result = _generate_presigned_url("images/test.jpg")

        assert result is None


class TestGetUserCollectionsService:

    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_service.validate_and_extract_user_details')
    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_service.SessionLocal')
    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_service.get_user_collections')
    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_service.get_collection_item_counts')
    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_service._generate_presigned_url')
    @pytest.mark.asyncio
    async def test_get_user_collections_success(
        self,
        mock_presigned_url,
        mock_item_counts,
        mock_get_collections,
        mock_session,
        mock_validate
    ):
        user_id = uuid4()
        collection_id_1 = uuid4()
        collection_id_2 = uuid4()

        mock_validate.return_value = MockUser(id=user_id)

        mock_db = MagicMock()
        mock_session.return_value.__enter__ = MagicMock(return_value=mock_db)
        mock_session.return_value.__exit__ = MagicMock(return_value=False)

        collections = [
            MockCollection(id=collection_id_1, name="Morning Prayers"),
            MockCollection(id=collection_id_2, name="Evening Prayers")
        ]
        mock_get_collections.return_value = (collections, 2)
        mock_item_counts.return_value = {collection_id_1: 5, collection_id_2: 3}
        mock_presigned_url.return_value = "https://presigned-url.com/image.jpg"

        result = await get_user_collections_service(token="valid_token", skip=0, limit=20)

        assert isinstance(result, RecitationCollectionsResponse)
        assert len(result.collections) == 2
        assert result.collections[0].name == "Morning Prayers"
        assert result.collections[0].item_count == 5
        assert result.collections[1].name == "Evening Prayers"
        assert result.collections[1].item_count == 3
        assert result.total == 2

        mock_validate.assert_called_once_with(token="valid_token")
        mock_get_collections.assert_called_once_with(db=mock_db, user_id=user_id, skip=0, limit=20)

    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_service.validate_and_extract_user_details')
    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_service.SessionLocal')
    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_service.get_user_collections')
    @pytest.mark.asyncio
    async def test_get_user_collections_empty(
        self,
        mock_get_collections,
        mock_session,
        mock_validate
    ):
        user_id = uuid4()
        mock_validate.return_value = MockUser(id=user_id)

        mock_db = MagicMock()
        mock_session.return_value.__enter__ = MagicMock(return_value=mock_db)
        mock_session.return_value.__exit__ = MagicMock(return_value=False)

        mock_get_collections.return_value = ([], 0)

        result = await get_user_collections_service(token="valid_token", skip=0, limit=20)

        assert isinstance(result, RecitationCollectionsResponse)
        assert len(result.collections) == 0
        assert result.total == 0

    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_service.validate_and_extract_user_details')
    @pytest.mark.asyncio
    async def test_get_user_collections_invalid_token(self, mock_validate):
        mock_validate.side_effect = HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials"
        )

        with pytest.raises(HTTPException) as exc_info:
            await get_user_collections_service(token="invalid_token", skip=0, limit=20)

        assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED

    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_service.validate_and_extract_user_details')
    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_service.SessionLocal')
    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_service.get_user_collections')
    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_service.get_collection_item_counts')
    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_service._generate_presigned_url')
    @pytest.mark.asyncio
    async def test_get_user_collections_with_pagination(
        self,
        mock_presigned_url,
        mock_item_counts,
        mock_get_collections,
        mock_session,
        mock_validate
    ):
        user_id = uuid4()
        mock_validate.return_value = MockUser(id=user_id)

        mock_db = MagicMock()
        mock_session.return_value.__enter__ = MagicMock(return_value=mock_db)
        mock_session.return_value.__exit__ = MagicMock(return_value=False)

        collections = [MockCollection(name=f"Collection {i}") for i in range(5)]
        mock_get_collections.return_value = (collections, 25)
        mock_item_counts.return_value = {c.id: 2 for c in collections}
        mock_presigned_url.return_value = "https://presigned-url.com/image.jpg"

        result = await get_user_collections_service(token="valid_token", skip=10, limit=5)

        assert len(result.collections) == 5
        assert result.skip == 10
        assert result.limit == 5
        assert result.total == 25

        mock_get_collections.assert_called_once_with(db=mock_db, user_id=user_id, skip=10, limit=5)


class TestGetCollectionDetailService:

    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_service.validate_and_extract_user_details')
    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_service.SessionLocal')
    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_service.get_collection_by_id')
    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_service.get_collection_items')
    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_service.get_texts_by_edition_or_text_ids')
    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_service._generate_presigned_url')
    @pytest.mark.asyncio
    async def test_get_collection_detail_success(
        self,
        mock_presigned_url,
        mock_get_texts,
        mock_get_items,
        mock_get_collection,
        mock_session,
        mock_validate
    ):
        user_id = uuid4()
        collection_id = uuid4()
        text_id_1 = uuid4()
        text_id_2 = uuid4()

        mock_validate.return_value = MockUser(id=user_id)

        mock_db = MagicMock()
        mock_session.return_value.__enter__ = MagicMock(return_value=mock_db)
        mock_session.return_value.__exit__ = MagicMock(return_value=False)

        mock_collection = MockCollection(id=collection_id, name="Morning Prayers")
        mock_get_collection.return_value = mock_collection

        items = [
            MockCollectionItem(text_id=text_id_1, display_order=1),
            MockCollectionItem(text_id=text_id_2, display_order=2)
        ]
        mock_get_items.return_value = items

        mock_get_texts.return_value = {
            str(text_id_1): MockTextDTO(title="Heart Sutra", language="bo"),
            str(text_id_2): MockTextDTO(title="Diamond Sutra", language="en")
        }
        mock_presigned_url.return_value = "https://presigned-url.com/image.jpg"

        result = await get_collection_detail_service(token="valid_token", collection_id=collection_id)

        assert isinstance(result, RecitationCollectionDetailDTO)
        assert result.id == collection_id
        assert result.name == "Morning Prayers"
        assert len(result.items) == 2
        assert result.items[0].title == "Heart Sutra"
        assert result.items[1].title == "Diamond Sutra"

        mock_validate.assert_called_once_with(token="valid_token")
        mock_get_collection.assert_called_once_with(db=mock_db, collection_id=collection_id, user_id=user_id)

    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_service.validate_and_extract_user_details')
    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_service.SessionLocal')
    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_service.get_collection_by_id')
    @pytest.mark.asyncio
    async def test_get_collection_detail_not_found(
        self,
        mock_get_collection,
        mock_session,
        mock_validate
    ):
        user_id = uuid4()
        collection_id = uuid4()

        mock_validate.return_value = MockUser(id=user_id)

        mock_db = MagicMock()
        mock_session.return_value.__enter__ = MagicMock(return_value=mock_db)
        mock_session.return_value.__exit__ = MagicMock(return_value=False)

        mock_get_collection.return_value = None

        with pytest.raises(HTTPException) as exc_info:
            await get_collection_detail_service(token="valid_token", collection_id=collection_id)

        assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND

    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_service.validate_and_extract_user_details')
    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_service.SessionLocal')
    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_service.get_collection_by_id')
    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_service.get_collection_items')
    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_service._generate_presigned_url')
    @pytest.mark.asyncio
    async def test_get_collection_detail_empty_items(
        self,
        mock_presigned_url,
        mock_get_items,
        mock_get_collection,
        mock_session,
        mock_validate
    ):
        user_id = uuid4()
        collection_id = uuid4()

        mock_validate.return_value = MockUser(id=user_id)

        mock_db = MagicMock()
        mock_session.return_value.__enter__ = MagicMock(return_value=mock_db)
        mock_session.return_value.__exit__ = MagicMock(return_value=False)

        mock_collection = MockCollection(id=collection_id, name="Empty Collection")
        mock_get_collection.return_value = mock_collection
        mock_get_items.return_value = []
        mock_presigned_url.return_value = "https://presigned-url.com/image.jpg"

        result = await get_collection_detail_service(token="valid_token", collection_id=collection_id)

        assert isinstance(result, RecitationCollectionDetailDTO)
        assert result.name == "Empty Collection"
        assert len(result.items) == 0

    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_service.validate_and_extract_user_details')
    @pytest.mark.asyncio
    async def test_get_collection_detail_invalid_token(self, mock_validate):
        collection_id = uuid4()

        mock_validate.side_effect = HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials"
        )

        with pytest.raises(HTTPException) as exc_info:
            await get_collection_detail_service(token="invalid_token", collection_id=collection_id)

        assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED

    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_service.validate_and_extract_user_details')
    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_service.SessionLocal')
    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_service.get_collection_by_id')
    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_service.get_collection_items')
    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_service.get_texts_by_edition_or_text_ids')
    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_service._generate_presigned_url')
    @pytest.mark.asyncio
    async def test_get_collection_detail_filters_missing_texts(
        self,
        mock_presigned_url,
        mock_get_texts,
        mock_get_items,
        mock_get_collection,
        mock_session,
        mock_validate
    ):
        user_id = uuid4()
        collection_id = uuid4()
        text_id_1 = uuid4()
        text_id_2 = uuid4()

        mock_validate.return_value = MockUser(id=user_id)

        mock_db = MagicMock()
        mock_session.return_value.__enter__ = MagicMock(return_value=mock_db)
        mock_session.return_value.__exit__ = MagicMock(return_value=False)

        mock_collection = MockCollection(id=collection_id, name="Test Collection")
        mock_get_collection.return_value = mock_collection

        items = [
            MockCollectionItem(text_id=text_id_1, display_order=1),
            MockCollectionItem(text_id=text_id_2, display_order=2)
        ]
        mock_get_items.return_value = items

        mock_get_texts.return_value = {
            str(text_id_1): MockTextDTO(title="Heart Sutra")
        }
        mock_presigned_url.return_value = "https://presigned-url.com/image.jpg"

        result = await get_collection_detail_service(token="valid_token", collection_id=collection_id)

        assert len(result.items) == 1
        assert result.items[0].title == "Heart Sutra"


class TestCreateCollectionService:

    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_service.validate_and_extract_user_details')
    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_service.SessionLocal')
    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_service.save_collection')
    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_service._generate_presigned_url')
    @pytest.mark.asyncio
    async def test_create_collection_success(
        self,
        mock_presigned_url,
        mock_save_collection,
        mock_session,
        mock_validate
    ):
        """Test successful collection creation"""
        user_id = uuid4()
        collection_id = uuid4()

        mock_validate.return_value = MockUser(id=user_id)

        mock_db = MagicMock()
        mock_session.return_value.__enter__ = MagicMock(return_value=mock_db)
        mock_session.return_value.__exit__ = MagicMock(return_value=False)

        saved_collection = MockCollection(
            id=collection_id,
            user_id=user_id,
            name="Morning Prayers",
            img_url="images/collections/test.jpg"
        )
        mock_save_collection.return_value = saved_collection
        mock_presigned_url.return_value = "https://presigned-url.com/test.jpg"

        request = CreateCollectionRequest(name="Morning Prayers", img_url="images/collections/test.jpg")
        result = await create_collection_service(token="valid_token", request=request)

        assert isinstance(result, CreateCollectionResponse)
        assert result.id == collection_id
        assert result.name == "Morning Prayers"
        assert result.img_url == "https://presigned-url.com/test.jpg"

        mock_validate.assert_called_once_with(token="valid_token")
        mock_save_collection.assert_called_once()

    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_service.validate_and_extract_user_details')
    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_service.SessionLocal')
    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_service.save_collection')
    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_service._generate_presigned_url')
    @pytest.mark.asyncio
    async def test_create_collection_without_image(
        self,
        mock_presigned_url,
        mock_save_collection,
        mock_session,
        mock_validate
    ):
        """Test creating collection without image URL"""
        user_id = uuid4()
        collection_id = uuid4()

        mock_validate.return_value = MockUser(id=user_id)

        mock_db = MagicMock()
        mock_session.return_value.__enter__ = MagicMock(return_value=mock_db)
        mock_session.return_value.__exit__ = MagicMock(return_value=False)

        saved_collection = MockCollection(
            id=collection_id,
            user_id=user_id,
            name="No Image Collection",
            img_url=""
        )
        mock_save_collection.return_value = saved_collection
        mock_presigned_url.return_value = None

        request = CreateCollectionRequest(name="No Image Collection", img_url="")
        result = await create_collection_service(token="valid_token", request=request)

        assert result.name == "No Image Collection"
        assert result.img_url is None

    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_service.validate_and_extract_user_details')
    @pytest.mark.asyncio
    async def test_create_collection_invalid_token(self, mock_validate):
        """Test creating collection with invalid token"""
        mock_validate.side_effect = HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials"
        )

        request = CreateCollectionRequest(name="Test Collection", img_url="images/test.jpg")

        with pytest.raises(HTTPException) as exc_info:
            await create_collection_service(token="invalid_token", request=request)

        assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED

    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_service.validate_and_extract_user_details')
    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_service.SessionLocal')
    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_service.save_collection')
    @pytest.mark.asyncio
    async def test_create_collection_database_error(
        self,
        mock_save_collection,
        mock_session,
        mock_validate
    ):
        """Test database error during collection creation"""
        user_id = uuid4()
        mock_validate.return_value = MockUser(id=user_id)

        mock_db = MagicMock()
        mock_session.return_value.__enter__ = MagicMock(return_value=mock_db)
        mock_session.return_value.__exit__ = MagicMock(return_value=False)

        mock_save_collection.side_effect = HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "BAD_REQUEST", "message": "Database error"}
        )

        request = CreateCollectionRequest(name="Test Collection", img_url="images/test.jpg")

        with pytest.raises(HTTPException) as exc_info:
            await create_collection_service(token="valid_token", request=request)

        assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST

    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_service.validate_and_extract_user_details')
    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_service.SessionLocal')
    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_service.save_collection')
    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_service._generate_presigned_url')
    @pytest.mark.asyncio
    async def test_create_collection_with_special_characters(
        self,
        mock_presigned_url,
        mock_save_collection,
        mock_session,
        mock_validate
    ):
        """Test creating collection with special characters and Tibetan text"""
        user_id = uuid4()
        collection_id = uuid4()
        special_name = "Morning Prayers 🙏 - དུས་གསུམ་སངས་རྒྱས།"

        mock_validate.return_value = MockUser(id=user_id)

        mock_db = MagicMock()
        mock_session.return_value.__enter__ = MagicMock(return_value=mock_db)
        mock_session.return_value.__exit__ = MagicMock(return_value=False)

        saved_collection = MockCollection(
            id=collection_id,
            user_id=user_id,
            name=special_name,
            img_url="images/test.jpg"
        )
        mock_save_collection.return_value = saved_collection
        mock_presigned_url.return_value = "https://presigned-url.com/test.jpg"

        request = CreateCollectionRequest(name=special_name, img_url="images/test.jpg")
        result = await create_collection_service(token="valid_token", request=request)

        assert result.name == special_name

    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_service.validate_and_extract_user_details')
    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_service.SessionLocal')
    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_service.save_collection')
    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_service._generate_presigned_url')
    @pytest.mark.asyncio
    async def test_create_collection_stores_key_when_full_url_given(
        self,
        mock_presigned_url,
        mock_save_collection,
        mock_session,
        mock_validate
    ):
        """Passing a full presigned URL as img_url should store only the S3 key"""
        user_id = uuid4()

        mock_validate.return_value = MockUser(id=user_id)

        mock_db = MagicMock()
        mock_session.return_value.__enter__ = MagicMock(return_value=mock_db)
        mock_session.return_value.__exit__ = MagicMock(return_value=False)

        def _save_with_id(db, collection):
            collection.id = uuid4()
            return collection
        mock_save_collection.side_effect = _save_with_id
        mock_presigned_url.return_value = "https://presigned-url.com/collections/test.jpg"

        full_url = "https://bucket.s3.amazonaws.com/images/collections/test.jpg?X-Amz-Signature=abc123"
        request = CreateCollectionRequest(name="Morning Prayers", img_url=full_url)
        await create_collection_service(token="valid_token", request=request)

        saved_collection = mock_save_collection.call_args.kwargs["collection"]
        assert saved_collection.img_url == "images/collections/test.jpg"

    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_service.validate_and_extract_user_details')
    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_service.SessionLocal')
    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_service.save_collection')
    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_service._generate_presigned_url')
    @pytest.mark.asyncio
    async def test_create_collection_stores_key_when_plain_key_given(
        self,
        mock_presigned_url,
        mock_save_collection,
        mock_session,
        mock_validate
    ):
        """Passing a plain S3 key as img_url should store it unchanged"""
        user_id = uuid4()

        mock_validate.return_value = MockUser(id=user_id)

        mock_db = MagicMock()
        mock_session.return_value.__enter__ = MagicMock(return_value=mock_db)
        mock_session.return_value.__exit__ = MagicMock(return_value=False)

        def _save_with_id(db, collection):
            collection.id = uuid4()
            return collection
        mock_save_collection.side_effect = _save_with_id
        mock_presigned_url.return_value = "https://presigned-url.com/collections/test.jpg"

        request = CreateCollectionRequest(name="Morning Prayers", img_url="images/collections/test.jpg")
        await create_collection_service(token="valid_token", request=request)

        saved_collection = mock_save_collection.call_args.kwargs["collection"]
        assert saved_collection.img_url == "images/collections/test.jpg"

    def test_create_collection_request_rejects_extra_fields(self):
        """Only name and img_url should be accepted on create"""
        with pytest.raises(ValidationError):
            CreateCollectionRequest(
                name="Morning Prayers",
                img_url="images/test.jpg",
                user_id=str(uuid4()),
            )


class TestUpdateCollectionService:

    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_service.validate_and_extract_user_details')
    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_service.SessionLocal')
    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_service.get_collection_by_id')
    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_service.update_collection')
    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_service._generate_presigned_url')
    @pytest.mark.asyncio
    async def test_update_collection_success(
        self,
        mock_presigned_url,
        mock_update_collection,
        mock_get_collection,
        mock_session,
        mock_validate
    ):
        """Test successful collection update"""
        user_id = uuid4()
        collection_id = uuid4()

        mock_validate.return_value = MockUser(id=user_id)

        mock_db = MagicMock()
        mock_session.return_value.__enter__ = MagicMock(return_value=mock_db)
        mock_session.return_value.__exit__ = MagicMock(return_value=False)

        collection = MockCollection(
            id=collection_id,
            user_id=user_id,
            name="Old Name",
            img_url="images/old.jpg",
        )
        mock_get_collection.return_value = collection
        mock_update_collection.return_value = collection
        mock_presigned_url.return_value = "https://presigned-url.com/new.jpg"

        request = UpdateCollectionRequest(name="New Name", img_url="images/new.jpg")
        result = await update_collection_service(
            token="valid_token",
            collection_id=collection_id,
            request=request,
        )

        assert isinstance(result, CreateCollectionResponse)
        assert result.name == "New Name"
        assert collection.name == "New Name"
        assert collection.img_url == "images/new.jpg"
        mock_update_collection.assert_called_once_with(db=mock_db, collection=collection)

    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_service.validate_and_extract_user_details')
    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_service.SessionLocal')
    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_service.get_collection_by_id')
    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_service.update_collection')
    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_service._generate_presigned_url')
    @pytest.mark.asyncio
    async def test_update_collection_partial_name_only(
        self,
        mock_presigned_url,
        mock_update_collection,
        mock_get_collection,
        mock_session,
        mock_validate
    ):
        """Test updating only the name leaves img_url untouched"""
        user_id = uuid4()
        collection_id = uuid4()

        mock_validate.return_value = MockUser(id=user_id)

        mock_db = MagicMock()
        mock_session.return_value.__enter__ = MagicMock(return_value=mock_db)
        mock_session.return_value.__exit__ = MagicMock(return_value=False)

        collection = MockCollection(
            id=collection_id,
            user_id=user_id,
            name="Old Name",
            img_url="images/unchanged.jpg",
        )
        mock_get_collection.return_value = collection
        mock_update_collection.return_value = collection
        mock_presigned_url.return_value = "https://presigned-url.com/unchanged.jpg"

        request = UpdateCollectionRequest(name="New Name")
        result = await update_collection_service(
            token="valid_token",
            collection_id=collection_id,
            request=request,
        )

        assert result.name == "New Name"
        assert collection.img_url == "images/unchanged.jpg"

    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_service.validate_and_extract_user_details')
    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_service.SessionLocal')
    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_service.get_collection_by_id')
    @pytest.mark.asyncio
    async def test_update_collection_not_found(
        self,
        mock_get_collection,
        mock_session,
        mock_validate
    ):
        """Test updating a non-existent collection"""
        user_id = uuid4()
        collection_id = uuid4()

        mock_validate.return_value = MockUser(id=user_id)

        mock_db = MagicMock()
        mock_session.return_value.__enter__ = MagicMock(return_value=mock_db)
        mock_session.return_value.__exit__ = MagicMock(return_value=False)

        mock_get_collection.return_value = None

        request = UpdateCollectionRequest(name="New Name")

        with pytest.raises(HTTPException) as exc_info:
            await update_collection_service(
                token="valid_token",
                collection_id=collection_id,
                request=request,
            )

        assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND

    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_service.validate_and_extract_user_details')
    @pytest.mark.asyncio
    async def test_update_collection_invalid_token(self, mock_validate):
        """Test updating a collection with an invalid token"""
        mock_validate.side_effect = HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials"
        )

        request = UpdateCollectionRequest(name="New Name")

        with pytest.raises(HTTPException) as exc_info:
            await update_collection_service(
                token="invalid_token",
                collection_id=uuid4(),
                request=request,
            )

        assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED

    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_service.validate_and_extract_user_details')
    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_service.SessionLocal')
    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_service.get_collection_by_id')
    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_service.update_collection')
    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_service._generate_presigned_url')
    @pytest.mark.asyncio
    async def test_update_collection_stores_key_when_full_url_given(
        self,
        mock_presigned_url,
        mock_update_collection,
        mock_get_collection,
        mock_session,
        mock_validate
    ):
        """Passing a full presigned URL as img_url should store only the S3 key"""
        user_id = uuid4()
        collection_id = uuid4()

        mock_validate.return_value = MockUser(id=user_id)

        mock_db = MagicMock()
        mock_session.return_value.__enter__ = MagicMock(return_value=mock_db)
        mock_session.return_value.__exit__ = MagicMock(return_value=False)

        collection = MockCollection(
            id=collection_id,
            user_id=user_id,
            name="Old Name",
            img_url="images/old.jpg",
        )
        mock_get_collection.return_value = collection
        mock_update_collection.side_effect = lambda db, collection: collection
        mock_presigned_url.return_value = "https://presigned-url.com/new.jpg"

        full_url = "https://bucket.s3.amazonaws.com/images/collections/new.jpg?X-Amz-Signature=abc123"
        request = UpdateCollectionRequest(img_url=full_url)
        await update_collection_service(
            token="valid_token",
            collection_id=collection_id,
            request=request,
        )

        assert collection.img_url == "images/collections/new.jpg"

    def test_update_collection_request_rejects_extra_fields(self):
        """Only name and img_url should be accepted on update"""
        with pytest.raises(ValidationError):
            UpdateCollectionRequest(
                name="New Name",
                id=str(uuid4()),
            )


class TestUploadCollectionImageService:

    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_service.validate_and_extract_user_details')
    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_service.validate_file')
    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_service.prepare_image_upload')
    def test_upload_success(
        self,
        mock_prepare_upload,
        mock_validate_file,
        mock_validate,
    ):
        """Test successful image upload for a user's recitation collection"""
        user_id = uuid4()
        mock_validate.return_value = MockUser(id=user_id)

        image_url_model = ImageUrlModel(
            thumbnail="https://signed/thumb",
            medium="https://signed/medium",
            original="https://signed/original",
        )
        mock_prepare_upload.return_value = (
            image_url_model,
            "images/recitation_collection_images/key",
        )
        mock_file = MagicMock()

        result = upload_collection_image_service(token="valid_token", file=mock_file)

        assert isinstance(result, PlanUploadResponse)
        assert result.key == "images/recitation_collection_images/key"
        assert result.image.thumbnail == "https://signed/thumb"
        mock_validate.assert_called_once_with(token="valid_token")
        mock_validate_file.assert_called_once_with(mock_file)

    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_service.validate_and_extract_user_details')
    def test_upload_invalid_token(self, mock_validate):
        """Test uploading an image with an invalid token"""
        mock_validate.side_effect = HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials"
        )

        with pytest.raises(HTTPException) as exc_info:
            upload_collection_image_service(token="invalid_token", file=MagicMock())

        assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED


class TestAddItemsToCollectionService:

    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_service.validate_and_extract_user_details')
    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_service.SessionLocal')
    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_service.get_collection_by_id')
    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_service.get_max_display_order_for_collection')
    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_service.save_collection_items')
    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_service.get_texts_by_edition_or_text_ids')
    @pytest.mark.asyncio
    async def test_add_items_single_success(
        self,
        mock_get_texts,
        mock_save_items,
        mock_max_order,
        mock_get_collection,
        mock_session,
        mock_validate
    ):
        """Test successfully adding single item to collection"""
        user_id = uuid4()
        collection_id = uuid4()
        text_id = uuid4()

        mock_validate.return_value = MockUser(id=user_id)

        mock_db = MagicMock()
        mock_session.return_value.__enter__ = MagicMock(return_value=mock_db)
        mock_session.return_value.__exit__ = MagicMock(return_value=False)

        mock_collection = MockCollection(id=collection_id, user_id=user_id)
        mock_get_collection.return_value = mock_collection

        mock_max_order.return_value = 0

        saved_item = MockCollectionItem(
            recitation_collection_id=collection_id,
            text_id=text_id,
            display_order=1
        )
        mock_save_items.return_value = [saved_item]

        mock_get_texts.return_value = {
            str(text_id): MockTextDTO(title="Heart Sutra", language="bo", type="root_text")
        }

        request = AddItemsRequest(text_ids=[str(text_id)])
        result = await add_items_to_collection_service(
            token="valid_token",
            collection_id=collection_id,
            request=request
        )

        assert isinstance(result, AddItemsResponse)
        assert result.collection_id == collection_id
        assert result.added_count == 1
        assert len(result.items) == 1
        assert result.items[0].title == "Heart Sutra"
        assert result.items[0].display_order == 1

        mock_validate.assert_called_once_with(token="valid_token")
        mock_get_collection.assert_called_once_with(db=mock_db, collection_id=collection_id, user_id=user_id)

    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_service.validate_and_extract_user_details')
    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_service.SessionLocal')
    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_service.get_collection_by_id')
    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_service.get_max_display_order_for_collection')
    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_service.save_collection_items')
    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_service.get_texts_by_edition_or_text_ids')
    @pytest.mark.asyncio
    async def test_add_items_multiple_success(
        self,
        mock_get_texts,
        mock_save_items,
        mock_max_order,
        mock_get_collection,
        mock_session,
        mock_validate
    ):
        """Test successfully adding multiple items to collection"""
        user_id = uuid4()
        collection_id = uuid4()
        text_ids = [uuid4(), uuid4(), uuid4()]

        mock_validate.return_value = MockUser(id=user_id)

        mock_db = MagicMock()
        mock_session.return_value.__enter__ = MagicMock(return_value=mock_db)
        mock_session.return_value.__exit__ = MagicMock(return_value=False)

        mock_collection = MockCollection(id=collection_id, user_id=user_id)
        mock_get_collection.return_value = mock_collection

        mock_max_order.return_value = 0

        saved_items = [
            MockCollectionItem(recitation_collection_id=collection_id, text_id=text_ids[i], display_order=i+1)
            for i in range(3)
        ]
        mock_save_items.return_value = saved_items

        mock_get_texts.return_value = {
            str(text_ids[0]): MockTextDTO(title="Text 1", language="bo", type="root_text"),
            str(text_ids[1]): MockTextDTO(title="Text 2", language="en", type="translation"),
            str(text_ids[2]): MockTextDTO(title="Text 3", language="sa", type="commentary")
        }

        request = AddItemsRequest(text_ids=[str(t) for t in text_ids])
        result = await add_items_to_collection_service(
            token="valid_token",
            collection_id=collection_id,
            request=request
        )

        assert result.added_count == 3
        assert len(result.items) == 3
        assert result.items[0].display_order == 1
        assert result.items[2].display_order == 3

    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_service.validate_and_extract_user_details')
    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_service.SessionLocal')
    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_service.get_collection_by_id')
    @pytest.mark.asyncio
    async def test_add_items_collection_not_found(
        self,
        mock_get_collection,
        mock_session,
        mock_validate
    ):
        """Test adding items to non-existent collection"""
        user_id = uuid4()
        collection_id = uuid4()
        text_id = uuid4()

        mock_validate.return_value = MockUser(id=user_id)

        mock_db = MagicMock()
        mock_session.return_value.__enter__ = MagicMock(return_value=mock_db)
        mock_session.return_value.__exit__ = MagicMock(return_value=False)

        mock_get_collection.return_value = None

        request = AddItemsRequest(text_ids=[str(text_id)])

        with pytest.raises(HTTPException) as exc_info:
            await add_items_to_collection_service(
                token="valid_token",
                collection_id=collection_id,
                request=request
            )

        assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND

    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_service.validate_and_extract_user_details')
    @pytest.mark.asyncio
    async def test_add_items_invalid_token(self, mock_validate):
        """Test adding items with invalid token"""
        collection_id = uuid4()
        text_id = uuid4()

        mock_validate.side_effect = HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials"
        )

        request = AddItemsRequest(text_ids=[str(text_id)])

        with pytest.raises(HTTPException) as exc_info:
            await add_items_to_collection_service(
                token="invalid_token",
                collection_id=collection_id,
                request=request
            )

        assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED

    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_service.validate_and_extract_user_details')
    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_service.SessionLocal')
    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_service.get_collection_by_id')
    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_service.get_max_display_order_for_collection')
    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_service.save_collection_items')
    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_service.get_texts_by_edition_or_text_ids')
    @pytest.mark.asyncio
    async def test_add_items_display_order_continuation(
        self,
        mock_get_texts,
        mock_save_items,
        mock_max_order,
        mock_get_collection,
        mock_session,
        mock_validate
    ):
        """Test that display order continues from existing items"""
        user_id = uuid4()
        collection_id = uuid4()
        text_ids = [uuid4(), uuid4()]

        mock_validate.return_value = MockUser(id=user_id)

        mock_db = MagicMock()
        mock_session.return_value.__enter__ = MagicMock(return_value=mock_db)
        mock_session.return_value.__exit__ = MagicMock(return_value=False)

        mock_collection = MockCollection(id=collection_id, user_id=user_id)
        mock_get_collection.return_value = mock_collection

        mock_max_order.return_value = 10

        saved_items = [
            MockCollectionItem(recitation_collection_id=collection_id, text_id=text_ids[0], display_order=11),
            MockCollectionItem(recitation_collection_id=collection_id, text_id=text_ids[1], display_order=12)
        ]
        mock_save_items.return_value = saved_items

        mock_get_texts.return_value = {
            str(text_ids[0]): MockTextDTO(title="Text 1"),
            str(text_ids[1]): MockTextDTO(title="Text 2")
        }

        request = AddItemsRequest(text_ids=[str(t) for t in text_ids])
        result = await add_items_to_collection_service(
            token="valid_token",
            collection_id=collection_id,
            request=request
        )

        assert result.items[0].display_order == 11
        assert result.items[1].display_order == 12

    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_service.validate_and_extract_user_details')
    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_service.SessionLocal')
    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_service.get_collection_by_id')
    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_service.get_max_display_order_for_collection')
    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_service.save_collection_items')
    @pytest.mark.asyncio
    async def test_add_items_duplicate_error(
        self,
        mock_save_items,
        mock_max_order,
        mock_get_collection,
        mock_session,
        mock_validate
    ):
        """Test duplicate item error handling"""
        user_id = uuid4()
        collection_id = uuid4()
        text_id = uuid4()

        mock_validate.return_value = MockUser(id=user_id)

        mock_db = MagicMock()
        mock_session.return_value.__enter__ = MagicMock(return_value=mock_db)
        mock_session.return_value.__exit__ = MagicMock(return_value=False)

        mock_collection = MockCollection(id=collection_id, user_id=user_id)
        mock_get_collection.return_value = mock_collection

        mock_max_order.return_value = 5

        mock_save_items.side_effect = HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "BAD_REQUEST", "message": "duplicate key value violates unique constraint"}
        )

        request = AddItemsRequest(text_ids=[str(text_id)])

        with pytest.raises(HTTPException) as exc_info:
            await add_items_to_collection_service(
                token="valid_token",
                collection_id=collection_id,
                request=request
            )

        assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST


class TestDeleteCollectionService:

    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_service.validate_and_extract_user_details')
    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_service.SessionLocal')
    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_service.delete_collection')
    @pytest.mark.asyncio
    async def test_delete_collection_success(
        self,
        mock_delete_collection,
        mock_session,
        mock_validate
    ):
        """Test successful collection deletion"""
        user_id = uuid4()
        collection_id = uuid4()

        mock_validate.return_value = MockUser(id=user_id)

        mock_db = MagicMock()
        mock_session.return_value.__enter__ = MagicMock(return_value=mock_db)
        mock_session.return_value.__exit__ = MagicMock(return_value=False)

        deleted_collection = MockCollection(
            id=collection_id,
            user_id=user_id,
            name="Test Collection"
        )
        mock_delete_collection.return_value = deleted_collection

        result = await delete_collection_service(token="valid_token", collection_id=collection_id)

        assert result is None

        mock_validate.assert_called_once_with(token="valid_token")
        mock_delete_collection.assert_called_once_with(
            db=mock_db,
            collection_id=collection_id,
            user_id=user_id
        )

    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_service.validate_and_extract_user_details')
    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_service.SessionLocal')
    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_service.delete_collection')
    @pytest.mark.asyncio
    async def test_delete_collection_not_found(
        self,
        mock_delete_collection,
        mock_session,
        mock_validate
    ):
        """Test deleting non-existent collection"""
        user_id = uuid4()
        collection_id = uuid4()

        mock_validate.return_value = MockUser(id=user_id)

        mock_db = MagicMock()
        mock_session.return_value.__enter__ = MagicMock(return_value=mock_db)
        mock_session.return_value.__exit__ = MagicMock(return_value=False)

        mock_delete_collection.return_value = None

        with pytest.raises(HTTPException) as exc_info:
            await delete_collection_service(token="valid_token", collection_id=collection_id)

        assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND
        assert "not found" in str(exc_info.value.detail).lower()

    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_service.validate_and_extract_user_details')
    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_service.SessionLocal')
    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_service.delete_collection')
    @pytest.mark.asyncio
    async def test_delete_collection_wrong_owner(
        self,
        mock_delete_collection,
        mock_session,
        mock_validate
    ):
        """Test deleting collection owned by another user"""
        user_id = uuid4()
        collection_id = uuid4()

        mock_validate.return_value = MockUser(id=user_id)

        mock_db = MagicMock()
        mock_session.return_value.__enter__ = MagicMock(return_value=mock_db)
        mock_session.return_value.__exit__ = MagicMock(return_value=False)

        mock_delete_collection.return_value = None

        with pytest.raises(HTTPException) as exc_info:
            await delete_collection_service(token="valid_token", collection_id=collection_id)

        assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND

    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_service.validate_and_extract_user_details')
    @pytest.mark.asyncio
    async def test_delete_collection_invalid_token(self, mock_validate):
        """Test deleting collection with invalid token"""
        collection_id = uuid4()

        mock_validate.side_effect = HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials"
        )

        with pytest.raises(HTTPException) as exc_info:
            await delete_collection_service(token="invalid_token", collection_id=collection_id)

        assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED

    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_service.validate_and_extract_user_details')
    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_service.SessionLocal')
    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_service.delete_collection')
    @pytest.mark.asyncio
    async def test_delete_collection_database_error(
        self,
        mock_delete_collection,
        mock_session,
        mock_validate
    ):
        """Test database error during collection deletion"""
        user_id = uuid4()
        collection_id = uuid4()

        mock_validate.return_value = MockUser(id=user_id)

        mock_db = MagicMock()
        mock_session.return_value.__enter__ = MagicMock(return_value=mock_db)
        mock_session.return_value.__exit__ = MagicMock(return_value=False)

        mock_delete_collection.side_effect = HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "BAD_REQUEST", "message": "Database error"}
        )

        with pytest.raises(HTTPException) as exc_info:
            await delete_collection_service(token="valid_token", collection_id=collection_id)

        assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST

    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_service.validate_and_extract_user_details')
    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_service.SessionLocal')
    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_service.delete_collection')
    @pytest.mark.asyncio
    async def test_delete_collection_with_items(
        self,
        mock_delete_collection,
        mock_session,
        mock_validate
    ):
        """Test deleting collection that has items (cascade delete)"""
        user_id = uuid4()
        collection_id = uuid4()

        mock_validate.return_value = MockUser(id=user_id)

        mock_db = MagicMock()
        mock_session.return_value.__enter__ = MagicMock(return_value=mock_db)
        mock_session.return_value.__exit__ = MagicMock(return_value=False)

        deleted_collection = MockCollection(
            id=collection_id,
            user_id=user_id,
            name="Collection with Items"
        )
        mock_delete_collection.return_value = deleted_collection

        result = await delete_collection_service(token="valid_token", collection_id=collection_id)

        assert result is None
        mock_delete_collection.assert_called_once()


class TestDeleteCollectionItemService:

    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_service.validate_and_extract_user_details')
    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_service.SessionLocal')
    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_service.get_collection_by_id')
    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_service.get_collection_item_by_id')
    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_service.soft_delete_collection_item')
    @pytest.mark.asyncio
    async def test_delete_collection_item_success(
        self,
        mock_soft_delete_item,
        mock_get_item,
        mock_get_collection,
        mock_session,
        mock_validate
    ):
        """Test successful item deletion soft-deletes rather than removing the row"""
        user_id = uuid4()
        collection_id = uuid4()
        item_id = uuid4()

        mock_validate.return_value = MockUser(id=user_id)

        mock_db = MagicMock()
        mock_session.return_value.__enter__ = MagicMock(return_value=mock_db)
        mock_session.return_value.__exit__ = MagicMock(return_value=False)

        mock_get_collection.return_value = MockCollection(id=collection_id, user_id=user_id)
        item = MockCollectionItem(id=item_id, recitation_collection_id=collection_id)
        mock_get_item.return_value = item

        result = await delete_collection_item_service(
            token="valid_token",
            collection_id=collection_id,
            item_id=item_id
        )

        assert result is None

        mock_validate.assert_called_once_with(token="valid_token")
        mock_get_item.assert_called_once_with(
            db=mock_db,
            item_id=item_id,
            collection_id=collection_id
        )
        mock_soft_delete_item.assert_called_once_with(db=mock_db, item=item)

    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_service.validate_and_extract_user_details')
    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_service.SessionLocal')
    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_service.get_collection_by_id')
    @pytest.mark.asyncio
    async def test_delete_collection_item_collection_not_found(
        self,
        mock_get_collection,
        mock_session,
        mock_validate
    ):
        """Test deleting item from a non-existent collection"""
        user_id = uuid4()
        collection_id = uuid4()
        item_id = uuid4()

        mock_validate.return_value = MockUser(id=user_id)

        mock_db = MagicMock()
        mock_session.return_value.__enter__ = MagicMock(return_value=mock_db)
        mock_session.return_value.__exit__ = MagicMock(return_value=False)

        mock_get_collection.return_value = None

        with pytest.raises(HTTPException) as exc_info:
            await delete_collection_item_service(
                token="valid_token",
                collection_id=collection_id,
                item_id=item_id
            )

        assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND

    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_service.validate_and_extract_user_details')
    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_service.SessionLocal')
    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_service.get_collection_by_id')
    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_service.get_collection_item_by_id')
    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_service.soft_delete_collection_item')
    @pytest.mark.asyncio
    async def test_delete_collection_item_not_found(
        self,
        mock_soft_delete_item,
        mock_get_item,
        mock_get_collection,
        mock_session,
        mock_validate
    ):
        """Test deleting a non-existent (or already soft-deleted) item from an existing collection"""
        user_id = uuid4()
        collection_id = uuid4()
        item_id = uuid4()

        mock_validate.return_value = MockUser(id=user_id)

        mock_db = MagicMock()
        mock_session.return_value.__enter__ = MagicMock(return_value=mock_db)
        mock_session.return_value.__exit__ = MagicMock(return_value=False)

        mock_get_collection.return_value = MockCollection(id=collection_id, user_id=user_id)
        mock_get_item.return_value = None

        with pytest.raises(HTTPException) as exc_info:
            await delete_collection_item_service(
                token="valid_token",
                collection_id=collection_id,
                item_id=item_id
            )

        assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND
        assert "not found" in str(exc_info.value.detail).lower()
        mock_soft_delete_item.assert_not_called()

    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_service.validate_and_extract_user_details')
    @pytest.mark.asyncio
    async def test_delete_collection_item_invalid_token(self, mock_validate):
        """Test deleting item with invalid token"""
        collection_id = uuid4()
        item_id = uuid4()

        mock_validate.side_effect = HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials"
        )

        with pytest.raises(HTTPException) as exc_info:
            await delete_collection_item_service(
                token="invalid_token",
                collection_id=collection_id,
                item_id=item_id
            )

        assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED

    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_service.validate_and_extract_user_details')
    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_service.SessionLocal')
    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_service.get_collection_by_id')
    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_service.get_collection_item_by_id')
    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_service.soft_delete_collection_item')
    @pytest.mark.asyncio
    async def test_delete_collection_item_database_error(
        self,
        mock_soft_delete_item,
        mock_get_item,
        mock_get_collection,
        mock_session,
        mock_validate
    ):
        """Test database error during item deletion"""
        user_id = uuid4()
        collection_id = uuid4()
        item_id = uuid4()

        mock_validate.return_value = MockUser(id=user_id)

        mock_db = MagicMock()
        mock_session.return_value.__enter__ = MagicMock(return_value=mock_db)
        mock_session.return_value.__exit__ = MagicMock(return_value=False)

        mock_get_collection.return_value = MockCollection(id=collection_id, user_id=user_id)
        mock_get_item.return_value = MockCollectionItem(id=item_id, recitation_collection_id=collection_id)
        mock_soft_delete_item.side_effect = HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "BAD_REQUEST", "message": "Database error"}
        )

        with pytest.raises(HTTPException) as exc_info:
            await delete_collection_item_service(
                token="valid_token",
                collection_id=collection_id,
                item_id=item_id
            )

        assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST


class TestUpdateCollectionItemDisplayOrderService:

    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_service.validate_and_extract_user_details')
    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_service.SessionLocal')
    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_service.get_collection_by_id')
    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_service.get_collection_item_by_id')
    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_service.collection_item_display_order_taken')
    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_service.update_collection_item')
    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_service.get_texts_by_edition_or_text_ids')
    @pytest.mark.asyncio
    async def test_updates_fractional_display_order(
        self,
        mock_get_texts,
        mock_update_item,
        mock_order_taken,
        mock_get_item,
        mock_get_collection,
        mock_session,
        mock_validate
    ):
        user_id = uuid4()
        collection_id = uuid4()
        item_id = uuid4()
        text_id = uuid4()

        mock_validate.return_value = MockUser(id=user_id)
        mock_db = MagicMock()
        mock_session.return_value.__enter__ = MagicMock(return_value=mock_db)
        mock_session.return_value.__exit__ = MagicMock(return_value=False)
        mock_get_collection.return_value = MockCollection(id=collection_id, user_id=user_id)

        item = MockCollectionItem(
            id=item_id,
            recitation_collection_id=collection_id,
            text_id=text_id,
            display_order=2
        )
        mock_get_item.return_value = item
        mock_order_taken.return_value = False

        def _save(db, item):
            return item
        mock_update_item.side_effect = _save
        mock_get_texts.return_value = {
            str(text_id): MockTextDTO(title="Heart Sutra", language="bo")
        }

        result = await update_collection_item_display_order_service(
            token="valid_token",
            collection_id=collection_id,
            item_id=item_id,
            request=UpdateCollectionItemRequest(display_order=1.4),
        )

        assert result.id == item_id
        assert result.display_order == 1.4
        assert result.title == "Heart Sutra"
        mock_order_taken.assert_called_once_with(
            db=mock_db,
            collection_id=collection_id,
            display_order=1.4,
            exclude_item_id=item_id,
        )
        mock_update_item.assert_called_once()

    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_service.validate_and_extract_user_details')
    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_service.SessionLocal')
    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_service.get_collection_by_id')
    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_service.get_collection_item_by_id')
    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_service.collection_item_display_order_taken')
    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_service.update_collection_item')
    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_service.get_texts_by_edition_or_text_ids')
    @pytest.mark.asyncio
    async def test_same_display_order_is_noop(
        self,
        mock_get_texts,
        mock_update_item,
        mock_order_taken,
        mock_get_item,
        mock_get_collection,
        mock_session,
        mock_validate
    ):
        user_id = uuid4()
        collection_id = uuid4()
        text_id = uuid4()

        mock_validate.return_value = MockUser(id=user_id)
        mock_db = MagicMock()
        mock_session.return_value.__enter__ = MagicMock(return_value=mock_db)
        mock_session.return_value.__exit__ = MagicMock(return_value=False)
        mock_get_collection.return_value = MockCollection(id=collection_id, user_id=user_id)
        item = MockCollectionItem(
            recitation_collection_id=collection_id,
            text_id=text_id,
            display_order=1.4
        )
        mock_get_item.return_value = item
        mock_get_texts.return_value = {str(text_id): MockTextDTO(title="Heart Sutra")}

        result = await update_collection_item_display_order_service(
            token="valid_token",
            collection_id=collection_id,
            item_id=item.id,
            request=UpdateCollectionItemRequest(display_order=1.4),
        )

        assert result.display_order == 1.4
        mock_order_taken.assert_not_called()
        mock_update_item.assert_not_called()

    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_service.validate_and_extract_user_details')
    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_service.SessionLocal')
    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_service.get_collection_by_id')
    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_service.get_collection_item_by_id')
    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_service.collection_item_display_order_taken')
    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_service.update_collection_item')
    @pytest.mark.asyncio
    async def test_rejects_duplicate_display_order(
        self,
        mock_update_item,
        mock_order_taken,
        mock_get_item,
        mock_get_collection,
        mock_session,
        mock_validate
    ):
        user_id = uuid4()
        collection_id = uuid4()

        mock_validate.return_value = MockUser(id=user_id)
        mock_db = MagicMock()
        mock_session.return_value.__enter__ = MagicMock(return_value=mock_db)
        mock_session.return_value.__exit__ = MagicMock(return_value=False)
        mock_get_collection.return_value = MockCollection(id=collection_id, user_id=user_id)
        mock_get_item.return_value = MockCollectionItem(
            recitation_collection_id=collection_id,
            display_order=2
        )
        mock_order_taken.return_value = True

        with pytest.raises(HTTPException) as exc_info:
            await update_collection_item_display_order_service(
                token="valid_token",
                collection_id=collection_id,
                item_id=uuid4(),
                request=UpdateCollectionItemRequest(display_order=1.0),
            )

        assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST
        mock_update_item.assert_not_called()

    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_service.validate_and_extract_user_details')
    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_service.SessionLocal')
    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_service.get_collection_by_id')
    @pytest.mark.asyncio
    async def test_collection_not_found(
        self,
        mock_get_collection,
        mock_session,
        mock_validate
    ):
        mock_validate.return_value = MockUser()
        mock_db = MagicMock()
        mock_session.return_value.__enter__ = MagicMock(return_value=mock_db)
        mock_session.return_value.__exit__ = MagicMock(return_value=False)
        mock_get_collection.return_value = None

        with pytest.raises(HTTPException) as exc_info:
            await update_collection_item_display_order_service(
                token="valid_token",
                collection_id=uuid4(),
                item_id=uuid4(),
                request=UpdateCollectionItemRequest(display_order=1.4),
            )

        assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND

    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_service.validate_and_extract_user_details')
    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_service.SessionLocal')
    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_service.get_collection_by_id')
    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_service.get_collection_item_by_id')
    @pytest.mark.asyncio
    async def test_item_not_found(
        self,
        mock_get_item,
        mock_get_collection,
        mock_session,
        mock_validate
    ):
        user_id = uuid4()
        collection_id = uuid4()
        mock_validate.return_value = MockUser(id=user_id)
        mock_db = MagicMock()
        mock_session.return_value.__enter__ = MagicMock(return_value=mock_db)
        mock_session.return_value.__exit__ = MagicMock(return_value=False)
        mock_get_collection.return_value = MockCollection(id=collection_id, user_id=user_id)
        mock_get_item.return_value = None

        with pytest.raises(HTTPException) as exc_info:
            await update_collection_item_display_order_service(
                token="valid_token",
                collection_id=collection_id,
                item_id=uuid4(),
                request=UpdateCollectionItemRequest(display_order=1.4),
            )

        assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND

    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_service.validate_and_extract_user_details')
    @pytest.mark.asyncio
    async def test_invalid_token(self, mock_validate):
        mock_validate.side_effect = HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials"
        )

        with pytest.raises(HTTPException) as exc_info:
            await update_collection_item_display_order_service(
                token="invalid_token",
                collection_id=uuid4(),
                item_id=uuid4(),
                request=UpdateCollectionItemRequest(display_order=1.4),
            )

        assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED

    def test_request_rejects_non_finite_display_order(self):
        with pytest.raises(ValidationError):
            UpdateCollectionItemRequest(display_order=float("inf"))
        with pytest.raises(ValidationError):
            UpdateCollectionItemRequest(display_order=float("nan"))

    def test_request_rejects_extra_fields(self):
        with pytest.raises(ValidationError):
            UpdateCollectionItemRequest(display_order=1.4, name="nope")
