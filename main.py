from contextlib import asynccontextmanager
from typing import List
import httpx
from fastapi import FastAPI, HTTPException, Path, Query, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from pydantic import BaseModel, Field
from leasing_client import (
    DonorStructureChangedError,
    InvalidINNError,
    LeasingAnalyticsClient,
    LeasingAnalyticsError,
)

leasing_client_instance: LeasingAnalyticsClient = None
shared_http_client: httpx.AsyncClient = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan manager: maintains persistent HTTP connection pool and TTL cache."""
    global shared_http_client, leasing_client_instance
    shared_http_client = httpx.AsyncClient(
        follow_redirects=True,
        timeout=10.0,
        limits=httpx.Limits(max_keepalive_connections=20, max_connections=50),
    )
    # TTL cache set to 180 seconds (3 minutes)
    leasing_client_instance = LeasingAnalyticsClient(shared_client=shared_http_client, ttl_seconds=180.0)
    yield
    await shared_http_client.aclose()


app = FastAPI(
    title="Leasing Analytics Request Repeater API",
    description="Высокоскоростной API-повторитель с поддержкой TTL-кэширования и контроля целостности структуры донора",
    version="1.3.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# Enable GZip compression for responses > 1000 bytes
app.add_middleware(GZipMiddleware, minimum_size=1000)

# Enable CORS for all origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_client() -> LeasingAnalyticsClient:
    if leasing_client_instance is None:
        return LeasingAnalyticsClient()
    return leasing_client_instance


class ContractItem(BaseModel):
    contract_number: str = Field(..., description="Номер договора лизинга", json_schema_extra={"example": "1663-ДЛ-23"})
    period_start: str = Field(..., description="Дата начала договора (ГГГГ-ММ-ДД)", json_schema_extra={"example": "2024-04-25"})
    period_end: str = Field(..., description="Дата окончания договора (ГГГГ-ММ-ДД)", json_schema_extra={"example": "2029-04-30"})
    leasing_company: str = Field(..., description="Наименование лизинговой компании", json_schema_extra={"example": "ООО 'ЭЛЕМЕНТ ЛИЗИНГ'"})
    category: str = Field(..., description="Категория предмета лизинга", json_schema_extra={"example": "Легковой автотранспорт"})
    subject: str = Field(..., description="Полный предмет лизинга", json_schema_extra={"example": "АВТОМОБИЛЬ ЛЕГКОВОЙ GEELY MONJARO"})
    url_hash: str = Field("", description="Внутренний идентификатор договора")
    brand: str = Field("", description="Марка предмета лизинга")
    model: str = Field("", description="Модель предмета лизинга")


class SummaryItem(BaseModel):
    leasing_company: str = Field(..., description="Наименование лизинговой компании", json_schema_extra={"example": "АО 'ЛИЗИНГОВАЯ КОМПАНИЯ 'КАМАЗ'"})
    contracts_count: int = Field(..., description="Количество договоров", json_schema_extra={"example": 12})


class LeasingResponse(BaseModel):
    inn: str = Field(..., description="Запрошенный ИНН", json_schema_extra={"example": "7707389530"})
    total_contracts: int = Field(..., description="Общее количество договоров лизинга", json_schema_extra={"example": 147})
    summary: List[SummaryItem] = Field(..., description="Сводка по лизинговым компаниям")
    contracts: List[ContractItem] = Field(..., description="Список всех найденных договоров")


class ErrorResponse(BaseModel):
    error: str = Field(..., description="Код/Тип ошибки")
    detail: str = Field(..., description="Подробная информация об ошибке")


@app.get(
    "/health",
    tags=["Service"],
    summary="Проверка работоспособности сервиса",
)
async def health_check():
    return {"status": "ok", "service": "leasing-repeater-api"}


@app.get(
    "/health/canary",
    tags=["Service"],
    summary="Проверка целостности верстки и кода сайта-донора (Canary Self-Test)",
    responses={
        200: {"description": "Сайт-донор доступен и отдает корректные данные"},
        502: {"model": ErrorResponse, "description": "Код или структура ответа сайта-донора изменилась"},
    },
)
async def canary_health_check():
    try:
        res = await get_client().verify_canary()
        return res
    except DonorStructureChangedError as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"error": "DonorSiteStructureChanged", "message": str(e)},
        )
    except LeasingAnalyticsError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error": "DonorSiteUnavailable", "message": str(e)},
        )


@app.get(
    "/api/v1/leasing/{inn}",
    response_model=LeasingResponse,
    responses={
        400: {"model": ErrorResponse, "description": "Некорректный ИНН"},
        502: {"model": ErrorResponse, "description": "Структура или код сайта-донора изменился"},
        503: {"model": ErrorResponse, "description": "Сайт-донор недоступен"},
    },
    tags=["Leasing"],
    summary="Получить полную информацию о договорах лизинга по ИНН",
)
async def get_leasing_by_inn(
    inn: str = Path(..., description="ИНН юридического или физического лица (10 или 12 цифр)"),
    refresh: bool = Query(False, description="Принудительное обновление данные в обход TTL-кэша"),
):
    try:
        data = await get_client().get_leasing_info(inn, force_refresh=refresh)
        return data
    except InvalidINNError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "InvalidINN", "message": str(e)},
        )
    except DonorStructureChangedError as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"error": "DonorSiteStructureChanged", "message": str(e)},
        )
    except LeasingAnalyticsError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error": "DonorSiteUnavailable", "message": str(e)},
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error": "InternalServerError", "message": f"Внутренняя ошибка сервера: {e}"},
        )


@app.get(
    "/api/v1/leasing/{inn}/contracts",
    response_model=List[ContractItem],
    tags=["Leasing"],
    summary="Получить только список договоров лизинга по ИНН",
)
async def get_contracts_by_inn(
    inn: str = Path(..., description="ИНН (10 или 12 цифр)"),
    refresh: bool = Query(False, description="Принудительное обновление данные в обход TTL-кэша"),
):
    data = await get_leasing_by_inn(inn, refresh=refresh)
    return data["contracts"]


@app.get(
    "/api/v1/leasing/{inn}/summary",
    response_model=List[SummaryItem],
    tags=["Leasing"],
    summary="Получить только сводку по лизинговым компаниям по ИНН",
)
async def get_summary_by_inn(
    inn: str = Path(..., description="ИНН (10 или 12 цифр)"),
    refresh: bool = Query(False, description="Принудительное обновление данные в обход TTL-кэша"),
):
    data = await get_leasing_by_inn(inn, refresh=refresh)
    return data["summary"]
