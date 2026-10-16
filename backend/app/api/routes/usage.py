from __future__ import annotations

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import get_session
from app.modules.auth.dependencies import get_current_user
from app.modules.billing.schemas import UsageSummary
from app.modules.billing.service import BillingService
from app.modules.organizations.repository import OrganizationRepository
from app.modules.users.models import User

router = APIRouter(prefix="/usage", tags=["usage"])


@router.get("", response_model=UsageSummary)
async def get_usage(
    org_id: Optional[uuid.UUID] = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """Retrieve usage metrics and quota consumption for the current period."""
    org_repo = OrganizationRepository(db)
    if org_id:
        org = await org_repo.get_by_id(org_id)
        if not org:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found"
            )
        target_org_id = org.id
    else:
        primary_org = await org_repo.get_user_primary_org(user.id)
        target_org_id = primary_org.id

    service = BillingService(db)
    return await service.get_usage_summary(target_org_id)
