"""
license_manager.py — License validation via Keygen.sh

Flow:
  1. App starts → check cached license
  2. No cache / expired → show activation window
  3. User enters key → validate + activate machine via Keygen.sh API
  4. Key is device-limited (max machines set in Keygen.sh policy)
  5. Key expires after N days (set in policy)

Keygen.sh free tier supports up to 100 activations — plenty for indie use.
"""
from __future__ import annotations

import hashlib
import json
import platform
import socket
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import requests

# ── Your Keygen.sh credentials ────────────────────────────────────────────────
# Sign up at https://app.keygen.sh → Settings → copy your Account ID
KEYGEN_ACCOUNT_ID = "33e8f944-6a41-47a3-bc20-1b6aa875869f"

# ── Local cache ───────────────────────────────────────────────────────────────
# Stored in the user's home folder — survives app updates
CACHE_PATH = Path.home() / ".ui_macro_tool" / "activation.json"

# Re-validate online if fewer than this many days remain (keeps expiry accurate)
REVALIDATE_THRESHOLD_DAYS = 2

BASE_URL = f"https://api.keygen.sh/v1/accounts/{KEYGEN_ACCOUNT_ID}"


# ── Result codes ──────────────────────────────────────────────────────────────

class LicenseResult:
    def __init__(self, success: bool, message: str, days_remaining: Optional[int] = None):
        self.success       = success
        self.message       = message
        self.days_remaining = days_remaining

    def __bool__(self) -> bool:
        return self.success


# ── Manager ───────────────────────────────────────────────────────────────────

class LicenseManager:

    # ── Machine fingerprint ───────────────────────────────────────────────────

    def fingerprint(self) -> str:
        """
        Stable machine identifier: SHA-256 of MAC address + hostname + platform.
        Different on every machine; survives reboots and app reinstalls.
        """
        raw = f"{uuid.getnode()}::{socket.gethostname()}::{platform.system()}"
        return hashlib.sha256(raw.encode()).hexdigest()[:40]

    # ── Keygen.sh API calls ───────────────────────────────────────────────────

    def _validate_key(self, key: str) -> dict:
        """Call Keygen.sh validate-key endpoint."""
        resp = requests.post(
            f"{BASE_URL}/licenses/actions/validate-key",
            headers={
                "Content-Type": "application/vnd.api+json",
                "Accept":       "application/vnd.api+json",
            },
            json={
                "meta": {
                    "key":   key,
                    "scope": {"fingerprint": self.fingerprint()},
                }
            },
            timeout=12,
        )
        return resp.json()

    def _activate_machine(self, key: str, license_id: str) -> dict:
        """Register this machine against the license."""
        resp = requests.post(
            f"{BASE_URL}/machines",
            headers={
                "Authorization": f"License {key}",
                "Content-Type":  "application/vnd.api+json",
                "Accept":        "application/vnd.api+json",
            },
            json={
                "data": {
                    "type": "machines",
                    "attributes": {
                        "fingerprint": self.fingerprint(),
                        "name":        socket.gethostname(),
                        "platform":    platform.system(),
                    },
                    "relationships": {
                        "license": {
                            "data": {"type": "licenses", "id": license_id}
                        }
                    },
                }
            },
            timeout=12,
        )
        return resp.json()

    # ── Cache ─────────────────────────────────────────────────────────────────

    def _save_cache(self, key: str, expiry: Optional[str]) -> None:
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        CACHE_PATH.write_text(json.dumps({
            "key":         key,
            "expiry":      expiry,
            "fingerprint": self.fingerprint(),
        }))

    def _load_cache(self) -> Optional[dict]:
        if not CACHE_PATH.exists():
            return None
        try:
            data = json.loads(CACHE_PATH.read_text())
            # Cache is only valid for THIS machine
            if data.get("fingerprint") != self.fingerprint():
                return None
            return data
        except Exception:
            return None

    def clear_cache(self) -> None:
        if CACHE_PATH.exists():
            CACHE_PATH.unlink()

    # ── Expiry helper ─────────────────────────────────────────────────────────

    def _days_remaining(self, expiry: Optional[str]) -> Optional[int]:
        if not expiry:
            return None
        try:
            exp = datetime.fromisoformat(expiry.replace("Z", "+00:00"))
            now = datetime.now(timezone.utc)
            return max(0, (exp - now).days)
        except Exception:
            return None

    # ── Public API ────────────────────────────────────────────────────────────

    def activate(self, key: str) -> LicenseResult:
        """
        Validate the key and activate this machine.
        Called when the user clicks Activate in the license window.
        """
        if KEYGEN_ACCOUNT_ID == "YOUR_ACCOUNT_ID_HERE":
            return LicenseResult(False,
                "Keygen.sh account not configured.\n"
                "Open license_manager.py and set KEYGEN_ACCOUNT_ID.")

        try:
            resp   = self._validate_key(key)
            meta   = resp.get("meta", {})
            code   = meta.get("code", "UNKNOWN")
            valid  = meta.get("valid", False)
            attrs  = resp.get("data", {}).get("attributes", {}) if resp.get("data") else {}
            lic_id = resp.get("data", {}).get("id")
            expiry = attrs.get("expiry")

            # ── Already valid on this machine ─────────────────────────────
            if valid:
                days = self._days_remaining(expiry)
                self._save_cache(key, expiry)
                return LicenseResult(True,
                    f"License active — {days} day(s) remaining." if days is not None
                    else "License active.",
                    days)

            # ── Need to activate this machine ─────────────────────────────
            if code == "FINGERPRINT_SCOPE_MISMATCH" and lic_id:
                act = self._activate_machine(key, lic_id)
                if "errors" not in act:
                    days = self._days_remaining(expiry)
                    self._save_cache(key, expiry)
                    return LicenseResult(True,
                        f"Activated! {days} day(s) remaining." if days is not None
                        else "Activated!",
                        days)
                # Activation rejected
                err_code = act.get("errors", [{}])[0].get("code", "")
                if err_code in ("MACHINE_LIMIT_EXCEEDED", "TOO_MANY_MACHINES"):
                    return LicenseResult(False,
                        "This key is already active on the maximum number of devices.\n"
                        "Please purchase a new key.")
                return LicenseResult(False, f"Activation failed ({err_code}).")

            # ── Specific error messages ───────────────────────────────────
            messages = {
                "EXPIRED":           "This license has expired. Please purchase a new key.",
                "TOO_MANY_MACHINES": "Device limit reached. Purchase a new key.",
                "SUSPENDED":         "This license has been suspended.",
                "BANNED":            "This license is banned.",
                "NOT_FOUND":         "Invalid key — please check and try again.",
                "NO_MACHINES":       "No machines activated. Contact support.",
            }
            return LicenseResult(False, messages.get(code, f"License error ({code})."))

        except requests.exceptions.ConnectionError:
            return LicenseResult(False,
                "No internet connection.\nPlease connect to the internet and try again.")
        except requests.exceptions.Timeout:
            return LicenseResult(False,
                "Connection timed out. Please try again.")
        except Exception as exc:
            return LicenseResult(False, f"Unexpected error: {exc}")

    def check_cached(self) -> LicenseResult:
        """
        Check if a valid license is already cached for this machine.
        Called at every app startup to avoid showing the activation window.
        """
        cached = self._load_cache()
        if not cached:
            return LicenseResult(False, "No license found.")

        key    = cached.get("key", "")
        expiry = cached.get("expiry")
        days   = self._days_remaining(expiry)

        # Locally expired
        if days is not None and days <= 0:
            self.clear_cache()
            return LicenseResult(False,
                "Your license has expired. Please enter a new key.", 0)

        # Re-validate online when close to expiry (keeps the expiry date accurate)
        if days is not None and days <= REVALIDATE_THRESHOLD_DAYS:
            try:
                result = self.activate(key)
                return result
            except Exception:
                pass   # No internet — trust the cache for now

        return LicenseResult(True,
            f"License active — {days} day(s) remaining." if days is not None
            else "License active.",
            days)
