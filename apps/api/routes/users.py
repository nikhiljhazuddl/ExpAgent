"""GET /api/me, GET /api/users."""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends

from deps import CurrentUser, current_user, output_dir

router = APIRouter()


@router.get("/me")
def me(user: CurrentUser = Depends(current_user)) -> dict:
    return {"role": user.role, "user": user.user}


@router.get("/users")
def users() -> dict:
    """Derive the (role, name) list from the latest output files."""
    out = output_dir()
    aes: set[str] = set()
    csms: set[str] = set()

    queues_ae = out / "queues" / "by_ae"
    queues_csm = out / "queues" / "by_csm"
    if queues_ae.exists():
        for p in queues_ae.glob("*.json"):
            try:
                payload = json.loads(p.read_text())
                if payload.get("user"):
                    aes.add(payload["user"])
            except (json.JSONDecodeError, OSError):
                continue
    if queues_csm.exists():
        for p in queues_csm.glob("*.json"):
            try:
                payload = json.loads(p.read_text())
                if payload.get("user"):
                    csms.add(payload["user"])
            except (json.JSONDecodeError, OSError):
                continue

    # Also pull notification owners (they may not have any active signal queue)
    notif_ae = out / "notifications" / "by_ae"
    notif_csm = out / "notifications" / "by_csm"
    for d, target in ((notif_ae, aes), (notif_csm, csms)):
        if not d.exists():
            continue
        for p in d.glob("*.json"):
            try:
                payload = json.loads(p.read_text())
                if payload.get("user"):
                    target.add(payload["user"])
            except (json.JSONDecodeError, OSError):
                continue

    users_payload = (
        [{"role": "AE", "name": n} for n in sorted(aes)]
        + [{"role": "CSM", "name": n} for n in sorted(csms)]
        + [{"role": "RevOps", "name": "RevOps Lead"}, {"role": "Admin", "name": "Admin"}]
    )
    return {"roles": ["AE", "CSM", "RevOps", "Admin"], "users": users_payload}
