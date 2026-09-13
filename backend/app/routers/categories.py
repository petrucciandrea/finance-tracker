"""
Categories endpoints: CRUD with soft delete and a self-referential
parent/child hierarchy (e.g. "Food" -> "Restaurants").
"""

from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.deps import get_current_user, get_db
from app.models import Category, User
from app.schemas import Category as CategorySchema, CategoryCreate, CategoryUpdate

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

    category = Category(
        user_id=current_user.id,
        name=payload.name,
        type=payload.type.value,
        parent_id=payload.parent_id,
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

    for field, value in update_data.items():
        setattr(category, field, value)

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

    category.deleted_at = datetime.now(timezone.utc)
    db.commit()
    # Transactions referencing this category keep their category_id — the
    # frontend shows "Deleted category" instead of erroring, as decided
    # for the soft-delete strategy.