from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from database import get_session
from models import XtreamAccount
from services.xtream_client import XtreamClient


router = APIRouter()


class AccountCreate(BaseModel):
    name: str
    server_url: str
    username: str
    password: str
    catchup_days: int = 7


class AccountUpdate(BaseModel):
    name: str | None = None
    server_url: str | None = None
    username: str | None = None
    password: str | None = None
    is_active: bool | None = None
    catchup_days: int | None = None


@router.get("")
async def list_accounts(session: AsyncSession = Depends(get_session)):
    """List all Xtream accounts."""
    result = await session.execute(select(XtreamAccount).order_by(XtreamAccount.name))
    accounts = result.scalars().all()
    return [acc.to_dict() for acc in accounts]


@router.post("")
async def create_account(
    account: AccountCreate,
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
        catchup_days=account.catchup_days,
        max_connections=user_info.get("max_connections"),
        active_connections=user_info.get("active_cons"),
        expiration_date=exp_date,
    )

    session.add(db_account)
    await session.commit()
    await session.refresh(db_account)

    return db_account.to_dict()


@router.get("/{account_id}")
async def get_account(
    account_id: int,
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
