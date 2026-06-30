# ******************************************************************************
# IBM Confidential
#
# OCO Source Materials
#
#  Copyright IBM Corp. 2026  All Rights Reserved.
#
# The source code for this program is not published or otherwise divested
# of its trade secrets, irrespective of what has been deposited with
# the U.S. Copyright Office.
# ******************************************************************************

"""Public workspace-config endpoints.

Today there's just one — ``GET /api/onboarding-status`` — used by the
frontend on initial render to decide whether to show the onboarding
wizard or the login flow. No auth required (must work pre-login so the
wizard can render). Returns exactly two scalar fields, no provider data.
"""

from __future__ import annotations

from typing import Optional, Union

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from dependencies import get_workspace_config_service

# Backend routes are mounted WITHOUT the /api prefix because the Next.js
# proxy at frontend/app/api/[...path]/route.ts strips it before forwarding.
# Frontend reaches this via /api/onboarding-status.
router = APIRouter(tags=["onboarding"])


class OnboardingStatusResponse(BaseModel):
    onboarded: bool
    # OnboardingState.current_step is an int (step index) in the legacy
    # config_manager dataclass; future schema may switch it to a string
    # name. Accept either to stay forward-compatible.
    current_step: int | str | None = None


@router.get("/onboarding-status", response_model=OnboardingStatusResponse)
async def onboarding_status(
    config_service=Depends(get_workspace_config_service),
) -> OnboardingStatusResponse:
    """Public endpoint — no auth.

    The frontend hits this on first render to decide between rendering
    the onboarding wizard and the login screen. Discloses one bit
    (whether the workspace is set up). Returns no provider keys, no
    settings details.
    """
    return OnboardingStatusResponse(
        onboarded=await config_service.is_onboarded(),
        current_step=await config_service.get_onboarding_step(),
    )
