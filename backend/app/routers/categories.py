"""
Categories endpoints: CRUD with soft delete and a self-referential
parent/child hierarchy (e.g. "Food" -> "Restaurants").
"""

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.deps import get_current_user, get_db
from app.models import Category, User
from app.schemas import Category as CategorySchema
from app.schemas import CategoryCreate, CategoryUpdate

router = APIRouter(prefix="/api/v1/categories", tags=["categories"])


def _get_owned_category(db: Session, category_id: UUID, user: User) -> Category:
    category = (
        db.query(Category)
        .filter(
            Category.id == category_id,
            Category.user_id == user.id,
            Category.deleted_at.is_(None),
        )
        .first()
    )
    if category is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Category not found")
    return category


def _validate_parent(db: Session, parent_id: UUID | None, user: User, category_type: str) -> None:
    """
    A parent must: exist, belong to the same user, not be soft-deleted, and
    share the same type (an expense category can't nest under an income one).
    Nesting is capped at two levels — a subcategory can't itself become a
    parent — since the "assign to a category that has subcategories" rule
    on transactions only makes sense for a flat parent/child hierarchy.
    """
    if parent_id is None:
        return

    parent = _get_owned_category(db, parent_id, user)
    if parent.type != category_type:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="A category's parent must have the same type (expense/income)",
        )
    if parent.parent_id is not None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="A subcategory cannot itself be used as a parent category",
        )


def _validate_necessity_fields(
    category_type: str,
    necessity_level: object,
    excluded_from_income_base: object,
    *,
    necessity_provided: bool,
    exclusion_provided: bool,
) -> None:
    """
    The two planning fields belong to opposite halves of the taxonomy and
    are rejected on the wrong one rather than silently ignored.

    `necessity_level` answers "how essential is this spend", so it only
    means something on an expense category — same rule as "budgets only on
    expense categories". `excluded_from_income_base` answers "does this
    count as income for the allocation model", so it only means something
    on an income category.

    Clearing `necessity_level` back to NULL is legitimate (it means
    "unclassified"), so only a non-null value on the wrong type is an
    error. `excluded_from_income_base` is NOT NULL in the database, so an
    explicit null is rejected instead of being quietly dropped.
    """
    if necessity_provided and necessity_level is not None and category_type != "expense":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="necessity_level can only be set on expense categories",
        )

    if exclusion_provided:
        if excluded_from_income_base is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="excluded_from_income_base cannot be null",
            )
        if excluded_from_income_base and category_type != "income":
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="excluded_from_income_base can only be set on income categories",
            )


def _has_active_children(db: Session, category_id: UUID) -> bool:
    return (
        db.query(Category)
        .filter(Category.parent_id == category_id, Category.deleted_at.is_(None))
        .first()
        is not None
    )


@router.get("", response_model=list[CategorySchema])
def list_categories(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[Category]:
    # Returned flat, ordered so parents precede their children — the
    # frontend builds the tree client-side from `parent_id`.
    return (
        db.query(Category)
        .filter(Category.user_id == current_user.id, Category.deleted_at.is_(None))
        .order_by(Category.parent_id.is_(None).desc(), Category.name)
        .all()
    )


@router.post("", response_model=CategorySchema, status_code=status.HTTP_201_CREATED)
def create_category(
    payload: CategoryCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Category:
    _validate_parent(db, payload.parent_id, current_user, payload.type.value)
    _validate_necessity_fields(
        payload.type.value,
        payload.necessity_level,
        payload.excluded_from_income_base,
        necessity_provided=True,
        exclusion_provided=True,
    )

    category = Category(
        user_id=current_user.id,
        name=payload.name,
        type=payload.type.value,
        parent_id=payload.parent_id,
        necessity_level=(
            payload.necessity_level.value if payload.necessity_level is not None else None
        ),
        excluded_from_income_base=payload.excluded_from_income_base,
    )
    db.add(category)
    db.commit()
    db.refresh(category)
    return category


@router.get("/{category_id}", response_model=CategorySchema)
def get_category(
    category_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Category:
    return _get_owned_category(db, category_id, current_user)


@router.patch("/{category_id}", response_model=CategorySchema)
def update_category(
    category_id: UUID,
    payload: CategoryUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Category:
    category = _get_owned_category(db, category_id, current_user)
    update_data = payload.model_dump(exclude_unset=True)

    if "parent_id" in update_data:
        new_parent_id = update_data["parent_id"]
        if new_parent_id == category.id:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="A category cannot be its own parent",
            )
        _validate_parent(db, new_parent_id, current_user, category.type)

    _validate_necessity_fields(
        category.type,
        update_data.get("necessity_level"),
        update_data.get("excluded_from_income_base"),
        necessity_provided="necessity_level" in update_data,
        exclusion_provided="excluded_from_income_base" in update_data,
    )

    for field, value in update_data.items():
        # `necessity_level` arrives as an enum member; store its string value
        # like `type` does on create.
        setattr(category, field, value.value if hasattr(value, "value") else value)

    db.commit()
    db.refresh(category)
    return category


@router.delete("/{category_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_category(
    category_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    category = _get_owned_category(db, category_id, current_user)

    if _has_active_children(db, category.id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot delete a category that still has active subcategories",
        )

    category.deleted_at = datetime.now(UTC)
    db.commit()
    # Transactions referencing this category keep their category_id — the
    # frontend shows "Deleted category" instead of erroring, as decided
    # for the soft-delete strategy.