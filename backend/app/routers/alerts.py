"""Everything that needs attention, for the banner shown when the app is opened."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.deps import get_current_user, get_db
from app.models import User
from app.schemas import AlertsResponse
from app.services.alerts import build_alerts

router = APIRouter(prefix="/api/v1/alerts", tags=["alerts"])


@router.get("", response_model=AlertsResponse)
def get_alerts(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AlertsResponse:
    return build_alerts(db, current_user)
