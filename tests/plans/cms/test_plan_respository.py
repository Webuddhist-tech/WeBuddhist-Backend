import uuid
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from pecha_api.db.database import Base
from pecha_api.plans.plans_models import Plan
from pecha_api.plans.items.plan_items_models import PlanItem
from pecha_api.plans.users.plan_users_models import UserPlanProgress
from pecha_api.plans.authors.plan_authors_model import Author
from pecha_api.plans.cms.cms_plans_repository import save_plan, get_plans_by_author_id
from pecha_api.plans.plans_response_models import PlansRepositoryResponse
from pecha_api.users.users_models import Users
from tests.postgres_integration import postgres_integration_url

DATABASE_URL = postgres_integration_url()
if not DATABASE_URL:
    pytest.skip(
        "Set TEST_DATABASE_URL to a reachable PostgreSQL database to run these tests.",
        allow_module_level=True,
    )

engine = create_engine(DATABASE_URL)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(scope="module")
def db():
    # Create only the plans-related tables needed for these tests
    Base.metadata.create_all(
        bind=engine,
        tables=[Users.__table__, Author.__table__, Plan.__table__, PlanItem.__table__, UserPlanProgress.__table__],
    )
    db = TestingSessionLocal()
    yield db
    db.close()
    Base.metadata.drop_all(
        bind=engine,
        tables=[Users.__table__, Author.__table__, Plan.__table__, PlanItem.__table__, UserPlanProgress.__table__],
    )


def _create_author(db) -> Author:
    author = Author(
        first_name="First",
        last_name="Last",
        email=f"{uuid.uuid4()}@example.com",
        password="secret",
        created_by="tester",
    )
    db.add(author)
    db.commit()
    db.refresh(author)
    return author


def test_save_plan_success(db):
    author = _create_author(db)

    plan = Plan(
        title="Mindfulness Basics",
        description="A simple plan.",
        author_id=author.id,
        created_by="tester",
    )

    saved = save_plan(db, plan)

    assert saved.id is not None
    assert saved.title == "Mindfulness Basics"
    assert saved.author_id == author.id


def test_get_plans_filter_sort_and_pagination(db):
    author = _create_author(db)

    # Seed multiple plans
    titles = ["B Plan", "A Plan", "C Plan"]
    for t in titles:
        p = Plan(
            title=t,
            description=f"{t} description",
            author_id=author.id,
            created_by="tester",
        )
        save_plan(db, p)

    # Sort by status ascending (all defaults are DRAFT)
    repo_resp: PlansRepositoryResponse = get_plans_by_author_id(
        db=db,
        search=None,
        author_id=author.id,
        sort_by="status",
        sort_order="asc",
        skip=0,
        limit=10,
    )

    assert repo_resp.total >= 3
    titles = [r.plan.title for r in repo_resp.plan_info[:3]]
    assert set(["A Plan", "B Plan", "C Plan"]) <= set(titles)

    # Search filter
    repo_resp = get_plans_by_author_id(
        db=db,
        search="A",
        author_id=author.id,
        sort_by="status",
        sort_order="asc",
        skip=0,
        limit=10,
    )
    assert any(r.plan.title == "A Plan" for r in repo_resp.plan_info)
    assert all("A" in r.plan.title for r in repo_resp.plan_info)

    # Pagination
    repo_resp = get_plans_by_author_id(
        db=db,
        search=None,
        author_id=author.id,
        sort_by="status",
        sort_order="asc",
        skip=1,
        limit=1,
    )
    assert len(repo_resp.plan_info) == 1
    assert repo_resp.plan_info[0].plan.title in ["A Plan", "B Plan", "C Plan"]


def test_get_plans_sort_by_total_days_desc(db):
    author = _create_author(db)

    # Create three plans and attach different numbers of items
    plan_counts = {"Zero": 0, "One": 1, "Two": 2}
    created = {}
    for title, count in plan_counts.items():
        p = Plan(
            title=f"{title} Items Plan",
            description="desc",
            author_id=author.id,
            created_by="tester",
        )
        p = save_plan(db, p)
        created[title] = p
        for day in range(count):
            item = PlanItem(
                plan_id=p.id,
                day_number=day + 1,
                created_by="tester",
            )
            db.add(item)
        db.commit()

    repo_resp = get_plans_by_author_id(
        db=db,
        search=None,
        author_id=author.id,
        sort_by="total_days",
        sort_order="desc",
        skip=0,
        limit=10,
    )

    # Extract just the seeded three for assertion order
    titles_in_order = [r.plan.title for r in repo_resp.plan_info if r.plan.title.endswith("Items Plan")]
    # Expect Two > One > Zero by total_days
    assert titles_in_order[:3] == [
        "Two Items Plan",
        "One Items Plan",
        "Zero Items Plan",
    ]


