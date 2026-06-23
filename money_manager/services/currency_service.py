from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

from money_manager.config.paths import CURRENCIES_JSON
from money_manager.security.secure_storage import read_json_secure, write_json_secure

BASE_CURRENCY = "EUR"
FRANKFURTER_V2_RATES_URL = "https://api.frankfurter.dev/v2/rates"
FRANKFURTER_V1_LATEST_URL = "https://api.frankfurter.dev/v1/latest"

DEFAULT_CURRENCIES = [
    {"code": "EUR", "name": "Euro", "rate_to_eur": 1.0, "correction_to_eur": 0.0, "source": "fixed", "active": True},
    {"code": "USD", "name": "US Dollar", "rate_to_eur": 0.92, "correction_to_eur": 0.0, "source": "default", "active": True},
    {"code": "GBP", "name": "British Pound", "rate_to_eur": 1.17, "correction_to_eur": 0.0, "source": "default", "active": True},
    {"code": "CHF", "name": "Swiss Franc", "rate_to_eur": 1.04, "correction_to_eur": 0.0, "source": "default", "active": True},
    {"code": "SEK", "name": "Swedish Krona", "rate_to_eur": 0.091, "correction_to_eur": 0.0, "source": "default", "active": True},
    {"code": "NOK", "name": "Norwegian Krone", "rate_to_eur": 0.087, "correction_to_eur": 0.0, "source": "default", "active": True},
    {"code": "DKK", "name": "Danish Krone", "rate_to_eur": 0.134, "correction_to_eur": 0.0, "source": "default", "active": True},
    {"code": "CAD", "name": "Canadian Dollar", "rate_to_eur": 0.67, "correction_to_eur": 0.0, "source": "default", "active": True},
    {"code": "AUD", "name": "Australian Dollar", "rate_to_eur": 0.60, "correction_to_eur": 0.0, "source": "default", "active": True},
    {"code": "JPY", "name": "Japanese Yen", "rate_to_eur": 0.0059, "correction_to_eur": 0.0, "source": "default", "active": True},
]


def load_currency_settings() -> dict:
    """Load the local currency table, creating a EUR-based default table if needed."""
    path = Path(CURRENCIES_JSON)
    if not path.exists():
        payload = _default_payload()
        _write_payload(payload)
        return payload

    try:
        payload = read_json_secure(path, None)
    except Exception:
        payload = None
    if payload is None:
        payload = _default_payload()
        _write_payload(payload)
        return payload

    if not isinstance(payload, dict):
        payload = _default_payload()

    payload.setdefault("base", BASE_CURRENCY)
    payload.setdefault("last_refresh_attempt", "")
    payload.setdefault("last_successful_refresh", "")
    payload.setdefault("last_error", "")
    payload["currencies"] = _merge_with_defaults(payload.get("currencies", []))
    return payload


def load_currencies(active_only: bool = False) -> list[dict]:
    rows = load_currency_settings().get("currencies", [])
    normalized = [_normalize_currency_row(row) for row in rows]
    normalized = [row for row in normalized if row is not None]
    if active_only:
        normalized = [row for row in normalized if row.get("active", True)]
    return sorted(normalized, key=lambda row: (row["code"] != BASE_CURRENCY, row["code"]))


def page_context() -> dict:
    payload = load_currency_settings()
    rows = load_currencies(active_only=False)
    for row in rows:
        row["effective_rate_to_eur"] = effective_rate(row)
        row["eur_for_100"] = 100.0 * row["effective_rate_to_eur"]
        row["status_tone"] = "main" if row["code"] == BASE_CURRENCY else ("positive" if row.get("active", True) else "neutral")
    active_count = sum(1 for row in rows if row.get("active", True))
    return {
        "base_currency": BASE_CURRENCY,
        "currencies": rows,
        "active_count": active_count,
        "last_refresh_attempt": payload.get("last_refresh_attempt", ""),
        "last_successful_refresh": payload.get("last_successful_refresh", ""),
        "last_error": payload.get("last_error", ""),
    }


def refresh_currency_rates(force: bool = True) -> dict:
    """Best-effort web refresh from Frankfurter.

    The local table remains the source of truth for manual correction factors.
    Web data updates only the base rate_to_eur; correction_to_eur is preserved.
    """
    payload = load_currency_settings()
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    payload["last_refresh_attempt"] = now

    wanted_codes = {row["code"] for row in load_currencies(active_only=False) if row["code"] != BASE_CURRENCY}
    rates = _fetch_frankfurter_rates(wanted_codes)
    if not rates:
        payload["last_error"] = "Could not refresh exchange rates. Keeping local/default rates."
        _write_payload(payload)
        return payload

    rows = []
    for row in payload.get("currencies", []):
        clean = _normalize_currency_row(row)
        if clean is None:
            continue
        code = clean["code"]
        if code in rates:
            clean["rate_to_eur"] = rates[code]
            clean["source"] = "Frankfurter"
            clean["updated_at"] = now
        elif code == BASE_CURRENCY:
            clean["rate_to_eur"] = 1.0
            clean["source"] = "fixed"
            clean["updated_at"] = now
        rows.append(clean)

    payload["currencies"] = rows
    payload["last_successful_refresh"] = now
    payload["last_error"] = ""
    _write_payload(payload)
    return payload


def update_currency_from_form(form) -> None:
    code = _clean_code(form.get("code"))
    if not code:
        return
    payload = load_currency_settings()
    rows = []
    updated = False
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    for row in payload.get("currencies", []):
        clean = _normalize_currency_row(row)
        if clean is None:
            continue
        if clean["code"] == code:
            if code == BASE_CURRENCY:
                clean["rate_to_eur"] = 1.0
                clean["correction_to_eur"] = 0.0
                clean["active"] = True
            else:
                clean["name"] = str(form.get("name") or clean.get("name") or code).strip() or code
                clean["rate_to_eur"] = _safe_float(form.get("rate_to_eur"), clean.get("rate_to_eur", 1.0))
                clean["correction_to_eur"] = _safe_float(form.get("correction_to_eur"), clean.get("correction_to_eur", 0.0))
                clean["active"] = str(form.get("active", "")).lower() in {"1", "true", "yes", "on"}
                clean["source"] = "manual"
                clean["updated_at"] = now
            updated = True
        rows.append(clean)

    if updated:
        payload["currencies"] = rows
        _write_payload(payload)


def add_currency_from_form(form) -> None:
    code = _clean_code(form.get("code"))
    if not code:
        return
    payload = load_currency_settings()
    rows = [_normalize_currency_row(row) for row in payload.get("currencies", [])]
    rows = [row for row in rows if row is not None]

    existing_codes = {row["code"] for row in rows}
    row = {
        "code": code,
        "name": str(form.get("name") or code).strip() or code,
        "rate_to_eur": 1.0 if code == BASE_CURRENCY else _safe_float(form.get("rate_to_eur"), 1.0),
        "correction_to_eur": 0.0 if code == BASE_CURRENCY else _safe_float(form.get("correction_to_eur"), 0.0),
        "source": "manual",
        "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "active": True,
    }

    if code in existing_codes:
        rows = [row if existing["code"] == code else existing for existing in rows]
    else:
        rows.append(row)
    payload["currencies"] = rows
    _write_payload(payload)


def currency_options_for_forms() -> list[dict]:
    rows = load_currencies(active_only=True)
    options = []
    for row in rows:
        options.append({
            "code": row["code"],
            "name": row.get("name", row["code"]),
            "rate_to_eur": row["rate_to_eur"],
            "correction_to_eur": row["correction_to_eur"],
            "effective_rate_to_eur": effective_rate(row),
            "label": f"{row['code']} · {row.get('name', row['code'])}",
        })
    if not any(option["code"] == BASE_CURRENCY for option in options):
        options.insert(0, {"code": BASE_CURRENCY, "name": "Euro", "rate_to_eur": 1.0, "correction_to_eur": 0.0, "effective_rate_to_eur": 1.0, "label": "EUR · Euro"})
    return options


def convert_amount_to_eur(amount: float, currency_code: str | None) -> dict:
    code = _clean_code(currency_code) or BASE_CURRENCY
    original_amount = _safe_float(amount, 0.0)
    row = currency_by_code(code)
    if row is None:
        code = BASE_CURRENCY
        row = currency_by_code(BASE_CURRENCY) or _normalize_currency_row(DEFAULT_CURRENCIES[0])

    rate = float(row.get("rate_to_eur", 1.0) or 1.0)
    correction = float(row.get("correction_to_eur", 0.0) or 0.0)
    eff = effective_rate(row)
    converted = original_amount * eff
    return {
        "original_amount": original_amount,
        "original_currency": code,
        "rate_to_eur": rate,
        "correction_to_eur": correction,
        "effective_rate_to_eur": eff,
        "amount_eur": round(converted + 1e-9, 2),
        "is_conversion": code != BASE_CURRENCY,
    }


def append_conversion_note(description: str, conversion: dict) -> str:
    base = str(description or "").strip()
    if not conversion.get("is_conversion"):
        return base
    note = (
        f"Original: {conversion['original_amount']:.2f} {conversion['original_currency']} → "
        f"€ {conversion['amount_eur']:.2f} "
        f"(rate {conversion['rate_to_eur']:.6f} + correction {conversion['correction_to_eur']:.6f}; "
        f"effective {conversion['effective_rate_to_eur']:.6f})."
    )
    return f"{base}\n{note}" if base else note


def currency_by_code(code: str | None) -> dict | None:
    wanted = _clean_code(code)
    for row in load_currencies(active_only=False):
        if row["code"] == wanted:
            return row
    return None


def effective_rate(row: dict) -> float:
    rate = _safe_float(row.get("rate_to_eur"), 1.0)
    correction = _safe_float(row.get("correction_to_eur"), 0.0)
    if str(row.get("code", "")).upper() == BASE_CURRENCY:
        return 1.0
    return max(0.0, rate + correction)


def _fetch_frankfurter_rates(codes: set[str]) -> dict[str, float]:
    if not codes:
        return {}
    for url in (FRANKFURTER_V2_RATES_URL, FRANKFURTER_V1_LATEST_URL):
        try:
            req = Request(url, headers={"User-Agent": "MoneyManager/1.0"})
            with urlopen(req, timeout=5) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except Exception:
            continue
        rates = _parse_frankfurter_payload(payload, codes)
        if rates:
            return rates
    return {}


def _parse_frankfurter_payload(payload, codes: set[str]) -> dict[str, float]:
    rates: dict[str, float] = {}

    # v2 /rates returns a list of rows: {base: EUR, quote: USD, rate: 1.08}.
    if isinstance(payload, list):
        for item in payload:
            if not isinstance(item, dict):
                continue
            base = _clean_code(item.get("base"))
            quote = _clean_code(item.get("quote"))
            rate = _safe_float(item.get("rate"), 0.0)
            if base == BASE_CURRENCY and quote in codes and rate > 0:
                rates[quote] = 1.0 / rate
            elif quote == BASE_CURRENCY and base in codes and rate > 0:
                rates[base] = rate
        return rates

    # v1 /latest returns {base: EUR, rates: {USD: 1.08}}.
    if isinstance(payload, dict):
        base = _clean_code(payload.get("base"))
        raw_rates = payload.get("rates", {})
        if base == BASE_CURRENCY and isinstance(raw_rates, dict):
            for code, value in raw_rates.items():
                clean = _clean_code(code)
                rate = _safe_float(value, 0.0)
                if clean in codes and rate > 0:
                    rates[clean] = 1.0 / rate
        elif isinstance(raw_rates, dict):
            eur_per_base = _safe_float(raw_rates.get(BASE_CURRENCY), 0.0)
            if base in codes and eur_per_base > 0:
                rates[base] = eur_per_base
    return rates


def _merge_with_defaults(rows) -> list[dict]:
    normalized = []
    seen = set()
    for row in rows if isinstance(rows, list) else []:
        clean = _normalize_currency_row(row)
        if clean is None or clean["code"] in seen:
            continue
        normalized.append(clean)
        seen.add(clean["code"])
    for default in DEFAULT_CURRENCIES:
        code = default["code"]
        if code not in seen:
            normalized.append(_normalize_currency_row(default))
            seen.add(code)
    return [row for row in normalized if row is not None]


def _normalize_currency_row(row) -> dict | None:
    if not isinstance(row, dict):
        return None
    code = _clean_code(row.get("code"))
    if not code:
        return None
    if code == BASE_CURRENCY:
        return {
            "code": BASE_CURRENCY,
            "name": str(row.get("name") or "Euro").strip() or "Euro",
            "rate_to_eur": 1.0,
            "correction_to_eur": 0.0,
            "source": str(row.get("source") or "fixed"),
            "updated_at": str(row.get("updated_at") or ""),
            "active": True,
        }
    return {
        "code": code,
        "name": str(row.get("name") or code).strip() or code,
        "rate_to_eur": _safe_float(row.get("rate_to_eur"), 1.0),
        "correction_to_eur": _safe_float(row.get("correction_to_eur"), 0.0),
        "source": str(row.get("source") or "manual"),
        "updated_at": str(row.get("updated_at") or ""),
        "active": _truthy(row.get("active", True)),
    }


def _default_payload() -> dict:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    rows = []
    for row in DEFAULT_CURRENCIES:
        clean = _normalize_currency_row({**row, "updated_at": now})
        if clean is not None:
            rows.append(clean)
    return {
        "base": BASE_CURRENCY,
        "currencies": rows,
        "last_refresh_attempt": "",
        "last_successful_refresh": "",
        "last_error": "",
    }


def _write_payload(payload: dict) -> None:
    path = Path(CURRENCIES_JSON)
    path.parent.mkdir(exist_ok=True, parents=True)
    payload["currencies"] = _merge_with_defaults(payload.get("currencies", []))
    write_json_secure(path, payload)
    try:
        from money_manager.services.cache_service import notify_data_changed

        notify_data_changed()
    except Exception:
        pass


def _clean_code(value) -> str:
    return str(value or "").strip().upper()


def _safe_float(value, default=0.0) -> float:
    try:
        return float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return float(default)


def _truthy(value) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}
