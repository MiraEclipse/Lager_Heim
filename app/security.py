"""Passwörter (Argon2id), Sitzungen, CSRF und Brute-Force-Schutz."""
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from .db import now_iso

_ph = PasswordHasher()  # Argon2id mit Standardparametern
# Vergleichshash, damit unbekannte Benutzernamen gleich lange brauchen
_DUMMY_HASH = _ph.hash(secrets.token_hex(16))

MIN_PW_LEN = 8


def hash_password(pw: str) -> str:
    return _ph.hash(pw)


def verify_password(pw_hash: str | None, pw: str) -> bool:
    try:
        return _ph.verify(pw_hash or _DUMMY_HASH, pw) and pw_hash is not None
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def check_password_policy(pw: str) -> str | None:
    if len(pw) < MIN_PW_LEN:
        return f"Passwort muss mindestens {MIN_PW_LEN} Zeichen lang sein."
    if len(pw) > 256:
        return "Passwort ist zu lang."
    return None


def new_token() -> str:
    return secrets.token_urlsafe(32)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def tokens_equal(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())


def parse_iso(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------- Brute-Force
def lock_remaining(conn, keys: list[str]) -> int:
    """Sekunden, die einer der Schlüssel noch gesperrt ist (0 = frei)."""
    remaining = 0
    for k in keys:
        r = conn.execute("SELECT locked_until FROM login_attempts WHERE key = ?", (k,)).fetchone()
        if r and r["locked_until"]:
            delta = (parse_iso(r["locked_until"]) - _now()).total_seconds()
            remaining = max(remaining, int(delta) + 1 if delta > 0 else 0)
    return remaining


def register_failure(conn, keys: list[str], max_fails: int, base_s: int, max_s: int) -> None:
    for k in keys:
        r = conn.execute("SELECT fails FROM login_attempts WHERE key = ?", (k,)).fetchone()
        fails = (r["fails"] if r else 0) + 1
        locked_until = None
        if fails >= max_fails:
            # exponentiell wachsende Sperre: 60 s, 120 s, 240 s … bis max_s
            secs = min(base_s * (2 ** (fails - max_fails)), max_s)
            locked_until = (_now() + timedelta(seconds=secs)).isoformat().replace("+00:00", "Z")
        conn.execute(
            "INSERT INTO login_attempts(key, fails, locked_until) VALUES (?,?,?) "
            "ON CONFLICT(key) DO UPDATE SET fails = excluded.fails, locked_until = excluded.locked_until",
            (k, fails, locked_until),
        )


def clear_failures(conn, keys: list[str]) -> None:
    for k in keys:
        conn.execute("DELETE FROM login_attempts WHERE key = ?", (k,))


# ---------------------------------------------------------------- Sitzungen
def create_session(conn, user_id: int, ip: str) -> tuple[str, str]:
    token = new_token()
    csrf = new_token()
    ts = now_iso()
    conn.execute(
        "INSERT INTO sessions(token_hash, user_id, csrf_token, created_at, last_seen, ip) VALUES (?,?,?,?,?,?)",
        (token_hash(token), user_id, csrf, ts, ts, ip),
    )
    return token, csrf


def session_expired(last_seen: str, timeout_min: int) -> bool:
    return _now() - parse_iso(last_seen) > timedelta(minutes=timeout_min)
