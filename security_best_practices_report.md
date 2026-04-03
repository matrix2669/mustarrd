# Security Best Practices Report

## Executive Summary

This review covered the FastAPI backend and React frontend in `/Users/tylerhereford/repos/catchup-dvr` against the `python-fastapi-web-server-security`, `javascript-typescript-react-web-frontend-security`, and `javascript-general-web-frontend-security` guidance bundled with the `security-best-practices` skill.

The highest-impact issues are:

1. First-run admin setup is reachable from any private-network client, which allows another host on the same LAN to claim the instance before the owner.
2. The app uses cookie-based session auth for privileged state-changing endpoints but does not implement CSRF protection or Origin/Referer validation.
3. FastAPI interactive docs and OpenAPI remain enabled by default, exposing the full admin/download API surface to any reachable client.

I also found a legacy credential-storage risk: provider passwords may remain in plaintext in the database until a migration path is triggered.

## Critical Findings

None identified in the code reviewed.

## High Findings

### SBP-001
- Rule ID: FASTAPI-AUTH-001 / secure initial bootstrap boundary
- Severity: High
- Location: `/Users/tylerhereford/repos/catchup-dvr/backend/api/auth.py:77`, `/Users/tylerhereford/repos/catchup-dvr/backend/api/auth.py:247`
- Evidence:

```python
def _is_local_or_private_client(host: str | None) -> bool:
    ...
    return ip.is_loopback or ip.is_private
```

```python
if not settings.allow_remote_setup:
    client_host = request.client.host if request.client else None
    if not _is_local_or_private_client(client_host):
        raise HTTPException(
            status_code=403,
            detail="Initial setup is restricted to local/private network clients",
        )
```

- Impact: On first boot, any device on the same RFC1918 network can race to initialize the admin account and take control of the instance.
- Fix: Restrict bootstrap to loopback by default, or require an out-of-band bootstrap secret/token for any non-loopback setup flow. If LAN bootstrap is intentional, make it opt-in rather than the default behavior behind `allow_remote_setup=False`.
- Mitigation: Bind the setup endpoint to localhost during first-run, or require manual CLI/environment confirmation before accepting network bootstrap requests.
- False positive notes: This matters whenever the service is reachable from other devices on the local network, which is common for self-hosted Docker/LAN deployments.

### SBP-002
- Rule ID: FASTAPI baseline for cookie auth / REACT-CSRF-001
- Severity: High
- Location: `/Users/tylerhereford/repos/catchup-dvr/backend/main.py:228`, `/Users/tylerhereford/repos/catchup-dvr/backend/main.py:236`, `/Users/tylerhereford/repos/catchup-dvr/frontend/src/api.js:5`, `/Users/tylerhereford/repos/catchup-dvr/backend/api/auth.py:470`, `/Users/tylerhereford/repos/catchup-dvr/backend/api/settings.py:174`, `/Users/tylerhereford/repos/catchup-dvr/backend/api/accounts.py:77`
- Evidence:

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(
    AutoSecureSessionMiddleware,
    secret_key=settings.session_secret,
    same_site="lax",
    https_mode=_resolve_session_cookie_secure_mode(),
)
```

```javascript
const config = {
  credentials: 'include',
  headers: {
    'Content-Type': 'application/json',
```

```python
@router.post("/logout")
async def logout_auth(request: Request):
```

```python
@router.put("")
async def update_settings(
```

```python
@router.post("")
async def create_account(
```

- Impact: A victim with an active session can be induced to send authenticated state-changing requests from another site or same-site sibling origin because the app relies on cookies but does not verify a CSRF token, `Origin`, or `Referer`.
- Fix: Add CSRF protection for all cookie-authenticated mutating routes. A practical minimal fix is to require and validate `Origin` on `POST/PUT/PATCH/DELETE`, then add a synchronizer or double-submit CSRF token for defense in depth.
- Mitigation: Keep the cookie `SameSite` policy as strict as product behavior allows and reduce the set of trusted browser origins. Document that CORS is not a CSRF control.
- False positive notes: `SameSite=Lax` reduces some cross-site cases, but it does not replace CSRF defenses for cookie-authenticated browser apps and is not sufficient as the primary control.

## Medium Findings

### SBP-003
- Rule ID: FASTAPI-OPENAPI-001
- Severity: Medium
- Location: `/Users/tylerhereford/repos/catchup-dvr/backend/main.py:86`
- Evidence:

```python
app = FastAPI(
    title=settings.app_name,
    description="Catchup DVR - Xtream Codes Timeshift Downloader",
    version="1.0.0",
    lifespan=lifespan,
)
```

- Impact: FastAPI defaults expose `/docs`, `/redoc`, and `/openapi.json`, which provides unauthenticated clients with a full map of administrative and internal endpoints and lowers the cost of attack discovery.
- Fix: Disable docs/OpenAPI in production with `docs_url=None`, `redoc_url=None`, and `openapi_url=None`, or gate them behind authentication/internal-only routing.
- Mitigation: If docs must remain available, isolate them behind an authenticated reverse-proxy rule or internal network boundary.
- False positive notes: This is lower risk on a purely local desktop install, but it becomes relevant immediately for Docker/LAN exposure.

### SBP-004
- Rule ID: Secure credential storage
- Severity: Medium
- Location: `/Users/tylerhereford/repos/catchup-dvr/backend/models/account.py:13`, `/Users/tylerhereford/repos/catchup-dvr/backend/services/account_credentials.py:20`, `/Users/tylerhereford/repos/catchup-dvr/backend/services/account_credentials.py:36`
- Evidence:

```python
password: Mapped[str] = mapped_column(String(255))
password_encrypted: Mapped[str | None] = mapped_column(String(2048), nullable=True)
```

```python
if account.password:
    return account.password
```

```python
plaintext = account.password
account.password_encrypted = encrypt_account_password(plaintext)
account.password = ""
```

- Impact: Any legacy rows that still use the plaintext `password` column remain decryptable without any crypto boundary until a read path happens to migrate them, increasing the impact of database disclosure or local file compromise.
- Fix: Run an explicit one-time migration at startup or via a maintenance command that encrypts all legacy `password` values and then removes or ignores the plaintext column going forward.
- Mitigation: Add startup telemetry or a health warning when plaintext account credentials still exist, so operators know migration is incomplete.
- False positive notes: Newly created/updated accounts are stored encrypted, so this primarily affects older databases that predate the encrypted field rollout.

## Low Findings

None documented in this pass.

## Recommended Remediation Order

1. Fix first-run bootstrap exposure so non-loopback clients cannot claim a fresh instance by default.
2. Add CSRF protection and request-origin validation for every mutating cookie-authenticated endpoint.
3. Disable or protect FastAPI docs/OpenAPI in non-development deployments.
4. Complete a forced migration away from plaintext legacy provider passwords.

## Notes

- I did not find evidence of unsafe shell execution via `shell=True`, raw HTML injection in the React app, or obvious leakage of encrypted provider credentials through API responses.
- Infrastructure-layer controls such as reverse-proxy auth, WAF rules, CSP headers, or trusted-host enforcement were not visible in this repository and should be verified at deployment time.
