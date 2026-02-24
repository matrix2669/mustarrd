import asyncio
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from auth import require_admin
from database import get_session
from models import XtreamAccount
from services.epg_ingest_manager import epg_ingest_manager
from services.xtream_client import XtreamClient


router = APIRouter()


def _log_task_result(task: asyncio.Task):
    try:
        task.result()
    except Exception as exc:
        print(f"EPG refresh task failed: {exc}")


class AccountCreate(BaseModel):
    name: str
    server_url: str
    username: str
    password: str


class AccountUpdate(BaseModel):
    name: str | None = None
    server_url: str | None = None
    username: str | None = None
    password: str | None = None
    is_active: bool | None = None


@router.get("")
async def list_accounts(
    _admin: None = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    """List all Xtream accounts."""
    result = await session.execute(select(XtreamAccount).order_by(XtreamAccount.name))
    accounts = result.scalars().all()
    return [acc.to_dict() for acc in accounts]


@router.get("/public")
async def list_accounts_public(
    _admin: None = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    """List minimal account info for non-admin browsing flows."""
    result = await session.execute(select(XtreamAccount).order_by(XtreamAccount.name))
    accounts = result.scalars().all()
    return [
        {
            "id": acc.id,
            "name": acc.name,
            "is_active": acc.is_active,
        }
        for acc in accounts
    ]


@router.post("")
async def create_account(
    account: AccountCreate,
    _admin: None = Depends(require_admin),
    session: AsyncSession = Depends(get_session)
):
    """Create a new Xtream account (validates connection)."""
    # Test connection first
    client = XtreamClient(account.server_url, account.username, account.password)
    try:
        auth_data = await client.authenticate()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Connection failed: {str(e)}")
    finally:
        await client.close()

    # Extract account info from auth response
    user_info = auth_data.get("user_info", {})
    server_info = auth_data.get("server_info", {})

    # Parse expiration date
    exp_date = None
    if user_info.get("exp_date"):
        try:
            exp_date = datetime.fromtimestamp(int(user_info["exp_date"]))
        except (ValueError, TypeError):
            pass

    # Create account
    db_account = XtreamAccount(
        name=account.name,
        server_url=account.server_url,
        username=account.username,
        password=account.password,
        max_connections=user_info.get("max_connections"),
        active_connections=user_info.get("active_cons"),
        expiration_date=exp_date,
    )

    session.add(db_account)
    await session.commit()
    await session.refresh(db_account)

    refresh_task = asyncio.create_task(epg_ingest_manager.refresh_account_by_id(db_account.id))
    refresh_task.add_done_callback(_log_task_result)

    return db_account.to_dict()


@router.get("/{account_id}")
async def get_account(
    account_id: int,
    _admin: None = Depends(require_admin),
    session: AsyncSession = Depends(get_session)
):
    """Get a specific account."""
    result = await session.execute(
        select(XtreamAccount).where(XtreamAccount.id == account_id)
    )
    account = result.scalar_one_or_none()

    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    return account.to_dict()


@router.put("/{account_id}")
async def update_account(
    account_id: int,
    update_data: AccountUpdate,
    _admin: None = Depends(require_admin),
    session: AsyncSession = Depends(get_session)
):
    """Update an account."""
    result = await session.execute(
        select(XtreamAccount).where(XtreamAccount.id == account_id)
    )
    account = result.scalar_one_or_none()

    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    # Update fields
    update_dict = update_data.model_dump(exclude_unset=True)
    for field, value in update_dict.items():
        setattr(account, field, value)

    await session.commit()
    await session.refresh(account)

    return account.to_dict()


@router.delete("/{account_id}")
async def delete_account(
    account_id: int,
    _admin: None = Depends(require_admin),
    session: AsyncSession = Depends(get_session)
):
    """Delete an account."""
    result = await session.execute(
        select(XtreamAccount).where(XtreamAccount.id == account_id)
    )
    account = result.scalar_one_or_none()

    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    await session.delete(account)
    await session.commit()

    return {"status": "deleted"}


@router.post("/{account_id}/test")
async def test_account(
    account_id: int,
    _admin: None = Depends(require_admin),
    session: AsyncSession = Depends(get_session)
):
    """Test connection to an account."""
    result = await session.execute(
        select(XtreamAccount).where(XtreamAccount.id == account_id)
    )
    account = result.scalar_one_or_none()

    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    client = XtreamClient(account.server_url, account.username, account.password)
    try:
        auth_data = await client.authenticate()

        # Update cached info
        user_info = auth_data.get("user_info", {})

        exp_date = None
        if user_info.get("exp_date"):
            try:
                exp_date = datetime.fromtimestamp(int(user_info["exp_date"]))
            except (ValueError, TypeError):
                pass

        account.max_connections = user_info.get("max_connections")
        account.active_connections = user_info.get("active_cons")
        account.expiration_date = exp_date
        account.last_used = datetime.utcnow()

        await session.commit()

        return {
            "status": "connected",
            "user_info": user_info,
            "server_info": auth_data.get("server_info", {}),
        }

    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Connection failed: {str(e)}")
    finally:
        await client.close()
