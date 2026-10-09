"""eSIM Access top-up helpers.

This module only talks to the provider. A customer-facing checkout must collect
payment and verify it before calling topup_esim(); never call it directly from
an untrusted browser request.
"""
from __future__ import annotations

import uuid
from typing import Any, Optional

import requests

from app.api.client import BASE_URL, get_client


class TopUpError(RuntimeError):
    """Raised when eSIM Access rejects a top-up request or returns bad data."""


def get_topup_packages(
    *,
    iccid: str = "",
    esim_tran_no: str = "",
    package_code: str = "",
    slug: str = "",
) -> list[dict[str, Any]]:
    """Return top-up packages compatible with the specified eSIM or base package.

    At least one identifier is required. For a customer-specific top-up list,
    prefer ICCID; provider documentation also supports a base package slug/code.
    """
    if not any((iccid.strip(), esim_tran_no.strip(), package_code.strip(), slug.strip())):
        raise ValueError("Provide an ICCID, eSIM transaction number, or base package code/slug.")

    payload: dict[str, str] = {"type": "TOPUP"}
    if iccid.strip():
        payload["iccid"] = iccid.strip()
    elif package_code.strip():
        payload["packageCode"] = package_code.strip()
    elif slug.strip():
        payload["slug"] = slug.strip()
    else:
        # esimTranNo is supported by the top-up endpoint, but is not explicitly
        # documented as a package-list filter. Use the saved ICCID or base slug.
        raise ValueError("For listing top-up packages, provide ICCID or base package code/slug.")

    try:
        response = get_client().post(
            f"{BASE_URL}/package/list", json=payload, timeout=20
        )
        response.raise_for_status()
        data = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise TopUpError(f"Could not retrieve top-up packages: {exc}") from exc

    if not data.get("success"):
        message = data.get("errorMsg") or data.get("errorMessage") or "Unknown provider error"
        raise TopUpError(f"eSIM Access rejected top-up package query: {message}")

    obj = data.get("obj") or {}
    return obj.get("packageList") or []


def topup_esim(
    *,
    package_code: str,
    esim_tran_no: str = "",
    iccid: str = "",
    transaction_id: Optional[str] = None,
    amount: Optional[int] = None,
    period_num: Optional[int] = None,
) -> dict[str, Any]:
    """Add a selected compatible package to an existing eSIM.

    IMPORTANT: call only after payment has been verified server-side.
    package_code should be the TOP-UP package slug (preferred by provider)
    or packageCode. amount, if supplied, uses provider units (10,000 = USD 1).
    """
    package_code = package_code.strip()
    esim_tran_no = esim_tran_no.strip()
    iccid = iccid.strip()

    if not package_code:
        raise ValueError("package_code is required.")
    if not esim_tran_no and not iccid:
        raise ValueError("Provide esim_tran_no or iccid.")
    if amount is not None and amount < 0:
        raise ValueError("amount cannot be negative.")
    if period_num is not None and not 1 <= period_num <= 365:
        raise ValueError("period_num must be between 1 and 365.")

    # Provider requires a unique transactionId.
    txn_id = (transaction_id or f"bgesim-topup-{uuid.uuid4().hex}").strip()
    if not txn_id or len(txn_id) > 50:
        raise ValueError("transaction_id must be 1–50 characters.")

    payload: dict[str, Any] = {
        "transactionId": txn_id,
        "packageCode": package_code,
    }
    if esim_tran_no:
        payload["esimTranNo"] = esim_tran_no
    if iccid:
        payload["iccid"] = iccid
    if amount is not None:
        payload["amount"] = amount
    if period_num is not None:
        payload["periodNum"] = period_num

    try:
        response = get_client().post(
            f"{BASE_URL}/esim/topup", json=payload, timeout=30
        )
        response.raise_for_status()
        data = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise TopUpError(f"Top-up request failed: {exc}") from exc

    if not data.get("success"):
        message = data.get("errorMsg") or data.get("errorMessage") or "Unknown provider error"
        code = data.get("errorCode")
        raise TopUpError(f"eSIM Access top-up rejected ({code}): {message}")

    result = data.get("obj") or {}
    if not result:
        raise TopUpError("Provider reported success but returned no top-up details.")

    return result
