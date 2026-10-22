"""Anmeldung und Benutzerverwaltung."""
import re

from . import audit, perms, security
from .db import now_iso, one, rows, write_tx
from .errors import AppError, Forbidden, NotFound

USERNAME_RE = re.compile(r"^[A-Za-z0-9._-]{3,32}$")
GENERIC_LOGIN_ERROR = "Benutzername oder Passwort falsch."


class LoginError(AppError):
    pass


def public(u: dict) -> dict:
    return {"id": u["id"], "username": u["username"], "role": u["role"], "active": bool(u["active"]),
            "must_change_pw": bool(u["must_change_pw"]), "created_at": u["created_at"],
            "last_login": u["last_login"]}


def login(conn, cfg, username: str, password: str, ip: str) -> tuple[dict, str, str]:
    username = (username or "").strip()[:64]
    keys = [f"u:{username.lower()}", f"ip:{ip}"]
    error = None
    with write_tx(conn):
        remaining = security.lock_remaining(conn, keys)
        if remaining:
            audit.append(conn, None, "LOGIN_GESPERRT", "BENUTZER", username,
                         new={"benutzer": username, "sperre_sekunden": remaining}, ip=ip)
            error = LoginError(f"Zu viele Fehlversuche. Bitte {remaining} Sekunden warten.", 429)
        else:
            user = one(conn.execute("SELECT * FROM users WHERE username = ?", (username,)))
            ok = security.verify_password(user["pw_hash"] if user else None, password or "")
            if not ok or not user["active"]:
                security.register_failure(conn, keys, cfg.login_max_fails, cfg.login_lock_base_s,
                                          cfg.login_lock_max_s)
                reason = "Konto gesperrt" if ok else "falsches Passwort oder unbekannter Benutzer"
                audit.append(conn, None, "LOGIN_FEHLGESCHLAGEN", "BENUTZER", username,
                             new={"benutzer": username, "grund": reason}, ip=ip)
                error = LoginError(GENERIC_LOGIN_ERROR, 401)
            else:
                security.clear_failures(conn, keys)
                conn.execute("DELETE FROM sessions WHERE last_seen < datetime('now', '-1 day')")
                token, csrf = security.create_session(conn, user["id"], ip)
                conn.execute("UPDATE users SET last_login = ? WHERE id = ?", (now_iso(), user["id"]))
                audit.append(conn, user, "LOGIN", "BENUTZER", user["id"], new={"benutzer": user["username"]},
                             ip=ip)
    if error:
        raise error
    return user, token, csrf


def logout(conn, user: dict, token: str, ip: str, reason: str = "LOGOUT") -> None:
    with write_tx(conn):
        conn.execute("DELETE FROM sessions WHERE token_hash = ?", (security.token_hash(token),))
        audit.append(conn, user, reason, "BENUTZER", user["id"], ip=ip)


def list_users(conn, actor: dict) -> list[dict]:
    perms.require(conn, actor, perms.BENUTZER)
    return [public(u) for u in rows(conn.execute("SELECT * FROM users ORDER BY username"))]


def create_user(conn, actor: dict | None, username: str, password: str, ip: str, role: str = perms.USER) -> dict:
    if actor is not None:
        perms.require(conn, actor, perms.BENUTZER)
        role = perms.USER  # über die Oberfläche nur normale Benutzer – es gibt genau einen Admin
    username = (username or "").strip()
    if not USERNAME_RE.match(username):
        raise AppError("Benutzername: 3–32 Zeichen, nur Buchstaben, Ziffern, Punkt, Minus, Unterstrich.")
    err = security.check_password_policy(password or "")
    if err:
        raise AppError(err)
    with write_tx(conn):
        if role == perms.ADMIN and one(conn.execute("SELECT 1 FROM users WHERE role = 'ADMIN'")):
            raise AppError("Es existiert bereits ein Admin.")
        if one(conn.execute("SELECT 1 FROM users WHERE username = ?", (username,))):
            raise AppError("Benutzername ist bereits vergeben.")
        cur = conn.execute(
            "INSERT INTO users(username, pw_hash, role, active, must_change_pw, created_at) VALUES (?,?,?,?,?,?)",
            (username, security.hash_password(password), role, 1, 0 if role == perms.ADMIN else 1, now_iso()))
        u = one(conn.execute("SELECT * FROM users WHERE id = ?", (cur.lastrowid,)))
        audit.append(conn, actor, "BENUTZER_ANGELEGT", "BENUTZER", u["id"], old=None,
                     new={"benutzer": username, "rolle": role, "aktiv": True}, ip=ip)
    return public(u)


def update_user(conn, actor: dict, user_id: int, data: dict, ip: str) -> dict:
    perms.require(conn, actor, perms.BENUTZER)
    with write_tx(conn):
        u = one(conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)))
        if not u:
            raise NotFound("Benutzer nicht gefunden.")
        if u["role"] == perms.ADMIN and ("active" in data or "password" in data):
            raise Forbidden("Das Admin-Konto kann hier nicht gesperrt oder zurückgesetzt werden "
                            "(eigenes Passwort über „Passwort ändern“).")
        if "active" in data:
            active = 1 if data["active"] else 0
            if active != u["active"]:
                conn.execute("UPDATE users SET active = ? WHERE id = ?", (active, user_id))
                if not active:
                    conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
                audit.append(conn, actor, "BENUTZER_ENTSPERRT" if active else "BENUTZER_GESPERRT", "BENUTZER",
                             user_id, old={"aktiv": bool(u["active"])}, new={"aktiv": bool(active)}, ip=ip)
        if data.get("password"):
            err = security.check_password_policy(data["password"])
            if err:
                raise AppError(err)
            conn.execute("UPDATE users SET pw_hash = ?, must_change_pw = 1 WHERE id = ?",
                         (security.hash_password(data["password"]), user_id))
            conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
            audit.append(conn, actor, "PASSWORT_ZURUECKGESETZT", "BENUTZER", user_id,
                         new={"benutzer": u["username"]}, ip=ip)
        if data.get("unlock"):
            security.clear_failures(conn, [f"u:{u['username'].lower()}"])
            audit.append(conn, actor, "LOGINSPERRE_AUFGEHOBEN", "BENUTZER", user_id,
                         new={"benutzer": u["username"]}, ip=ip)
        u = one(conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)))
    return public(u)


def change_own_password(conn, user: dict, old_pw: str, new_pw: str, ip: str) -> None:
    err = security.check_password_policy(new_pw or "")
    if err:
        raise AppError(err)
    if old_pw == new_pw:
        raise AppError("Neues Passwort muss sich vom alten unterscheiden.")
    with write_tx(conn):
        u = one(conn.execute("SELECT * FROM users WHERE id = ?", (user["id"],)))
        if not security.verify_password(u["pw_hash"], old_pw or ""):
            raise AppError("Altes Passwort ist falsch.")
        conn.execute("UPDATE users SET pw_hash = ?, must_change_pw = 0 WHERE id = ?",
                     (security.hash_password(new_pw), user["id"]))
        audit.append(conn, user, "PASSWORT_GEAENDERT", "BENUTZER", user["id"], ip=ip)
