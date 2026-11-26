"""
The pillar-4 guardrails the user sets in the plan, their state, and the
generic presets that fill the targets in.

Under `/api/v1/planning` with the rest of the plan: to a client these are
the plan's investing section, even though they read the portfolio.
"""

from datetime import date as date_
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.deps import get_current_user, get_db
from app.models import Account, AssetTransaction, PortfolioRule, User
from app.schemas import (
    EXPOSURE_BUCKETS,
    ApplyPresetRequest,
    ExposureDimension,
    PortfolioPreset,
    PortfolioRuleCreate,
    PortfolioRuleKind,
    PortfolioRulesStatus,
    TargetsReplace,
)
from app.schemas import PortfolioRule as PortfolioRuleSchema
from app.services import portfolio_rules as service

router = APIRouter(prefix="/api/v1/planning", tags=["planning"])

TARGET_DIMENSIONS = {ExposureDimension.asset_class.value, ExposureDimension.region.value}
POSITION = "position"
# The fields each kind takes; any other one set is a 422, not silently dropped.
FIELDS = {
    PortfolioRuleKind.target: {"dimension", "bucket", "target_pct", "tolerance_pct"},
    PortfolioRuleKind.max_share: {"dimension", "bucket", "max_pct"},
    PortfolioRuleKind.excess_cash: {"threshold_amount", "threshold_months"},
    PortfolioRuleKind.min_invested: {"min_pct"},
}


def _unprocessable(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=detail)


def _get_owned_rule(db: Session, rule_id: UUID, user: User) -> PortfolioRule:
    rule = (
        db.query(PortfolioRule)
        .filter(PortfolioRule.id == rule_id, PortfolioRule.user_id == user.id)
        .first()
    )
    if rule is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rule not found")
    return rule


def _holds_asset(db: Session, user: User, asset_id: str) -> bool:
    try:
        parsed = UUID(asset_id)
    except ValueError:
        return False
    return (
        db.query(AssetTransaction.id)
        .join(Account, Account.id == AssetTransaction.account_id)
        .filter(
            Account.user_id == user.id,
            AssetTransaction.asset_id == parsed,
            AssetTransaction.deleted_at.is_(None),
        )
        .first()
        is not None
    )


def _validate(db: Session, user: User, payload: PortfolioRuleCreate) -> None:
    given = {k for k, v in payload.model_dump(exclude={"kind"}).items() if v is not None}
    extra = given - FIELDS[payload.kind]
    if extra:
        raise _unprocessable(f"A {payload.kind.value} rule doesn't take {', '.join(sorted(extra))}")

    if payload.kind == PortfolioRuleKind.target:
        if payload.dimension not in TARGET_DIMENSIONS:
            raise _unprocessable("Targets are by asset class or region")
        if payload.target_pct is None:
            raise _unprocessable("A target needs target_pct")
    if payload.kind == PortfolioRuleKind.max_share:
        if payload.max_pct is None:
            raise _unprocessable("A cap needs max_pct")
        if payload.dimension == POSITION:
            if not payload.bucket or not _holds_asset(db, user, payload.bucket):
                raise _unprocessable("A position cap needs a product you hold")
        elif payload.dimension not in EXPOSURE_BUCKETS:
            raise _unprocessable("Unknown dimension")
    if payload.kind in (PortfolioRuleKind.target, PortfolioRuleKind.max_share):
        if payload.dimension != POSITION and payload.bucket not in EXPOSURE_BUCKETS.get(
            payload.dimension or "", ()
        ):
            raise _unprocessable(f"Unknown bucket «{payload.bucket}» for {payload.dimension}")
    if payload.kind == PortfolioRuleKind.excess_cash and (
        (payload.threshold_amount is None) == (payload.threshold_months is None)
    ):
        raise _unprocessable("Set either threshold_amount or threshold_months")
    if payload.kind == PortfolioRuleKind.min_invested and payload.min_pct is None:
        raise _unprocessable("A minimum needs min_pct")


def _reject_duplicates(db: Session, user: User, payload: PortfolioRuleCreate) -> None:
    rules = service.list_rules(db, user)
    same = [
        r
        for r in rules
        if r.kind == payload.kind.value
        and (
            payload.kind in (PortfolioRuleKind.excess_cash, PortfolioRuleKind.min_invested)
            or (r.dimension == payload.dimension and r.bucket == payload.bucket)
        )
    ]
    if same:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This rule already exists — change or delete it instead",
        )
    if payload.kind == PortfolioRuleKind.target:
        total = sum(
            (
                Decimal(str(r.target_pct))
                for r in rules
                if r.kind == PortfolioRuleKind.target.value and r.dimension == payload.dimension
            ),
            Decimal("0"),
        )
        if total + (payload.target_pct or 0) > 100:
            raise _unprocessable("The targets of this dimension would add up to more than 100")


@router.get("/portfolio-rules", response_model=PortfolioRulesStatus)
def get_rules(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PortfolioRulesStatus:
    return service.evaluate(db, current_user, date_.today())


@router.post(
    "/portfolio-rules", response_model=PortfolioRuleSchema, status_code=status.HTTP_201_CREATED
)
def create_rule(
    payload: PortfolioRuleCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PortfolioRule:
    if payload.kind == PortfolioRuleKind.target and payload.tolerance_pct is None:
        payload.tolerance_pct = Decimal("5")
    _validate(db, current_user, payload)
    _reject_duplicates(db, current_user, payload)
    rule = PortfolioRule(user_id=current_user.id, **payload.model_dump(exclude={"kind"}))
    rule.kind = payload.kind.value
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return rule


@router.delete("/portfolio-rules/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_rule(
    rule_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    db.delete(_get_owned_rule(db, rule_id, current_user))
    db.commit()


@router.get("/portfolio-presets", response_model=list[PortfolioPreset])
def list_presets(current_user: User = Depends(get_current_user)) -> list[PortfolioPreset]:
    return service.PRESETS


@router.post("/portfolio-rules/preset", response_model=PortfolioRulesStatus)
def apply_preset(
    payload: ApplyPresetRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PortfolioRulesStatus:
    """
    Replaces every target with the preset's. Caps, the idle-cash threshold
    and the minimum invested share are the user's own and stay.
    """
    preset = service.PRESETS_BY_KEY.get(payload.preset)
    if preset is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Preset not found")
    db.query(PortfolioRule).filter(
        PortfolioRule.user_id == current_user.id,
        PortfolioRule.kind == PortfolioRuleKind.target.value,
    ).delete(synchronize_session=False)
    for target in preset.targets:
        db.add(
            PortfolioRule(
                user_id=current_user.id,
                kind=PortfolioRuleKind.target.value,
                dimension=target.dimension.value,
                bucket=target.bucket,
                target_pct=target.target_pct,
                tolerance_pct=payload.tolerance_pct,
            )
        )
    db.commit()
    return service.evaluate(db, current_user, date_.today())


@router.put("/portfolio-rules/targets", response_model=PortfolioRulesStatus)
def replace_targets(
    payload: TargetsReplace,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PortfolioRulesStatus:
    """
    Replaces the targets of one dimension; the other dimension's targets,
    the caps and the thresholds stay. One commit, so the stored mix is never
    a half-way state that adds up to more than 100.
    """
    dimension = payload.dimension.value
    if dimension not in TARGET_DIMENSIONS:
        raise _unprocessable("Targets are by asset class or region")
    allowed = EXPOSURE_BUCKETS[dimension]
    seen: set[str] = set()
    for target in payload.targets:
        if target.bucket not in allowed:
            raise _unprocessable(f"Unknown bucket «{target.bucket}» for {dimension}")
        if target.bucket in seen:
            raise _unprocessable(f"Bucket «{target.bucket}» appears twice")
        seen.add(target.bucket)
    if sum((t.target_pct for t in payload.targets), Decimal("0")) > 100:
        raise _unprocessable("The targets add up to more than 100")

    db.query(PortfolioRule).filter(
        PortfolioRule.user_id == current_user.id,
        PortfolioRule.kind == PortfolioRuleKind.target.value,
        PortfolioRule.dimension == dimension,
    ).delete(synchronize_session=False)
    for target in payload.targets:
        if target.target_pct == 0:
            continue
        db.add(
            PortfolioRule(
                user_id=current_user.id,
                kind=PortfolioRuleKind.target.value,
                dimension=dimension,
                bucket=target.bucket,
                target_pct=target.target_pct,
                tolerance_pct=payload.tolerance_pct,
            )
        )
    db.commit()
    return service.evaluate(db, current_user, date_.today())
