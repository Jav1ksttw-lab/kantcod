"""Загрузка вакансий из API «Работа в России» с постраничной обработкой."""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import requests

from .config import Config


class FetchError(RuntimeError):
    """Источник недоступен или вернул неожидаемый ответ."""


@dataclass
class FetchResult:
    vacancies: list[dict[str, Any]]
    pages_loaded: int
    total: int | None
    source_url: str


def with_params(url: str, params: dict[str, int]) -> str:
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query.update({k: str(v) for k, v in params.items()})
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def extract_vacancies(payload: Any) -> list[dict[str, Any]]:
    """Принимает ответ API, список элементов или одиночную вакансию."""
    if isinstance(payload, dict) and "vacancy" in payload:
        payload = [payload]
    if isinstance(payload, dict):
        payload = payload.get("results", {}).get("vacancies", [])
    if not isinstance(payload, list):
        return []
    result: list[dict[str, Any]] = []
    for item in payload:
        if isinstance(item, dict):
            vacancy = item.get("vacancy", item)
            if isinstance(vacancy, dict) and vacancy.get("id"):
                result.append(vacancy)
    return result


def _request_json(url: str, cfg: Config) -> dict[str, Any]:
    last_error: Exception | None = None
    for attempt in range(1, cfg.retries + 1):
        try:
            response = requests.get(
                url,
                timeout=cfg.request_timeout,
                headers={"User-Agent": "transparent-vacancy/1.0", "Accept": "application/json"},
            )
            if response.status_code != 200:
                raise FetchError(f"HTTP {response.status_code} от {url}: {response.text[:200]}")
            data = response.json()
            if not isinstance(data, dict):
                raise FetchError(f"Ожидался JSON-объект от {url}, получен {type(data).__name__}")
            return data
        except (requests.RequestException, ValueError, FetchError) as exc:
            last_error = exc
            if attempt < cfg.retries:
                time.sleep(cfg.retry_backoff_seconds * attempt)
    raise FetchError(f"Не удалось получить данные ({cfg.retries} попыток): {last_error}")


def fetch_vacancies(cfg: Config) -> FetchResult:
    collected: list[dict[str, Any]] = []
    seen: set[str] = set()
    offset = 0
    pages_loaded = 0
    total: int | None = None

    for _page in range(1, cfg.max_pages + 1):
        limit = min(cfg.page_size, cfg.max_vacancies - len(collected))
        if limit <= 0:
            break
        url = with_params(cfg.source_url, {"limit": limit, "offset": offset})
        payload = _request_json(url, cfg)
        meta = payload.get("meta") or {}
        if isinstance(meta.get("total"), int):
            total = meta["total"]
        batch = extract_vacancies(payload)
        if not batch:
            break
        for vacancy in batch:
            vacancy_id = str(vacancy["id"])
            if vacancy_id not in seen:
                seen.add(vacancy_id)
                collected.append(vacancy)
        pages_loaded += 1
        offset += limit
        if len(collected) >= cfg.max_vacancies:
            break
        if total is not None and offset >= total:
            break

    if not collected:
        raise FetchError(f"Источник вернул 0 вакансий: {cfg.source_url}")

    return FetchResult(
        vacancies=collected[: cfg.max_vacancies],
        pages_loaded=pages_loaded,
        total=total,
        source_url=cfg.source_url,
    )
