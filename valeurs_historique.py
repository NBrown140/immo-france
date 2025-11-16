import io
import zipfile
from collections.abc import Iterable
from pathlib import Path

import geopandas as gpd
import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from shapely.geometry import Point
from tqdm import tqdm
from urllib3.util.retry import Retry

from geocoding_candidates import build_city_variants, build_q_candidates, construct_address


GEOCODING_API_URL = "http://localhost:8080"

data_url_2025 = "https://static.data.gouv.fr/resources/demandes-de-valeurs-foncieres/20251018-234902/valeursfoncieres-2025-s1.txt.zip"

_retry_strategy = Retry(
    total=3,
    status_forcelist=(429, 503),
    allowed_methods=frozenset({"GET"}),
    backoff_factor=0.5,
)
_http_adapter = HTTPAdapter(max_retries=_retry_strategy)
SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "immo-france-geocoder/1.0"})
SESSION.mount("http://", _http_adapter)
SESSION.mount("https://", _http_adapter)

def _extract_first_txt(zip_file: zipfile.ZipFile) -> io.BytesIO:
    """Return a buffer containing the first .txt file found in the archive."""
    for name in zip_file.namelist():
        if name.lower().endswith(".txt"):
            return io.BytesIO(zip_file.read(name))
    raise ValueError("Zip archive does not contain any .txt file.")


def _load_dataframe_from_url(url: str, *, sep: str) -> pd.DataFrame:
    """Download a single archive and return its TXT payload as a DataFrame."""
    response = requests.get(url, timeout=120)
    response.raise_for_status()

    with zipfile.ZipFile(io.BytesIO(response.content)) as zf:
        txt_buffer = _extract_first_txt(zf)

    txt_buffer.seek(0)
    return pd.read_csv(txt_buffer, sep=sep, dtype=str, low_memory=False)


def load_valeurs_foncieres_dataframe(
    urls: str | Iterable[str] = data_url_2025, *, sep: str = "|"
) -> pd.DataFrame:
    """
    Download one or more valeurs foncières archives, merge them, and return a DataFrame.
    """
    if isinstance(urls, str):
        urls_to_fetch = [urls]
    else:
        urls_to_fetch = list(urls)

    if not urls_to_fetch:
        raise ValueError("At least one URL must be provided.")

    frames = [_load_dataframe_from_url(url, sep=sep) for url in urls_to_fetch]
    return pd.concat(frames, ignore_index=True)


def geocode_address(
    *,
    street: str | None = None,
    city: str | None = None,
    postal_code: str | None = None,
    country: str = "France",
) -> tuple[tuple[float, float] | None, str | None]:
    """
    Geocode an address via structured parameters, falling back to a free-text `q` query.
    Returns ((longitude, latitude), None) if successful, otherwise (None, error_message).
    """
    base_params = {
        "format": "json",
        "limit": 1,
        "country": country,
    }
    if street:
        base_params["street"] = street
    if postal_code:
        base_params["postalcode"] = postal_code

    if not any((street, city, postal_code)):
        return None, None

    attempt_logs: list[str] = []

    def _append_trace(label: str, message: str | None) -> None:
        detail = message if message else "[geocode] failed without error details"
        attempt_logs.append(f"{label}: {detail}")

    def _request(params: dict[str, str]) -> tuple[list[dict[str, str]] | None, str | None, str]:
        endpoint = GEOCODING_API_URL + "/search"
        prepared = requests.Request("GET", endpoint, params=params).prepare()
        query_url = prepared.url
        try:
            response = SESSION.get(endpoint, params=params, timeout=30)
        except requests.RequestException as exc:
            return None, f"[geocode] connection error ({exc.__class__.__name__}): {query_url}, params: {params}", query_url
        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else "unknown"
            return None, f"[geocode] request failed (status={status}): {query_url}, params: {params}", query_url
        results = response.json()
        if not results:
            return None, f"[geocode] no result: {query_url}, params: {params}", query_url
        return results, None, query_url

    structured_cities: list[str | None] = []
    seen_city_options: set[str | None] = set()

    def _add_city_option(option: str | None) -> None:
        if option in seen_city_options:
            return
        if option is None and not (street or postal_code):
            return
        structured_cities.append(option)
        seen_city_options.add(option)

    if city:
        city_variants = build_city_variants(city)
        for key in ("city_original", "city_arrondissement_parent", "city_remove_eme"):
            option = city_variants.get(key)
            if option:
                _add_city_option(option)

    if not structured_cities and city:
        _add_city_option(city)
    if not structured_cities:
        _add_city_option(None)
    elif street or postal_code:
        _add_city_option(None)

    structured_errors: list[str] = []
    for city_option in structured_cities:
        params = dict(base_params)
        if city_option:
            params["city"] = city_option
        label = f"structured(city={city_option!r})" if city_option else "structured(base)"
        results, error, _ = _request(params)
        if results:
            lon = float(results[0]["lon"])
            lat = float(results[0]["lat"])
            return (lon, lat), None
        if error:
            structured_errors.append(error)
            _append_trace(label, error)

    def _build_q_params(street_variant: str | None, city_variant: str | None) -> dict[str, str] | None:
        chosen_city = city_variant if city_variant is not None else city
        parts = [part for part in (street_variant, postal_code, chosen_city, country) if part]
        if not parts:
            return None
        return {"format": "json", "limit": 1, "q": ", ".join(parts)}

    fallback_errors: list[str] = []
    q_candidates = build_q_candidates(street, city)

    for candidate in q_candidates:
        params = _build_q_params(candidate.street, candidate.city)
        if not params:
            continue
        label = f"fallback({candidate.label})"
        fallback_results, fallback_error, _ = _request(params)
        if fallback_results:
            lon = float(fallback_results[0]["lon"])
            lat = float(fallback_results[0]["lat"])
            return (lon, lat), None
        if fallback_error:
            fallback_errors.append(f"{candidate.label}: {fallback_error}")
            _append_trace(label, fallback_error)

    last_error = fallback_errors[-1] if fallback_errors else (structured_errors[-1] if structured_errors else None)
    if attempt_logs:
        trace_lines = "\n  - " + "\n  - ".join(attempt_logs)
    else:
        trace_lines = ""
    if last_error and trace_lines:
        return None, f"{last_error}\n[geocode trace]{trace_lines}"
    if last_error:
        return None, last_error
    if trace_lines:
        return None, f"[geocode] failed without captured error\n[geocode trace]{trace_lines}"
    return None, "[geocode] failed without captured error"


def geocode_dataframe(df: pd.DataFrame) -> tuple[gpd.GeoDataFrame, list[str]]:
    """
    Geocode the addresses in the DataFrame and return (GeoDataFrame, geocoding_errors).
    Uses DVF columns: 'No voie', 'B/T/Q', 'Type de voie', 'Voie', 'Code postal', 'Commune'.
    """
    geometries: list[Point | None] = [None] * len(df)
    errors: list[str] = []
    jobs: list[tuple[int, str | None, str | None, str | None]] = []

    for idx, (_, row) in enumerate(df.iterrows()):
        street, city, postal_code = construct_address(row)
        if any((street, city, postal_code)):
            jobs.append((idx, street, city, postal_code))

    if jobs:
        for idx, street, city, postal_code in tqdm(
            jobs,
            total=len(jobs),
            desc="Geocoding",
        ):
            coords, error = geocode_address(street=street, city=city, postal_code=postal_code)
            if error:
                errors.append(error)
            if coords:
                geometries[idx] = Point(coords)

    gdf = gpd.GeoDataFrame(df.copy(), geometry=geometries, crs="EPSG:4326")
    return gdf, errors


def save_geodataframe(
    gdf: gpd.GeoDataFrame,
    output_path: str,
    layer: str = "valeurs_foncieres",
) -> None:
    """
    Persist the GeoDataFrame as GeoJSON, GeoPackage, or GeoParquet depending on the file suffix.
    """
    path = Path(output_path)
    suffix = path.suffix.lower()

    if suffix in {".geojson", ".json"}:
        gdf.to_file(path, driver="GeoJSON")
    elif suffix == ".gpkg":
        gdf.to_file(path, driver="GPKG", layer=layer)
    elif suffix in {".parquet", ".pq"}:
        gdf.to_parquet(path)
    else:
        raise ValueError(
            f"Unsupported output format '{suffix}'. Use .geojson, .gpkg, or .parquet/.pq"
        )
