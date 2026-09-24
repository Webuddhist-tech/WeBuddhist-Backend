import pytest
from unittest.mock import patch, MagicMock
from uuid import uuid4
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from starlette import status

from pecha_api.plans.users.recitation_collection.recitation_collection_views import (
    get_user_collections,
    get_collection_detail,
    create_collection,
    update_collection,
    upload_collection_image,
    add_items_to_collection,
    delete_collection,
    delete_collection_item,
    update_collection_item_display_order
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


class TestDataFactory:

    @staticmethod
    def create_auth_credentials(token="valid_token") -> HTTPAuthorizationCredentials:
        return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)

    @staticmethod
    def create_collection_dto(
        id=None,
        name="Test Collection",
        img_url="https://example.com/image.jpg",
        item_count=5,
        created_at="2025-06-09T10:00:00",
        updated_at="2025-06-09T10:00:00"
    ) -> RecitationCollectionDTO:
        return RecitationCollectionDTO(
            id=id or uuid4(),
            name=name,
            img_url=img_url,
            item_count=item_count,
            created_at=created_at,
            updated_at=updated_at
        )

    @staticmethod
    def create_collection_item_dto(
        id=None,
        text_id=None,
        title="Test Text",
        language="bo",
        type="root_text",
        display_order=1
    ) -> RecitationCollectionItemDTO:
        return RecitationCollectionItemDTO(
            id=id or uuid4(),
            text_id=str(text_id or uuid4()),
            title=title,
            language=language,
            type=type,
            display_order=display_order
        )

    @staticmethod
    def create_collection_detail_dto(
        id=None,
        name="Test Collection",
        img_url="https://example.com/image.jpg",
        created_at="2025-06-09T10:00:00",
        updated_at="2025-06-09T10:00:00",
        items=None
    ) -> RecitationCollectionDetailDTO:
        return RecitationCollectionDetailDTO(
            id=id or uuid4(),
            name=name,
            img_url=img_url,
            created_at=created_at,
            updated_at=updated_at,
            items=items or []
        )

    @staticmethod
    def create_collections_response(
        collections=None,
        skip=0,
        limit=20,
        total=0
    ) -> RecitationCollectionsResponse:
        return RecitationCollectionsResponse(
            collections=collections or [],
            skip=skip,
            limit=limit,
            total=total
        )


class TestGetUserCollectionsView:

    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_views.get_user_collections_service')
    @pytest.mark.asyncio
    async def test_get_user_collections_success(self, mock_service):
        token = "valid_token"
        collection_id_1 = uuid4()
        collection_id_2 = uuid4()

        auth_credentials = TestDataFactory.create_auth_credentials(token=token)

        collections = [
            TestDataFactory.create_collection_dto(id=collection_id_1, name="Morning Prayers", item_count=5),
            TestDataFactory.create_collection_dto(id=collection_id_2, name="Evening Prayers", item_count=3)
        ]
        mock_response = TestDataFactory.create_collections_response(collections=collections, total=2)
        mock_service.return_value = mock_response

        result = await get_user_collections(
            authentication_credential=auth_credentials,
            skip=0,
            limit=20
        )

        assert isinstance(result, RecitationCollectionsResponse)
        assert len(result.collections) == 2
        assert result.collections[0].name == "Morning Prayers"
        assert result.collections[0].item_count == 5
        assert result.collections[1].name == "Evening Prayers"
        assert result.total == 2

        mock_service.assert_awaited_once_with(token=token, skip=0, limit=20)

    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_views.get_user_collections_service')
    @pytest.mark.asyncio
    async def test_get_user_collections_empty_list(self, mock_service):
        token = "valid_token"
        auth_credentials = TestDataFactory.create_auth_credentials(token=token)

        mock_response = TestDataFactory.create_collections_response(collections=[], total=0)
        mock_service.return_value = mock_response

        result = await get_user_collections(
            authentication_credential=auth_credentials,
            skip=0,
            limit=20
        )

        assert isinstance(result, RecitationCollectionsResponse)
        assert len(result.collections) == 0
        assert result.total == 0

        mock_service.assert_awaited_once_with(token=token, skip=0, limit=20)

    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_views.get_user_collections_service')
    @pytest.mark.asyncio
    async def test_get_user_collections_with_pagination(self, mock_service):
        token = "valid_token"
        auth_credentials = TestDataFactory.create_auth_credentials(token=token)

        collections = [TestDataFactory.create_collection_dto(name=f"Collection {i}") for i in range(5)]
        mock_response = TestDataFactory.create_collections_response(
            collections=collections,
            skip=10,
            limit=5,
            total=25
        )
        mock_service.return_value = mock_response

        result = await get_user_collections(
            authentication_credential=auth_credentials,
            skip=10,
            limit=5
        )

        assert len(result.collections) == 5
        assert result.skip == 10
        assert result.limit == 5
        assert result.total == 25

        mock_service.assert_awaited_once_with(token=token, skip=10, limit=5)

    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_views.get_user_collections_service')
    @pytest.mark.asyncio
    async def test_get_user_collections_invalid_token(self, mock_service):
        token = "invalid_token"
        auth_credentials = TestDataFactory.create_auth_credentials(token=token)

        mock_service.side_effect = HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials"
        )

        with pytest.raises(HTTPException) as exc_info:
            await get_user_collections(
                authentication_credential=auth_credentials,
                skip=0,
                limit=20
            )

        assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED

    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_views.get_user_collections_service')
    @pytest.mark.asyncio
    async def test_get_user_collections_database_error(self, mock_service):
        token = "valid_token"
        auth_credentials = TestDataFactory.create_auth_credentials(token=token)

        mock_service.side_effect = HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Database connection error"
        )

        with pytest.raises(HTTPException) as exc_info:
            await get_user_collections(
                authentication_credential=auth_credentials,
                skip=0,
                limit=20
            )

        assert exc_info.value.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR


class TestGetCollectionDetailView:

    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_views.get_collection_detail_service')
    @pytest.mark.asyncio
    async def test_get_collection_detail_success(self, mock_service):
        token = "valid_token"
        collection_id = uuid4()
        text_id_1 = uuid4()
        text_id_2 = uuid4()

        auth_credentials = TestDataFactory.create_auth_credentials(token=token)

        items = [
            TestDataFactory.create_collection_item_dto(
                text_id=text_id_1,
                title="Heart Sutra",
                language="bo",
                type="root_text",
                display_order=1
            ),
            TestDataFactory.create_collection_item_dto(
                text_id=text_id_2,
                title="Diamond Sutra",
                language="en",
                type="translation",
                display_order=2
            )
        ]
        mock_response = TestDataFactory.create_collection_detail_dto(
            id=collection_id,
            name="Morning Prayers",
            items=items
        )
        mock_service.return_value = mock_response

        result = await get_collection_detail(
            collection_id=collection_id,
            authentication_credential=auth_credentials
        )

        assert isinstance(result, RecitationCollectionDetailDTO)
        assert result.id == collection_id
        assert result.name == "Morning Prayers"
        assert len(result.items) == 2
        assert result.items[0].title == "Heart Sutra"
        assert result.items[0].language == "bo"
        assert result.items[1].title == "Diamond Sutra"

        mock_service.assert_awaited_once_with(token=token, collection_id=collection_id)

    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_views.get_collection_detail_service')
    @pytest.mark.asyncio
    async def test_get_collection_detail_empty_items(self, mock_service):
        token = "valid_token"
        collection_id = uuid4()

        auth_credentials = TestDataFactory.create_auth_credentials(token=token)

        mock_response = TestDataFactory.create_collection_detail_dto(
            id=collection_id,
            name="Empty Collection",
            items=[]
        )
        mock_service.return_value = mock_response

        result = await get_collection_detail(
            collection_id=collection_id,
            authentication_credential=auth_credentials
        )

        assert isinstance(result, RecitationCollectionDetailDTO)
        assert result.name == "Empty Collection"
        assert len(result.items) == 0

        mock_service.assert_awaited_once_with(token=token, collection_id=collection_id)

    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_views.get_collection_detail_service')
    @pytest.mark.asyncio
    async def test_get_collection_detail_not_found(self, mock_service):
        token = "valid_token"
        collection_id = uuid4()

        auth_credentials = TestDataFactory.create_auth_credentials(token=token)

        mock_service.side_effect = HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "NOT_FOUND", "message": f"Collection with ID {collection_id} not found"}
        )

        with pytest.raises(HTTPException) as exc_info:
            await get_collection_detail(
                collection_id=collection_id,
                authentication_credential=auth_credentials
            )

        assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND
        assert exc_info.value.detail["error"] == "NOT_FOUND"

        mock_service.assert_awaited_once_with(token=token, collection_id=collection_id)

    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_views.get_collection_detail_service')
    @pytest.mark.asyncio
    async def test_get_collection_detail_invalid_token(self, mock_service):
        token = "invalid_token"
        collection_id = uuid4()

        auth_credentials = TestDataFactory.create_auth_credentials(token=token)

        mock_service.side_effect = HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials"
        )

        with pytest.raises(HTTPException) as exc_info:
            await get_collection_detail(
                collection_id=collection_id,
                authentication_credential=auth_credentials
            )

        assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED

    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_views.get_collection_detail_service')
    @pytest.mark.asyncio
    async def test_get_collection_detail_with_many_items(self, mock_service):
        token = "valid_token"
        collection_id = uuid4()

        auth_credentials = TestDataFactory.create_auth_credentials(token=token)

        items = [
            TestDataFactory.create_collection_item_dto(
                title=f"Text {i}",
                display_order=i
            )
            for i in range(1, 21)
        ]
        mock_response = TestDataFactory.create_collection_detail_dto(
            id=collection_id,
            name="Large Collection",
            items=items
        )
        mock_service.return_value = mock_response

        result = await get_collection_detail(
            collection_id=collection_id,
            authentication_credential=auth_credentials
        )

        assert len(result.items) == 20
        assert result.items[0].display_order == 1
        assert result.items[19].display_order == 20


class TestCreateCollectionView:

    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_views.create_collection_service')
    @pytest.mark.asyncio
    async def test_create_collection_success(self, mock_service):
        token = "valid_token"
        collection_id = uuid4()

        auth_credentials = TestDataFactory.create_auth_credentials(token=token)
        request = CreateCollectionRequest(name="Morning Prayers", img_url="images/morning.jpg")

        mock_response = CreateCollectionResponse(
            id=collection_id,
            name="Morning Prayers",
            img_url="https://presigned-url.com/morning.jpg",
            created_at="2025-06-09T10:00:00",
            updated_at="2025-06-09T10:00:00"
        )
        mock_service.return_value = mock_response

        result = await create_collection(
            authentication_credential=auth_credentials,
            request=request
        )

        assert isinstance(result, CreateCollectionResponse)
        assert result.id == collection_id
        assert result.name == "Morning Prayers"
        assert result.img_url == "https://presigned-url.com/morning.jpg"

        mock_service.assert_awaited_once_with(token=token, request=request)

    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_views.create_collection_service')
    @pytest.mark.asyncio
    async def test_create_collection_invalid_token(self, mock_service):
        token = "invalid_token"

        auth_credentials = TestDataFactory.create_auth_credentials(token=token)
        request = CreateCollectionRequest(name="Test Collection", img_url="images/test.jpg")

        mock_service.side_effect = HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials"
        )

        with pytest.raises(HTTPException) as exc_info:
            await create_collection(
                authentication_credential=auth_credentials,
                request=request
            )

        assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED

    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_views.create_collection_service')
    @pytest.mark.asyncio
    async def test_create_collection_database_error(self, mock_service):
        token = "valid_token"

        auth_credentials = TestDataFactory.create_auth_credentials(token=token)
        request = CreateCollectionRequest(name="Test Collection", img_url="images/test.jpg")

        mock_service.side_effect = HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "BAD_REQUEST", "message": "Database error"}
        )

        with pytest.raises(HTTPException) as exc_info:
            await create_collection(
                authentication_credential=auth_credentials,
                request=request
            )

        assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST

    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_views.create_collection_service')
    @pytest.mark.asyncio
    async def test_create_collection_without_image(self, mock_service):
        """Test creating collection without image URL (empty string)"""
        token = "valid_token"
        collection_id = uuid4()

        auth_credentials = TestDataFactory.create_auth_credentials(token=token)
        request = CreateCollectionRequest(name="No Image Collection", img_url="")

        mock_response = CreateCollectionResponse(
            id=collection_id,
            name="No Image Collection",
            img_url=None,
            created_at="2025-06-09T10:00:00",
            updated_at="2025-06-09T10:00:00"
        )
        mock_service.return_value = mock_response

        result = await create_collection(
            authentication_credential=auth_credentials,
            request=request
        )

        assert result.img_url is None
        assert result.name == "No Image Collection"
        mock_service.assert_awaited_once_with(token=token, request=request)

    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_views.create_collection_service')
    @pytest.mark.asyncio
    async def test_create_collection_with_long_name(self, mock_service):
        """Test creating collection with long name"""
        token = "valid_token"
        collection_id = uuid4()
        long_name = "A" * 255

        auth_credentials = TestDataFactory.create_auth_credentials(token=token)
        request = CreateCollectionRequest(name=long_name, img_url="images/test.jpg")

        mock_response = CreateCollectionResponse(
            id=collection_id,
            name=long_name,
            img_url="https://presigned-url.com/test.jpg",
            created_at="2025-06-09T10:00:00",
            updated_at="2025-06-09T10:00:00"
        )
        mock_service.return_value = mock_response

        result = await create_collection(
            authentication_credential=auth_credentials,
            request=request
        )

        assert result.name == long_name
        assert len(result.name) == 255
        mock_service.assert_awaited_once_with(token=token, request=request)

    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_views.create_collection_service')
    @pytest.mark.asyncio
    async def test_create_collection_with_special_characters(self, mock_service):
        """Test creating collection with special characters in name"""
        token = "valid_token"
        collection_id = uuid4()
        special_name = "Morning Prayers 🙏 - དུས་གསུམ་སངས་རྒྱས།"

        auth_credentials = TestDataFactory.create_auth_credentials(token=token)
        request = CreateCollectionRequest(name=special_name, img_url="images/test.jpg")

        mock_response = CreateCollectionResponse(
            id=collection_id,
            name=special_name,
            img_url="https://presigned-url.com/test.jpg",
            created_at="2025-06-09T10:00:00",
            updated_at="2025-06-09T10:00:00"
        )
        mock_service.return_value = mock_response

        result = await create_collection(
            authentication_credential=auth_credentials,
            request=request
        )

        assert result.name == special_name
        mock_service.assert_awaited_once_with(token=token, request=request)

    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_views.create_collection_service')
    @pytest.mark.asyncio
    async def test_create_collection_presigned_url_generation(self, mock_service):
        """Test that presigned URL is generated for S3 key"""
        token = "valid_token"
        collection_id = uuid4()
        s3_key = "images/collections/user123/collection.jpg"
        presigned_url = "https://bucket.s3.amazonaws.com/images/collections/user123/collection.jpg?X-Amz-Algorithm=..."

        auth_credentials = TestDataFactory.create_auth_credentials(token=token)
        request = CreateCollectionRequest(name="Test Collection", img_url=s3_key)

        mock_response = CreateCollectionResponse(
            id=collection_id,
            name="Test Collection",
            img_url=presigned_url,
            created_at="2025-06-09T10:00:00",
            updated_at="2025-06-09T10:00:00"
        )
        mock_service.return_value = mock_response

        result = await create_collection(
            authentication_credential=auth_credentials,
            request=request
        )

        assert result.img_url == presigned_url
        assert "X-Amz-Algorithm" in result.img_url
        mock_service.assert_awaited_once_with(token=token, request=request)


class TestUpdateCollectionView:

    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_views.update_collection_service')
    @pytest.mark.asyncio
    async def test_update_collection_success(self, mock_service):
        token = "valid_token"
        collection_id = uuid4()

        auth_credentials = TestDataFactory.create_auth_credentials(token=token)
        request = UpdateCollectionRequest(name="Updated Name", img_url="images/updated.jpg")

        mock_response = CreateCollectionResponse(
            id=collection_id,
            name="Updated Name",
            img_url="https://presigned-url.com/updated.jpg",
            created_at="2025-06-09T10:00:00",
            updated_at="2025-06-09T11:00:00"
        )
        mock_service.return_value = mock_response

        result = await update_collection(
            collection_id=collection_id,
            authentication_credential=auth_credentials,
            request=request
        )

        assert isinstance(result, CreateCollectionResponse)
        assert result.name == "Updated Name"
        assert result.img_url == "https://presigned-url.com/updated.jpg"

        mock_service.assert_awaited_once_with(
            token=token,
            collection_id=collection_id,
            request=request
        )

    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_views.update_collection_service')
    @pytest.mark.asyncio
    async def test_update_collection_not_found(self, mock_service):
        token = "valid_token"
        collection_id = uuid4()

        auth_credentials = TestDataFactory.create_auth_credentials(token=token)
        request = UpdateCollectionRequest(name="Updated Name")

        mock_service.side_effect = HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "NOT_FOUND", "message": f"Collection with ID {collection_id} not found"}
        )

        with pytest.raises(HTTPException) as exc_info:
            await update_collection(
                collection_id=collection_id,
                authentication_credential=auth_credentials,
                request=request
            )

        assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND

    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_views.update_collection_service')
    @pytest.mark.asyncio
    async def test_update_collection_invalid_token(self, mock_service):
        token = "invalid_token"
        collection_id = uuid4()

        auth_credentials = TestDataFactory.create_auth_credentials(token=token)
        request = UpdateCollectionRequest(name="Updated Name")

        mock_service.side_effect = HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials"
        )

        with pytest.raises(HTTPException) as exc_info:
            await update_collection(
                collection_id=collection_id,
                authentication_credential=auth_credentials,
                request=request
            )

        assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED


class TestUploadCollectionImageView:

    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_views.upload_collection_image_service')
    @pytest.mark.asyncio
    async def test_upload_success(self, mock_service):
        token = "valid_token"
        auth_credentials = TestDataFactory.create_auth_credentials(token=token)

        mock_response = PlanUploadResponse(
            image=ImageUrlModel(
                thumbnail="https://signed/thumb",
                medium="https://signed/medium",
                original="https://signed/original",
            ),
            key="images/recitation_collection_images/abc",
            path="images/recitation_collection_images",
        )
        mock_service.return_value = mock_response

        result = await upload_collection_image(
            authentication_credential=auth_credentials,
            file=MagicMock(),
        )

        assert isinstance(result, PlanUploadResponse)
        assert result.key == "images/recitation_collection_images/abc"
        assert result.image.thumbnail == "https://signed/thumb"
        mock_service.assert_called_once()

    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_views.upload_collection_image_service')
    @pytest.mark.asyncio
    async def test_upload_invalid_token(self, mock_service):
        token = "invalid_token"
        auth_credentials = TestDataFactory.create_auth_credentials(token=token)

        mock_service.side_effect = HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials"
        )

        with pytest.raises(HTTPException) as exc_info:
            await upload_collection_image(
                authentication_credential=auth_credentials,
                file=MagicMock(),
            )

        assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED


class TestAddItemsToCollectionView:

    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_views.add_items_to_collection_service')
    @pytest.mark.asyncio
    async def test_add_items_single_success(self, mock_service):
        token = "valid_token"
        collection_id = uuid4()
        text_id = str(uuid4())

        auth_credentials = TestDataFactory.create_auth_credentials(token=token)
        request = AddItemsRequest(text_ids=[text_id])

        item_dto = TestDataFactory.create_collection_item_dto(
            text_id=text_id,
            title="Heart Sutra",
            display_order=1
        )
        mock_response = AddItemsResponse(
            collection_id=collection_id,
            added_count=1,
            items=[item_dto]
        )
        mock_service.return_value = mock_response

        result = await add_items_to_collection(
            collection_id=collection_id,
            authentication_credential=auth_credentials,
            request=request
        )

        assert isinstance(result, AddItemsResponse)
        assert result.collection_id == collection_id
        assert result.added_count == 1
        assert len(result.items) == 1
        assert result.items[0].title == "Heart Sutra"

        mock_service.assert_awaited_once_with(
            token=token,
            collection_id=collection_id,
            request=request
        )

    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_views.add_items_to_collection_service')
    @pytest.mark.asyncio
    async def test_add_items_multiple_success(self, mock_service):
        token = "valid_token"
        collection_id = uuid4()
        text_ids = [str(uuid4()), str(uuid4()), str(uuid4())]

        auth_credentials = TestDataFactory.create_auth_credentials(token=token)
        request = AddItemsRequest(text_ids=text_ids)

        items_dto = [
            TestDataFactory.create_collection_item_dto(
                text_id=text_ids[i],
                title=f"Text {i+1}",
                display_order=i+1
            )
            for i in range(3)
        ]
        mock_response = AddItemsResponse(
            collection_id=collection_id,
            added_count=3,
            items=items_dto
        )
        mock_service.return_value = mock_response

        result = await add_items_to_collection(
            collection_id=collection_id,
            authentication_credential=auth_credentials,
            request=request
        )

        assert result.added_count == 3
        assert len(result.items) == 3

        mock_service.assert_awaited_once_with(
            token=token,
            collection_id=collection_id,
            request=request
        )

    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_views.add_items_to_collection_service')
    @pytest.mark.asyncio
    async def test_add_items_collection_not_found(self, mock_service):
        token = "valid_token"
        collection_id = uuid4()
        text_id = str(uuid4())

        auth_credentials = TestDataFactory.create_auth_credentials(token=token)
        request = AddItemsRequest(text_ids=[text_id])

        mock_service.side_effect = HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "NOT_FOUND", "message": f"Collection with ID {collection_id} not found"}
        )

        with pytest.raises(HTTPException) as exc_info:
            await add_items_to_collection(
                collection_id=collection_id,
                authentication_credential=auth_credentials,
                request=request
            )

        assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND

    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_views.add_items_to_collection_service')
    @pytest.mark.asyncio
    async def test_add_items_text_not_found(self, mock_service):
        token = "valid_token"
        collection_id = uuid4()
        text_id = str(uuid4())

        auth_credentials = TestDataFactory.create_auth_credentials(token=token)
        request = AddItemsRequest(text_ids=[text_id])

        mock_service.side_effect = HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "NOT_FOUND", "message": f"Text with ID {text_id} not found"}
        )

        with pytest.raises(HTTPException) as exc_info:
            await add_items_to_collection(
                collection_id=collection_id,
                authentication_credential=auth_credentials,
                request=request
            )

        assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND

    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_views.add_items_to_collection_service')
    @pytest.mark.asyncio
    async def test_add_items_duplicate_item(self, mock_service):
        token = "valid_token"
        collection_id = uuid4()
        text_id = str(uuid4())

        auth_credentials = TestDataFactory.create_auth_credentials(token=token)
        request = AddItemsRequest(text_ids=[text_id])

        mock_service.side_effect = HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "BAD_REQUEST", "message": "duplicate key value violates unique constraint"}
        )

        with pytest.raises(HTTPException) as exc_info:
            await add_items_to_collection(
                collection_id=collection_id,
                authentication_credential=auth_credentials,
                request=request
            )

        assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST

    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_views.add_items_to_collection_service')
    @pytest.mark.asyncio
    async def test_add_items_invalid_token(self, mock_service):
        """Test adding items with invalid authentication token"""
        token = "invalid_token"
        collection_id = uuid4()
        text_id = str(uuid4())

        auth_credentials = TestDataFactory.create_auth_credentials(token=token)
        request = AddItemsRequest(text_ids=[text_id])

        mock_service.side_effect = HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials"
        )

        with pytest.raises(HTTPException) as exc_info:
            await add_items_to_collection(
                collection_id=collection_id,
                authentication_credential=auth_credentials,
                request=request
            )

        assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED

    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_views.add_items_to_collection_service')
    @pytest.mark.asyncio
    async def test_add_items_large_batch(self, mock_service):
        """Test adding large batch of items (50 texts)"""
        token = "valid_token"
        collection_id = uuid4()
        text_ids = [str(uuid4()) for _ in range(50)]

        auth_credentials = TestDataFactory.create_auth_credentials(token=token)
        request = AddItemsRequest(text_ids=text_ids)

        items_dto = [
            TestDataFactory.create_collection_item_dto(
                text_id=text_ids[i],
                title=f"Text {i+1}",
                display_order=i+1
            )
            for i in range(50)
        ]
        mock_response = AddItemsResponse(
            collection_id=collection_id,
            added_count=50,
            items=items_dto
        )
        mock_service.return_value = mock_response

        result = await add_items_to_collection(
            collection_id=collection_id,
            authentication_credential=auth_credentials,
            request=request
        )

        assert result.added_count == 50
        assert len(result.items) == 50
        assert result.items[0].display_order == 1
        assert result.items[49].display_order == 50

        mock_service.assert_awaited_once_with(
            token=token,
            collection_id=collection_id,
            request=request
        )

    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_views.add_items_to_collection_service')
    @pytest.mark.asyncio
    async def test_add_items_display_order_continuation(self, mock_service):
        """Test that display order continues from existing items"""
        token = "valid_token"
        collection_id = uuid4()
        text_ids = [str(uuid4()), str(uuid4())]

        auth_credentials = TestDataFactory.create_auth_credentials(token=token)
        request = AddItemsRequest(text_ids=text_ids)

        items_dto = [
            TestDataFactory.create_collection_item_dto(
                text_id=text_ids[0],
                title="Text 1",
                display_order=11
            ),
            TestDataFactory.create_collection_item_dto(
                text_id=text_ids[1],
                title="Text 2",
                display_order=12
            )
        ]
        mock_response = AddItemsResponse(
            collection_id=collection_id,
            added_count=2,
            items=items_dto
        )
        mock_service.return_value = mock_response

        result = await add_items_to_collection(
            collection_id=collection_id,
            authentication_credential=auth_credentials,
            request=request
        )

        assert result.items[0].display_order == 11
        assert result.items[1].display_order == 12

        mock_service.assert_awaited_once_with(
            token=token,
            collection_id=collection_id,
            request=request
        )

    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_views.add_items_to_collection_service')
    @pytest.mark.asyncio
    async def test_add_items_with_different_text_types(self, mock_service):
        """Test adding items with different text types (root_text, translation, etc.)"""
        token = "valid_token"
        collection_id = uuid4()
        text_ids = [str(uuid4()), str(uuid4()), str(uuid4())]

        auth_credentials = TestDataFactory.create_auth_credentials(token=token)
        request = AddItemsRequest(text_ids=text_ids)

        items_dto = [
            TestDataFactory.create_collection_item_dto(
                text_id=text_ids[0],
                title="Root Text",
                type="root_text",
                display_order=1
            ),
            TestDataFactory.create_collection_item_dto(
                text_id=text_ids[1],
                title="Translation",
                type="translation",
                display_order=2
            ),
            TestDataFactory.create_collection_item_dto(
                text_id=text_ids[2],
                title="Commentary",
                type="commentary",
                display_order=3
            )
        ]
        mock_response = AddItemsResponse(
            collection_id=collection_id,
            added_count=3,
            items=items_dto
        )
        mock_service.return_value = mock_response

        result = await add_items_to_collection(
            collection_id=collection_id,
            authentication_credential=auth_credentials,
            request=request
        )

        assert result.items[0].type == "root_text"
        assert result.items[1].type == "translation"
        assert result.items[2].type == "commentary"

        mock_service.assert_awaited_once_with(
            token=token,
            collection_id=collection_id,
            request=request
        )

    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_views.add_items_to_collection_service')
    @pytest.mark.asyncio
    async def test_add_items_with_different_languages(self, mock_service):
        """Test adding items with different languages"""
        token = "valid_token"
        collection_id = uuid4()
        text_ids = [str(uuid4()), str(uuid4()), str(uuid4())]

        auth_credentials = TestDataFactory.create_auth_credentials(token=token)
        request = AddItemsRequest(text_ids=text_ids)

        items_dto = [
            TestDataFactory.create_collection_item_dto(
                text_id=text_ids[0],
                title="Tibetan Text",
                language="bo",
                display_order=1
            ),
            TestDataFactory.create_collection_item_dto(
                text_id=text_ids[1],
                title="English Text",
                language="en",
                display_order=2
            ),
            TestDataFactory.create_collection_item_dto(
                text_id=text_ids[2],
                title="Sanskrit Text",
                language="sa",
                display_order=3
            )
        ]
        mock_response = AddItemsResponse(
            collection_id=collection_id,
            added_count=3,
            items=items_dto
        )
        mock_service.return_value = mock_response

        result = await add_items_to_collection(
            collection_id=collection_id,
            authentication_credential=auth_credentials,
            request=request
        )

        assert result.items[0].language == "bo"
        assert result.items[1].language == "en"
        assert result.items[2].language == "sa"

        mock_service.assert_awaited_once_with(
            token=token,
            collection_id=collection_id,
            request=request
        )

    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_views.add_items_to_collection_service')
    @pytest.mark.asyncio
    async def test_add_items_database_error(self, mock_service):
        """Test database error handling when adding items"""
        token = "valid_token"
        collection_id = uuid4()
        text_id = str(uuid4())

        auth_credentials = TestDataFactory.create_auth_credentials(token=token)
        request = AddItemsRequest(text_ids=[text_id])

        mock_service.side_effect = HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Database connection error"
        )

        with pytest.raises(HTTPException) as exc_info:
            await add_items_to_collection(
                collection_id=collection_id,
                authentication_credential=auth_credentials,
                request=request
            )

        assert exc_info.value.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR


class TestDeleteCollectionView:

    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_views.delete_collection_service')
    @pytest.mark.asyncio
    async def test_delete_collection_success(self, mock_service):
        """Test successful collection deletion"""
        token = "valid_token"
        collection_id = uuid4()

        auth_credentials = TestDataFactory.create_auth_credentials(token=token)
        mock_service.return_value = None

        result = await delete_collection(
            collection_id=collection_id,
            authentication_credential=auth_credentials
        )

        assert result is None

        mock_service.assert_awaited_once_with(
            token=token,
            collection_id=collection_id
        )

    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_views.delete_collection_service')
    @pytest.mark.asyncio
    async def test_delete_collection_not_found(self, mock_service):
        """Test deleting non-existent collection"""
        token = "valid_token"
        collection_id = uuid4()

        auth_credentials = TestDataFactory.create_auth_credentials(token=token)

        mock_service.side_effect = HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "NOT_FOUND", "message": f"Collection with ID {collection_id} not found"}
        )

        with pytest.raises(HTTPException) as exc_info:
            await delete_collection(
                collection_id=collection_id,
                authentication_credential=auth_credentials
            )

        assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND
        assert exc_info.value.detail["error"] == "NOT_FOUND"

        mock_service.assert_awaited_once_with(
            token=token,
            collection_id=collection_id
        )

    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_views.delete_collection_service')
    @pytest.mark.asyncio
    async def test_delete_collection_invalid_token(self, mock_service):
        """Test deleting collection with invalid authentication token"""
        token = "invalid_token"
        collection_id = uuid4()

        auth_credentials = TestDataFactory.create_auth_credentials(token=token)

        mock_service.side_effect = HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials"
        )

        with pytest.raises(HTTPException) as exc_info:
            await delete_collection(
                collection_id=collection_id,
                authentication_credential=auth_credentials
            )

        assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED

    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_views.delete_collection_service')
    @pytest.mark.asyncio
    async def test_delete_collection_wrong_owner(self, mock_service):
        """Test deleting collection owned by another user"""
        token = "valid_token"
        collection_id = uuid4()

        auth_credentials = TestDataFactory.create_auth_credentials(token=token)

        mock_service.side_effect = HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "NOT_FOUND", "message": f"Collection with ID {collection_id} not found"}
        )

        with pytest.raises(HTTPException) as exc_info:
            await delete_collection(
                collection_id=collection_id,
                authentication_credential=auth_credentials
            )

        assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND

    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_views.delete_collection_service')
    @pytest.mark.asyncio
    async def test_delete_collection_database_error(self, mock_service):
        """Test database error during collection deletion"""
        token = "valid_token"
        collection_id = uuid4()

        auth_credentials = TestDataFactory.create_auth_credentials(token=token)

        mock_service.side_effect = HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "BAD_REQUEST", "message": "Database error"}
        )

        with pytest.raises(HTTPException) as exc_info:
            await delete_collection(
                collection_id=collection_id,
                authentication_credential=auth_credentials
            )

        assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST

    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_views.delete_collection_service')
    @pytest.mark.asyncio
    async def test_delete_collection_with_items(self, mock_service):
        """Test deleting collection that has items (cascade delete)"""
        token = "valid_token"
        collection_id = uuid4()

        auth_credentials = TestDataFactory.create_auth_credentials(token=token)
        mock_service.return_value = None

        result = await delete_collection(
            collection_id=collection_id,
            authentication_credential=auth_credentials
        )

        assert result is None

        mock_service.assert_awaited_once_with(
            token=token,
            collection_id=collection_id
        )

    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_views.delete_collection_service')
    @pytest.mark.asyncio
    async def test_delete_collection_returns_no_content(self, mock_service):
        """Test that delete endpoint returns no content (HTTP 204)"""
        token = "valid_token"
        collection_id = uuid4()

        auth_credentials = TestDataFactory.create_auth_credentials(token=token)
        mock_service.return_value = None

        result = await delete_collection(
            collection_id=collection_id,
            authentication_credential=auth_credentials
        )

        assert result is None

        mock_service.assert_awaited_once_with(
            token=token,
            collection_id=collection_id
        )


class TestDeleteCollectionItemView:

    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_views.delete_collection_item_service')
    @pytest.mark.asyncio
    async def test_delete_collection_item_success(self, mock_service):
        """Test successful item deletion"""
        token = "valid_token"
        collection_id = uuid4()
        item_id = uuid4()

        auth_credentials = TestDataFactory.create_auth_credentials(token=token)
        mock_service.return_value = None

        result = await delete_collection_item(
            collection_id=collection_id,
            item_id=item_id,
            authentication_credential=auth_credentials
        )

        assert result is None

        mock_service.assert_awaited_once_with(
            token=token,
            collection_id=collection_id,
            item_id=item_id
        )

    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_views.delete_collection_item_service')
    @pytest.mark.asyncio
    async def test_delete_collection_item_collection_not_found(self, mock_service):
        """Test deleting item from a non-existent collection"""
        token = "valid_token"
        collection_id = uuid4()
        item_id = uuid4()

        auth_credentials = TestDataFactory.create_auth_credentials(token=token)

        mock_service.side_effect = HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "NOT_FOUND", "message": f"Collection with ID {collection_id} not found"}
        )

        with pytest.raises(HTTPException) as exc_info:
            await delete_collection_item(
                collection_id=collection_id,
                item_id=item_id,
                authentication_credential=auth_credentials
            )

        assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND

    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_views.delete_collection_item_service')
    @pytest.mark.asyncio
    async def test_delete_collection_item_not_found(self, mock_service):
        """Test deleting a non-existent item"""
        token = "valid_token"
        collection_id = uuid4()
        item_id = uuid4()

        auth_credentials = TestDataFactory.create_auth_credentials(token=token)

        mock_service.side_effect = HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "NOT_FOUND", "message": f"Item with ID {item_id} not found"}
        )

        with pytest.raises(HTTPException) as exc_info:
            await delete_collection_item(
                collection_id=collection_id,
                item_id=item_id,
                authentication_credential=auth_credentials
            )

        assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND
        assert exc_info.value.detail["error"] == "NOT_FOUND"

    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_views.delete_collection_item_service')
    @pytest.mark.asyncio
    async def test_delete_collection_item_invalid_token(self, mock_service):
        """Test deleting item with invalid authentication token"""
        token = "invalid_token"
        collection_id = uuid4()
        item_id = uuid4()

        auth_credentials = TestDataFactory.create_auth_credentials(token=token)

        mock_service.side_effect = HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials"
        )

        with pytest.raises(HTTPException) as exc_info:
            await delete_collection_item(
                collection_id=collection_id,
                item_id=item_id,
                authentication_credential=auth_credentials
            )

        assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED

    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_views.delete_collection_item_service')
    @pytest.mark.asyncio
    async def test_delete_collection_item_database_error(self, mock_service):
        """Test database error during item deletion"""
        token = "valid_token"
        collection_id = uuid4()
        item_id = uuid4()

        auth_credentials = TestDataFactory.create_auth_credentials(token=token)

        mock_service.side_effect = HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "BAD_REQUEST", "message": "Database error"}
        )

        with pytest.raises(HTTPException) as exc_info:
            await delete_collection_item(
                collection_id=collection_id,
                item_id=item_id,
                authentication_credential=auth_credentials
            )

        assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST


class TestUpdateCollectionItemDisplayOrderView:

    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_views.update_collection_item_display_order_service')
    @pytest.mark.asyncio
    async def test_update_display_order_success(self, mock_service):
        token = "valid_token"
        collection_id = uuid4()
        item_id = uuid4()
        auth_credentials = TestDataFactory.create_auth_credentials(token=token)
        request = UpdateCollectionItemRequest(display_order=1.4)
        mock_response = TestDataFactory.create_collection_item_dto(
            id=item_id,
            display_order=1.4
        )
        mock_service.return_value = mock_response

        result = await update_collection_item_display_order(
            collection_id=collection_id,
            item_id=item_id,
            authentication_credential=auth_credentials,
            request=request
        )

        assert isinstance(result, RecitationCollectionItemDTO)
        assert result.id == item_id
        assert result.display_order == 1.4
        mock_service.assert_awaited_once_with(
            token=token,
            collection_id=collection_id,
            item_id=item_id,
            request=request
        )

    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_views.update_collection_item_display_order_service')
    @pytest.mark.asyncio
    async def test_update_display_order_collection_not_found(self, mock_service):
        collection_id = uuid4()
        item_id = uuid4()
        auth_credentials = TestDataFactory.create_auth_credentials()
        request = UpdateCollectionItemRequest(display_order=2.5)
        mock_service.side_effect = HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "NOT_FOUND", "message": f"Collection with ID {collection_id} not found"}
        )

        with pytest.raises(HTTPException) as exc_info:
            await update_collection_item_display_order(
                collection_id=collection_id,
                item_id=item_id,
                authentication_credential=auth_credentials,
                request=request
            )

        assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND

    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_views.update_collection_item_display_order_service')
    @pytest.mark.asyncio
    async def test_update_display_order_item_not_found(self, mock_service):
        collection_id = uuid4()
        item_id = uuid4()
        auth_credentials = TestDataFactory.create_auth_credentials()
        request = UpdateCollectionItemRequest(display_order=2.5)
        mock_service.side_effect = HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "NOT_FOUND", "message": f"Item with ID {item_id} not found"}
        )

        with pytest.raises(HTTPException) as exc_info:
            await update_collection_item_display_order(
                collection_id=collection_id,
                item_id=item_id,
                authentication_credential=auth_credentials,
                request=request
            )

        assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND

    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_views.update_collection_item_display_order_service')
    @pytest.mark.asyncio
    async def test_update_display_order_duplicate(self, mock_service):
        collection_id = uuid4()
        item_id = uuid4()
        auth_credentials = TestDataFactory.create_auth_credentials()
        request = UpdateCollectionItemRequest(display_order=1.0)
        mock_service.side_effect = HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "Bad request", "message": "Display order must be unique among items in this collection"}
        )

        with pytest.raises(HTTPException) as exc_info:
            await update_collection_item_display_order(
                collection_id=collection_id,
                item_id=item_id,
                authentication_credential=auth_credentials,
                request=request
            )

        assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST

    @patch('pecha_api.plans.users.recitation_collection.recitation_collection_views.update_collection_item_display_order_service')
    @pytest.mark.asyncio
    async def test_update_display_order_invalid_token(self, mock_service):
        collection_id = uuid4()
        item_id = uuid4()
        auth_credentials = TestDataFactory.create_auth_credentials(token="invalid_token")
        request = UpdateCollectionItemRequest(display_order=1.4)
        mock_service.side_effect = HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials"
        )

        with pytest.raises(HTTPException) as exc_info:
            await update_collection_item_display_order(
                collection_id=collection_id,
                item_id=item_id,
                authentication_credential=auth_credentials,
                request=request
            )

        assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED
