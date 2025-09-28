from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

import httpx
from cryptography.hazmat.primitives import hashes, serialization
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
        ts = datetime.fromtimestamp(float(data["time"]), tz=timezone.utc)
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
                    start=datetime.fromtimestamp(entry["start"] / 1000, tz=timezone.utc),
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
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"limit": limit}
        if product_id:
            params["product_id"] = product_id
        if order_ids:
            params["order_ids"] = ",".join(order_ids)
        payload = await self._request("GET", "/api/v3/brokerage/orders/historical/fills", params=params)
        return payload.get("fills", [])

    async def list_orders(
        self,
        *,
        product_id: Optional[str] = None,
        order_status: Optional[list[str]] = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"limit": limit}
        if product_id:
            params["product_id"] = product_id
        if order_status:
            params["order_status"] = ",".join(order_status)
        payload = await self._request("GET", "/api/v3/brokerage/orders/historical/batch", params=params)
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

    def _get_ed25519_private_key(self) -> ed25519.Ed25519PrivateKey:
        if self._ed25519_private_key is None:
            key_bytes = self._secret_bytes
            if len(key_bytes) == 64:
                key_bytes = key_bytes[:32]
            if len(key_bytes) != 32:
                raise ValueError("Ed25519 private key must be 32 or 64 bytes")
            self._ed25519_private_key = ed25519.Ed25519PrivateKey.from_private_bytes(key_bytes)
        return self._ed25519_private_key

    def _get_ecdsa_private_key(self) -> ec.EllipticCurvePrivateKey:
        if self._ecdsa_private_key is None:
            secret = self._secret_bytes
            for loader in (serialization.load_pem_private_key, serialization.load_der_private_key):
                try:
                    key = loader(secret, password=None)
                except (ValueError, TypeError):
                    continue
                if isinstance(key, ec.EllipticCurvePrivateKey):
                    self._ecdsa_private_key = key
                    break
            if self._ecdsa_private_key is None and len(secret) == 32:
                scalar = int.from_bytes(secret, "big")
                self._ecdsa_private_key = ec.derive_private_key(scalar, ec.SECP256K1())
            if self._ecdsa_private_key is None:
                raise ValueError("Unable to parse ECDSA private key for Coinbase signing")
        return self._ecdsa_private_key

    def _sign_message(self, message: str) -> str:
        payload = message.encode("utf-8")
        match self.signing_algorithm:
            case "ed25519":
                signature = self._get_ed25519_private_key().sign(payload)
            case "ecdsa":
                signature = self._get_ecdsa_private_key().sign(payload, ec.ECDSA(hashes.SHA256()))
            case "hmac":
                signature = hmac.new(self._secret_bytes, payload, hashlib.sha256).digest()
            case _:
                raise ValueError(f"Unsupported Coinbase signing algorithm: {self.signing_algorithm}")
        return base64.b64encode(signature).decode()

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[dict[str, Any]] = None,
        json_body: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        request = self._client.build_request(method, path, params=params, json=json_body)
        body = request.content.decode() if request.content else ""
        timestamp = str(int(time.time()))
        request_path = request.url.raw_path.decode()
        message = f"{timestamp}{method.upper()}{request_path}{body}"
        signature_b64 = self._sign_message(message)

        request.headers.update(
            {
                "CB-ACCESS-KEY": self.api_key,
                "CB-ACCESS-SIGN": signature_b64,
                "CB-ACCESS-TIMESTAMP": timestamp,
                "CB-VERSION": "2023-10-01",
            }
        )
        if body and "content-type" not in request.headers:
            request.headers["Content-Type"] = "application/json"

        response = await self._client.send(request)
        if response.status_code >= 400:
            raise CoinbaseAPIError(response.status_code, response.text)
        return response.json()
