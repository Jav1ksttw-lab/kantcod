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
    if isinstance(payload, dict):
        if "vacancy" in payload or "id" in payload:
            payload = [payload]
        else:
            results = payload.get("results")
            payload = results.get("vacancies") if isinstance(results, dict) else None
    if not isinstance(payload, list):
        raise ValueError("Ожидался массив results.vacancies в ответе API")

    vacancies = []
    for index, item in enumerate(payload):
        vacancy = item.get("vacancy", item) if isinstance(item, dict) else None
        vacancy_id = vacancy.get("id") if isinstance(vacancy, dict) else None
        if type(vacancy_id) not in (str, int) or not str(vacancy_id).strip():
            raise ValueError(f"Вакансия с индексом {index} не содержит корректного ID")
        vacancies.append(vacancy)
    return vacancies


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
            if not isinstance(data, dict) or str(data.get("status", 200)) != "200":
                raise FetchError(f"Некорректный статус ответа API: {url}")
            if not isinstance(data.get("results"), dict):
                raise FetchError(f"Нет объекта results в ответе API: {url}")
            extract_vacancies(data)
            return data
        except (requests.RequestException, ValueError, FetchError) as exc:
            last_error = exc
            if attempt < cfg.retries:
                time.sleep(cfg.retry_backoff_seconds * attempt)
    raise FetchError(f"Не удалось получить данные ({cfg.retries} попыток): {last_error}")


def fetch_vacancies(cfg: Config) -> FetchResult:
    collected: list[dict[str, Any]] = []
    seen: set[str] = set()
    pages_loaded = 0
    total: int | None = None

    limit = min(cfg.page_size, cfg.max_vacancies)
    if cfg.max_pages > 1:
        limit = min(limit, (cfg.max_vacancies + 1) // 2)
    for offset in range(cfg.max_pages):
        url = with_params(cfg.source_url, {"limit": limit, "offset": offset})
        payload = _request_json(url, cfg)
        meta = payload.get("meta") or {}
        if isinstance(meta, dict) and type(meta.get("total")) is int:
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
        if len(collected) >= cfg.max_vacancies:
            break
        if total is not None and (offset + 1) * limit >= total:
            break

    return FetchResult(
        vacancies=collected[: cfg.max_vacancies],
        pages_loaded=pages_loaded,
        total=total,
        source_url=cfg.source_url,
    )
