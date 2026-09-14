import asyncio
import json
import logging
import time
from typing import Any, Dict, List, Optional
import httpx

logger = logging.getLogger("leasing_client")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")


class LeasingAnalyticsError(Exception):
    """Base exception for Leasing Analytics Client errors."""
    pass


class InvalidINNError(LeasingAnalyticsError):
    """Raised when the provided INN is invalid."""
    pass


class DonorStructureChangedError(LeasingAnalyticsError):
    """Raised when the target site structure, HTML signatures, or JSON keys change."""
    pass


class TTLCache:
    """Simple thread/async-safe In-Memory TTL Cache."""

    def __init__(self, ttl_seconds: float = 180.0, maxsize: int = 500):
        self.ttl_seconds = ttl_seconds
        self.maxsize = maxsize
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._lock = asyncio.Lock()

    async def get(self, key: str) -> Optional[Dict[str, Any]]:
        async with self._lock:
            item = self._cache.get(key)
            if not item:
                return None
            if time.time() > item["expire_at"]:
                del self._cache[key]
                return None
            return item["data"]

    async def set(self, key: str, data: Dict[str, Any]):
        async with self._lock:
            if len(self._cache) >= self.maxsize:
                # Evict oldest expired or first item
                now = time.time()
                expired = [k for k, v in self._cache.items() if now > v["expire_at"]]
                if expired:
                    for k in expired:
                        del self._cache[k]
                else:
                    first_key = next(iter(self._cache))
                    del self._cache[first_key]

            self._cache[key] = {
                "data": data,
                "expire_at": time.time() + self.ttl_seconds,
            }

    async def clear(self):
        async with self._lock:
            self._cache.clear()


class LeasingAnalyticsClient:
    """
    High-performance async client for querying leasing contracts from leasing-analytics.ru by INN.
    Features parallel HTTP execution, structural anti-breakage validation, connection pooling, and TTL caching.
    """

    BASE_URL = "https://leasing-analytics.ru"
    MAIN_PAGE_URL = f"{BASE_URL}/inn/"
    DB_URL = f"{BASE_URL}/wp-content/themes/leasing/includes/db.php"

    CANARY_INN = "7707083893"

    DEFAULT_HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        ),
        "Accept": "*/*",
        "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
        "Origin": BASE_URL,
        "Referer": MAIN_PAGE_URL,
    }

    EXPECTED_CONTRACT_KEYS = {"dogovor", "period_start", "period_end", "name_lk", "class", "total"}

    def __init__(
        self,
        timeout: float = 10.0,
        shared_client: Optional[httpx.AsyncClient] = None,
        ttl_seconds: float = 180.0,
    ):
        self.timeout = timeout
        self._shared_client = shared_client
        self.cache = TTLCache(ttl_seconds=ttl_seconds)

    @staticmethod
    def validate_inn(inn: str) -> str:
        """Validate Russian INN format (10 or 12 digits)."""
        clean_inn = str(inn).strip()
        if not clean_inn.isdigit() or len(clean_inn) not in (10, 12):
            raise InvalidINNError(f"Некорректный ИНН '{inn}'. ИНН должен состоять из 10 или 12 цифр.")
        return clean_inn

    async def get_leasing_info(self, inn: str, force_refresh: bool = False) -> Dict[str, Any]:
        """
        Fetch full leasing information for a given INN using parallel HTTP calls and TTL cache.
        """
        clean_inn = self.validate_inn(inn)

        # 1. Check TTL Cache
        if not force_refresh:
            cached_data = await self.cache.get(clean_inn)
            if cached_data is not None:
                logger.info(f"Выдача данных из TTL-кэша по ИНН: {clean_inn}")
                return cached_data

        logger.info(f"Запрос данных с донора по ИНН: {clean_inn}")

        if self._shared_client and not self._shared_client.is_closed:
            result = await self._fetch_with_client(self._shared_client, clean_inn)
        else:
            async with httpx.AsyncClient(
                headers=self.DEFAULT_HEADERS,
                follow_redirects=True,
                timeout=self.timeout,
                cookies={},
            ) as client:
                result = await self._fetch_with_client(client, clean_inn)

        # 2. Save result to TTL Cache
        await self.cache.set(clean_inn, result)
        return result

    async def _fetch_with_client(self, client: httpx.AsyncClient, clean_inn: str) -> Dict[str, Any]:
        # Step 1: Initialize session via main page
        try:
            resp_main = await client.get(self.MAIN_PAGE_URL, headers=self.DEFAULT_HEADERS)
            if resp_main.status_code != 200:
                raise DonorStructureChangedError(
                    f"Главная страница донора вернула HTTP статус {resp_main.status_code} вместо 200 OK"
                )
            html = resp_main.text
        except httpx.HTTPError as e:
            logger.error(f"Сбой сети при запросе к донору: {e}")
            raise LeasingAnalyticsError(f"Ошибка сети при запросе к leasing-analytics.ru: {e}")

        if "includes/db.php" not in html and "ls_query" not in html and "leasing-analytics.ru" not in html:
            raise DonorStructureChangedError(
                "Верстка главной страницы донора изменилась (отсутствуют сигнатуры поиска). Возможно, сайт обновил код."
            )

        ajax_headers = {
            **self.DEFAULT_HEADERS,
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "X-Requested-With": "XMLHttpRequest",
        }

        # Step 2 & 3: Run page='inn' and page='inn_all' IN PARALLEL!
        task_contracts = client.post(
            self.DB_URL, data={"page": "inn", "inn": clean_inn}, headers=ajax_headers
        )
        task_summary = client.post(
            self.DB_URL, data={"page": "inn_all", "inn": clean_inn}, headers=ajax_headers
        )

        try:
            resp_contracts, resp_summary = await asyncio.gather(
                task_contracts, task_summary, return_exceptions=False
            )
        except httpx.HTTPError as e:
            raise LeasingAnalyticsError(f"Ошибка сети при параллельных вызовах db.php: {e}")

        # Validate contracts response
        if resp_contracts.status_code != 200:
            raise DonorStructureChangedError(
                f"Эндпоинт db.php (page=inn) вернул HTTP статус {resp_contracts.status_code}"
            )
        try:
            contracts_data = resp_contracts.json()
        except json.JSONDecodeError as e:
            raise DonorStructureChangedError(f"Эндпоинт db.php вернул невалидный JSON: {e}")

        if not isinstance(contracts_data, dict) or "lease" not in contracts_data:
            raise DonorStructureChangedError(
                f"Структура ответа db.php изменилась: отсутствует ключ 'lease' в JSON."
            )

        raw_contracts = contracts_data["lease"]
        if not isinstance(raw_contracts, list):
            raise DonorStructureChangedError(f"Ключ 'lease' должен быть списком, получено: {type(raw_contracts)}")

        if raw_contracts:
            first_item = raw_contracts[0]
            if not isinstance(first_item, dict):
                raise DonorStructureChangedError("Элементы списка 'lease' должны быть объектами.")
            missing_keys = self.EXPECTED_CONTRACT_KEYS - set(first_item.keys())
            if missing_keys:
                raise DonorStructureChangedError(
                    f"Схема объекта договора изменилась! Отсутствуют поля: {missing_keys}"
                )

        # Validate summary response
        if resp_summary.status_code != 200:
            raise DonorStructureChangedError(
                f"Эндпоинт db.php (page=inn_all) вернул HTTP статус {resp_summary.status_code}"
            )
        try:
            summary_data = resp_summary.json()
        except json.JSONDecodeError as e:
            raise DonorStructureChangedError(f"Эндпоинт db.php (page=inn_all) вернул невалидный JSON: {e}")

        if not isinstance(summary_data, dict) or "lease_all" not in summary_data:
            raise DonorStructureChangedError(
                f"Структура ответа db.php изменилась: отсутствует ключ 'lease_all' в JSON."
            )

        raw_summary = summary_data["lease_all"]
        if not isinstance(raw_summary, list):
            raise DonorStructureChangedError(f"Ключ 'lease_all' должен быть списком, получено: {type(raw_summary)}")

        # Normalize contract data.
        # Donor may return null / numbers for some fields (seen on INN 7707049388),
        # so every value goes through null-safe _s() instead of raw .strip().
        def _s(value: Any) -> str:
            if value is None:
                return ""
            return str(value).strip()

        def _count(value: Any) -> int:
            digits = "".join(ch for ch in _s(value) if ch.isdigit())
            return int(digits) if digits else 0

        cleaned_contracts = [
            {
                "contract_number": _s(item.get("dogovor")),
                "period_start": _s(item.get("period_start")),
                "period_end": _s(item.get("period_end")),
                "leasing_company": _s(item.get("name_lk")),
                "category": _s(item.get("class")),
                "subject": _s(item.get("total")),
                "url_hash": _s(item.get("url")),
                "brand": _s(item.get("marka")),
                "model": _s(item.get("model")),
            }
            for item in raw_contracts
            if isinstance(item, dict)
        ]

        cleaned_summary = [
            {
                "leasing_company": _s(item.get("name")),
                "contracts_count": _count(item.get("kolvo")),
            }
            for item in raw_summary
            if isinstance(item, dict)
        ]

        return {
            "inn": clean_inn,
            "total_contracts": len(cleaned_contracts),
            "summary": cleaned_summary,
            "contracts": cleaned_contracts,
        }

    async def verify_canary(self) -> Dict[str, Any]:
        """Canary self-test (always bypasses cache)."""
        result = await self.get_leasing_info(self.CANARY_INN, force_refresh=True)
        if result["total_contracts"] == 0:
            raise DonorStructureChangedError(
                f"Канареечная проверка не пройдена! Эталонный ИНН {self.CANARY_INN} вернул 0 договоров."
            )
        return {
            "canary_status": "ok",
            "canary_inn": self.CANARY_INN,
            "contracts_found": result["total_contracts"],
        }
