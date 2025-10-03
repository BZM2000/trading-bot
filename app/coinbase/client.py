from __future__ import annotations

import base64
import binascii
import secrets
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

import httpx
import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec, ed25519

from app.config import Settings, get_settings


COINBASE_API_BASE = "https://api.coinbase.com"


class CoinbaseAPIError(RuntimeError):
    def __init__(self, status_code: int, content: Any):
        super().__init__(f"Coinbase API error {status_code}: {content}")
        self.status_code = status_code
        self.content = content


@dataclass(slots=True)
class BestBidAsk:
    product_id: str
    best_bid: str
    best_ask: str
    price: str
    time: datetime


@dataclass(slots=True)
class Product:
    product_id: str
    base_increment: str
    quote_increment: str
    base_min_size: str
    base_max_size: Optional[str]
    quote_min_size: Optional[str]
    quote_max_size: Optional[str]
    status: Optional[str] = None


@dataclass(slots=True)
class Candle:
    start: datetime
    low: float
    high: float
    open: float
    close: float
    volume: float


class CoinbaseClient:
    """Thin wrapper around Coinbase Advanced Trade REST endpoints."""

    def __init__(
        self,
        *,
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None,
        signing_algorithm: Optional[str] = None,
        settings: Optional[Settings] = None,
        base_url: str = COINBASE_API_BASE,
        timeout: float = 15.0,
        client: Optional[httpx.AsyncClient] = None,
    ) -> None:
        settings = settings or get_settings()
        self.api_key = api_key or settings.coinbase_api_key
        self.api_secret = api_secret or settings.coinbase_api_secret
        self.signing_algorithm = (signing_algorithm or settings.coinbase_signing_algorithm).lower()
        self.base_url = base_url.rstrip("/")
        if not self.api_key or not self.api_secret:
            raise ValueError("Coinbase API credentials are not configured")
        self._secret_bytes = self._decode_secret(self.api_secret)
        self._ed25519_private_key: ed25519.Ed25519PrivateKey | None = None
        self._ecdsa_private_key: ec.EllipticCurvePrivateKey | None = None
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(base_url=self.base_url, timeout=timeout)

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def __aenter__(self) -> "CoinbaseClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:  # type: ignore[override]
        await self.close()

    async def get_best_bid_ask(self, product_id: str) -> BestBidAsk:
        payload = await self._request("GET", "/api/v3/brokerage/best_bid_ask", params={"product_ids": product_id})
        if not payload.get("pricebooks"):
            raise CoinbaseAPIError(404, payload)
        data = payload["pricebooks"][0]
        ts = self._parse_timestamp(data.get("time"))
        return BestBidAsk(
            product_id=data["product_id"],
            best_bid=data["bids"][0]["price"] if data["bids"] else data.get("price", "0"),
            best_ask=data["asks"][0]["price"] if data["asks"] else data.get("price", "0"),
            price=data.get("price", "0"),
            time=ts,
        )

    async def get_product(self, product_id: str) -> Product:
        payload = await self._request("GET", f"/api/v3/brokerage/products/{product_id}")
        return Product(
            product_id=payload["product_id"],
            base_increment=payload["base_increment"],
            quote_increment=payload["quote_increment"],
            base_min_size=payload["base_min_size"],
            base_max_size=payload.get("base_max_size"),
            quote_min_size=payload.get("quote_min_size"),
            quote_max_size=payload.get("quote_max_size"),
            status=payload.get("status"),
        )

    async def get_product_candles(
        self,
        product_id: str,
        *,
        granularity: str = "FIVE_MINUTE",
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
        limit: int = 300,
    ) -> list[Candle]:
        params: dict[str, Any] = {
            "product_id": product_id,
            "granularity": granularity,
            "limit": limit,
        }
        if start:
            params["start"] = start.astimezone(timezone.utc).isoformat()
        if end:
            params["end"] = end.astimezone(timezone.utc).isoformat()

        payload = await self._request("GET", f"/api/v3/brokerage/products/{product_id}/candles", params=params)
        candles: list[Candle] = []
        for entry in payload.get("candles", []):
            candles.append(
                Candle(
                    start=self._parse_timestamp(entry.get("start")),
                    low=float(entry["low"]),
                    high=float(entry["high"]),
                    open=float(entry["open"]),
                    close=float(entry["close"]),
                    volume=float(entry["volume"]),
                )
            )
        candles.sort(key=lambda c: c.start)
        return candles

    async def list_fills(
        self,
        *,
        product_id: Optional[str] = None,
        order_ids: Optional[Iterable[str]] = None,
        limit: int = 100,
        cursor: Optional[str] = None,
        return_payload: bool = False,
    ) -> Any:
        params: dict[str, Any] = {"limit": limit}
        if product_id:
            params["product_id"] = product_id
        if order_ids:
            params["order_ids"] = ",".join(order_ids)
        if cursor:
            params["cursor"] = cursor
        payload = await self._request("GET", "/api/v3/brokerage/orders/historical/fills", params=params)
        if return_payload:
            return payload
        return payload.get("fills", [])

    async def list_orders(
        self,
        *,
        product_id: Optional[str] = None,
        order_status: Optional[list[str]] = None,
        limit: int = 100,
        cursor: Optional[str] = None,
        return_payload: bool = False,
    ) -> Any:
        statuses = [status.upper() for status in order_status] if order_status else None
        if statuses and "OPEN" in statuses and len(statuses) > 1:
            non_open = [status for status in statuses if status != "OPEN"]
            combined: list[dict[str, Any]] = []
            combined.extend(
                await self.list_orders(
                    product_id=product_id,
                    order_status=["OPEN"],
                    limit=limit,
                    cursor=cursor,
                )
            )
            if non_open:
                combined.extend(
                    await self.list_orders(product_id=product_id, order_status=non_open, limit=limit)
                )
            deduped: list[dict[str, Any]] = []
            seen: set[str] = set()
            for order in combined:
                order_id = order.get("order_id")
                if order_id and order_id in seen:
                    continue
                if order_id:
                    seen.add(order_id)
                deduped.append(order)
            return deduped

        params: dict[str, Any] = {"limit": limit}
        if product_id:
            params["product_id"] = product_id
        if statuses:
            params["order_status"] = statuses
        if cursor:
            params["cursor"] = cursor
        payload = await self._request("GET", "/api/v3/brokerage/orders/historical/batch", params=params)
        if return_payload:
            return payload
        return payload.get("orders", [])

    async def create_order(self, order: dict[str, Any]) -> dict[str, Any]:
        return await self._request("POST", "/api/v3/brokerage/orders", json_body=order)

    async def cancel_orders(self, order_ids: Iterable[str]) -> dict[str, Any]:
        return await self._request(
            "POST",
            "/api/v3/brokerage/orders/batch_cancel",
            json_body={"order_ids": list(order_ids)},
        )

    async def list_accounts(
        self,
        *,
        cursor: Optional[str] = None,
        limit: int = 250,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"limit": limit}
        if cursor:
            params["cursor"] = cursor
        return await self._request("GET", "/api/v3/brokerage/accounts", params=params)

    def _decode_secret(self, secret: str) -> bytes:
        try:
            return base64.b64decode(secret)
        except (binascii.Error, ValueError):
            return secret.encode("utf-8")

    def _parse_timestamp(self, value: Any) -> datetime:
        if isinstance(value, datetime):
            return value.astimezone(timezone.utc)
        if isinstance(value, (int, float)):
            return self._timestamp_from_numeric(float(value))
        if isinstance(value, str):
            text = value.strip()
            if not text:
                raise ValueError("Timestamp value is empty")
            if text.isdigit():
                return self._timestamp_from_numeric(float(text))
            try:
                if text.endswith("Z"):
                    text = text[:-1] + "+00:00"
                return datetime.fromisoformat(text).astimezone(timezone.utc)
            except ValueError:
                pass
            try:
                return self._timestamp_from_numeric(float(text))
            except ValueError as exc:
                raise ValueError(f"Unsupported timestamp format: {value!r}") from exc
        raise ValueError(f"Unsupported timestamp type: {type(value)!r}")

    def _timestamp_from_numeric(self, value: float) -> datetime:
        # Coinbase occasionally returns epoch values in milliseconds. Normalise if needed.
        if value > 1e12:  # approx. 2001-09-09 in milliseconds
            value /= 1000.0
        return datetime.fromtimestamp(value, tz=timezone.utc)

    def _get_ed25519_private_key(self) -> ed25519.Ed25519PrivateKey:
        if self._ed25519_private_key is None:
            key_bytes = self._secret_bytes
            if len(key_bytes) == 64:
                key_bytes = key_bytes[:32]
            if len(key_bytes) != 32:
                raise ValueError("Ed25519 private key must be 32 or 64 bytes")
            self._ed25519_private_key = ed25519.Ed25519PrivateKey.from_private_bytes(key_bytes)
        return self._ed25519_private_key

    def _ecdsa_key_material_candidates(self) -> list[bytes]:
        candidates: list[bytes] = []
        secret = self._secret_bytes
        if secret:
            candidates.append(secret)
            if len(secret) in (64, 65):
                candidates.append(secret[:32])

        raw_secret = self.api_secret or ""
        if raw_secret:
            cleaned_secret = raw_secret.strip()
            if (
                len(cleaned_secret) >= 2
                and cleaned_secret[0] == cleaned_secret[-1]
                and cleaned_secret[0] in {'"', '\''}
            ):
                cleaned_secret = cleaned_secret[1:-1]

            if cleaned_secret:
                literal_bytes = cleaned_secret.encode("utf-8")
                candidates.append(literal_bytes)

                normalised_str = cleaned_secret.replace("\\r", "\r").replace("\\n", "\n")
                if normalised_str != cleaned_secret:
                    candidates.append(normalised_str.encode("utf-8"))

            hex_candidate = cleaned_secret
            if hex_candidate.lower().startswith("0x"):
                hex_candidate = hex_candidate[2:]
            hex_candidate = hex_candidate.replace(" ", "")
            if hex_candidate and len(hex_candidate) % 2 == 0:
                try:
                    decoded = binascii.unhexlify(hex_candidate)
                except (binascii.Error, ValueError):
                    decoded = b""
                else:
                    if decoded:
                        candidates.append(decoded)
                        if len(decoded) > 32:
                            candidates.append(decoded[:32])

        seen: set[bytes] = set()
        unique_candidates: list[bytes] = []
        for candidate in candidates:
            if candidate and candidate not in seen:
                unique_candidates.append(candidate)
                seen.add(candidate)
        return unique_candidates

    def _get_ecdsa_private_key(self) -> ec.EllipticCurvePrivateKey:
        if self._ecdsa_private_key is None:
            for secret in self._ecdsa_key_material_candidates():
                for loader in (serialization.load_pem_private_key, serialization.load_der_private_key):
                    try:
                        key = loader(secret, password=None)
                    except (ValueError, TypeError):
                        continue
                    if isinstance(key, ec.EllipticCurvePrivateKey):
                        self._ecdsa_private_key = key
                        break
                if self._ecdsa_private_key is not None:
                    break

                if len(secret) == 32:
                    scalar = int.from_bytes(secret, "big")
                    try:
                        self._ecdsa_private_key = ec.derive_private_key(scalar, ec.SECP256R1())
                    except ValueError:
                        self._ecdsa_private_key = None
                    else:
                        break
            if self._ecdsa_private_key is None:
                raise ValueError(
                    "Unable to parse ECDSA private key for Coinbase signing. Provide a PEM/DER-encoded key, 32-byte base64, or 32-byte hex value encoded for the P-256 curve."
                )
        return self._ecdsa_private_key

    def _build_rest_jwt(self, method: str, url: httpx.URL) -> str:
        """Construct a JWT token for Advanced Trade REST authentication."""

        host = url.host or "api.coinbase.com"
        path = url.path
        now = int(time.time())
        uri = f"{method.upper()} {host}{path}"

        headers = {"kid": self.api_key, "nonce": secrets.token_hex(16)}
        payload = {
            "sub": self.api_key,
            "iss": "cdp",
            "nbf": now,
            "exp": now + 120,
            "uri": uri,
        }

        match self.signing_algorithm:
            case "ecdsa":
                private_key = self._get_ecdsa_private_key()
                algorithm = "ES256"
            case "ed25519":
                private_key = self._get_ed25519_private_key()
                algorithm = "EdDSA"
            case _:
                raise ValueError(
                    f"Unsupported signing algorithm for Coinbase JWT auth: {self.signing_algorithm}"
                )

        return jwt.encode(payload, private_key, algorithm=algorithm, headers=headers)

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[dict[str, Any]] = None,
        json_body: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        request = self._client.build_request(method, path, params=params, json=json_body)
        if json_body and "content-type" not in request.headers:
            request.headers["Content-Type"] = "application/json"

        jwt_token = self._build_rest_jwt(method, request.url)
        request.headers.update(
            {
                "Authorization": f"Bearer {jwt_token}",
                "Accept": "application/json",
            }
        )
        for header in ("CB-ACCESS-KEY", "CB-ACCESS-SIGN", "CB-ACCESS-TIMESTAMP", "CB-VERSION"):
            request.headers.pop(header, None)

        response = await self._client.send(request)
        if response.status_code >= 400:
            raise CoinbaseAPIError(response.status_code, response.text)
        return response.json()
