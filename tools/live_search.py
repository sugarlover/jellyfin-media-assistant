"""Run Jellyfin Media Assistant search against a real read-only catalog."""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import Mapping
import json
import os
from pathlib import Path
import sys
from typing import Any

from custom_components.jellyfin_assist.matching.context import MediaSearchContext
from custom_components.jellyfin_assist.search import (
    CatalogCacheStore,
    CatalogIndex,
    CatalogManager,
    CatalogManagerDiagnostics,
    CatalogPageResponseError,
    CatalogRefreshError,
    JellyfinCatalogClient,
    JellyfinCatalogConfigurationError,
    JellyfinCatalogResponseError,
    LocalCatalogSearchOutcome,
    catalog_cache_filename,
    load_catalog_snapshot,
)
from custom_components.jellyfin_assist.search.retrieval import (
    CatalogSearchOutcome,
    retrieve_rank_and_decide,
)
from tools.jellyfin_readonly import (
    JellyfinLiveConfigurationError,
    JellyfinReadOnlyApi,
    JellyfinReadOnlyError,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ENV_FILE = REPO_ROOT / ".env"
DEFAULT_CATALOG_CACHE_DIR = REPO_ROOT / ".cache" / "jellyfin-assist"


def load_env_file(path: Path) -> dict[str, str]:
    """Load a small KEY=VALUE environment file without third-party packages."""

    if not path.exists():
        return {}

    values: dict[str, str] = {}
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            raise JellyfinLiveConfigurationError(
                f"Invalid .env line {line_number}: expected KEY=VALUE"
            )
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            raise JellyfinLiveConfigurationError(
                f"Invalid .env line {line_number}: empty key"
            )
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        values[key] = value
    return values


def merged_environment(env_file: Path) -> dict[str, str]:
    """Merge local file values with process environment taking precedence."""

    merged = load_env_file(env_file)
    merged.update(os.environ)
    return merged


def parse_bool(value: str | None, *, default: bool) -> bool:
    if value is None or not value.strip():
        return default
    normalized = value.strip().casefold()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise JellyfinLiveConfigurationError(
        f"Expected a boolean value, received {value!r}"
    )


def required_setting(settings: Mapping[str, str], name: str) -> str:
    value = settings.get(name, "").strip()
    if not value:
        raise JellyfinLiveConfigurationError(
            f"{name} is required in .env or the process environment"
        )
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run the isolated Jellyfin Media Assistant search engine against "
            "a real Jellyfin catalog using GET-only requests."
        )
    )
    parser.add_argument("query", help="Media title or spoken search text")
    parser.add_argument("--media-type", help="Jellyfin type, e.g. Audio or Movie")
    parser.add_argument("--artist", help="Expected artist context")
    parser.add_argument("--album", help="Expected album context")
    parser.add_argument("--series", help="Expected series context")
    parser.add_argument("--year", help="Expected production year")
    parser.add_argument(
        "--catalog",
        action="store_true",
        help=(
            "Load a metadata-only catalog snapshot and match locally instead "
            "of relying on Jellyfin SearchTerm"
        ),
    )
    parser.add_argument(
        "--catalog-page-size",
        type=int,
        default=500,
        help="Items requested per read-only catalog page (default: 500)",
    )
    parser.add_argument(
        "--catalog-max-items",
        type=int,
        default=0,
        help="Optional catalog item cap; 0 means no cap (default: 0)",
    )
    parser.add_argument(
        "--refresh-catalog",
        action="store_true",
        help="Force a fresh Jellyfin catalog download before searching",
    )
    parser.add_argument(
        "--no-catalog-cache",
        action="store_true",
        help="Disable metadata cache reads and writes for this run",
    )
    parser.add_argument(
        "--catalog-cache-dir",
        type=Path,
        default=DEFAULT_CATALOG_CACHE_DIR,
        help="Catalog cache directory (default: repository .cache/jellyfin-assist)",
    )
    parser.add_argument(
        "--env-file",
        type=Path,
        default=DEFAULT_ENV_FILE,
        help="Credential file (default: repository .env)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable diagnostics instead of the human report",
    )
    parser.add_argument(
        "--max-results",
        type=int,
        default=10,
        help="Maximum ranked alternatives displayed (default: 10)",
    )
    return parser


def _item_value(item: Mapping[str, Any], *names: str) -> Any:
    for name in names:
        value = item.get(name)
        if value not in (None, "", []):
            return value
    return None


def _candidate_sources(outcome: CatalogSearchOutcome, item_id: str) -> list[str]:
    for candidate in outcome.execution.candidate_pool.candidates:
        if candidate.item_id == item_id:
            return [source.term for source in candidate.sources]
    return []


def _ranked_dict(outcome: CatalogSearchOutcome, ranked: Any) -> dict[str, Any]:
    candidate = ranked.candidate
    title_match = ranked.title_match
    result: dict[str, Any] = {
        "id": candidate.key,
        "title": candidate.title,
        "media_type": candidate.media_type,
        "artist": candidate.artist,
        "album": candidate.album,
        "series": candidate.series,
        "year": candidate.year,
        "family": title_match.family.value,
        "method": title_match.method.value,
        "matched_alias": title_match.matched_alias,
        "lexical_score": title_match.lexical_score,
        "phonetic_score": title_match.phonetic_score,
        "context_score": ranked.context_score,
        "total_score": ranked.total_score,
        "contradictions": ranked.contradiction_count,
        "retrieved_by": _candidate_sources(outcome, candidate.key),
        "context_evidence": [
            {
                "field": evidence.field.value,
                "relation": evidence.relation.value,
                "requested": evidence.requested,
                "candidate": evidence.candidate,
                "adjustment": evidence.adjustment,
                "method": evidence.method.value if evidence.method else None,
            }
            for evidence in ranked.evidence
        ],
    }
    if title_match.fuzzy is not None:
        result["edit_distance"] = title_match.fuzzy.edit_distance
        result["similarity"] = round(title_match.fuzzy.similarity, 4)
    if title_match.phonetic is not None:
        result["phonetic_query_signature"] = title_match.phonetic.query_signature
        result["phonetic_candidate_signature"] = title_match.phonetic.candidate_signature
    return result


def outcome_dict(outcome: CatalogSearchOutcome, server: Mapping[str, Any]) -> dict[str, Any]:
    selected = outcome.decision.selected
    return {
        "read_only": True,
        "server": {
            "name": server.get("ServerName"),
            "version": server.get("Version"),
        },
        "query": outcome.query,
        "context": {
            "media_type": outcome.context.media_type,
            "artist": outcome.context.artist,
            "album": outcome.context.album,
            "series": outcome.context.series,
            "year": outcome.context.year,
        },
        "attempts": [
            {
                "index": request.attempt.index,
                "term": request.term,
                "methods": [method.value for method in request.attempt.methods],
                "returned": len(outcome.execution.attempt_results[index].items)
                if index < len(outcome.execution.attempt_results)
                else None,
            }
            for index, request in enumerate(outcome.execution.requests)
        ],
        "candidate_pool": {
            "raw_items": outcome.execution.candidate_pool.raw_item_count,
            "unique_items": len(outcome.execution.candidate_pool.candidates),
            "duplicates": outcome.execution.candidate_pool.duplicate_item_count,
            "invalid": outcome.execution.candidate_pool.invalid_item_count,
            "dropped": outcome.execution.candidate_pool.dropped_unique_count,
            "truncated": outcome.execution.candidate_pool.truncated,
        },
        "decision": {
            "status": outcome.decision.status.value,
            "reason": outcome.decision.reason.value,
            "active_family": (
                outcome.decision.active_family.value
                if outcome.decision.active_family
                else None
            ),
            "automatic_selection_allowed": outcome.decision.automatic_selection_allowed,
            "required_minimum_score": outcome.decision.required_minimum_score,
            "required_margin": outcome.decision.required_margin,
            "required_minimum_similarity": outcome.decision.required_minimum_similarity,
            "observed_margin": outcome.decision.observed_margin,
            "selected": _ranked_dict(outcome, selected) if selected else None,
        },
        "ranked_candidates": [
            _ranked_dict(outcome, ranked) for ranked in outcome.ranking.matches
        ],
        "mapping_issues": [
            {"id": issue.item_id, "reason": issue.reason.value}
            for issue in outcome.media_candidates.issues
        ],
    }


def print_human_report(report: Mapping[str, Any], *, max_results: int) -> None:
    server = report["server"]
    context = report["context"]
    pool = report["candidate_pool"]
    decision = report["decision"]

    print("Jellyfin Media Assistant — READ-ONLY LIVE SEARCH")
    print("Only HTTP GET requests are permitted by this test client.")
    print()
    print(f"Server: {server.get('name') or '<unknown>'} {server.get('version') or ''}".rstrip())
    print(f"Original query: {report['query']}")
    supplied_context = ", ".join(
        f"{key}={value}" for key, value in context.items() if value not in (None, "")
    )
    print(f"Context: {supplied_context or '<none>'}")
    print()

    print("Catalog attempts:")
    for attempt in report["attempts"]:
        methods = ", ".join(attempt["methods"])
        returned = attempt["returned"]
        print(
            f"  {attempt['index'] + 1}. {attempt['term']!r} "
            f"[{methods}] -> {returned if returned is not None else '?'} items"
        )
    print(
        "Candidate pool: "
        f"{pool['raw_items']} raw, {pool['unique_items']} unique, "
        f"{pool['duplicates']} duplicates, {pool['dropped']} dropped"
    )
    print()

    print(f"Decision: {decision['status']} ({decision['reason']})")
    print(f"Active family: {decision['active_family'] or '<none>'}")
    print(f"Automatic selection allowed: {decision['automatic_selection_allowed']}")
    if decision["observed_margin"] is not None:
        print(
            f"Observed margin: {decision['observed_margin']} "
            f"(required: {decision['required_margin']})"
        )

    selected = decision["selected"]
    if selected:
        print(
            "Selected: "
            f"{selected['title']} [{selected['media_type'] or 'unknown'}] "
            f"id={selected['id']}"
        )
        alias_suffix = (
            f" via alias={selected['matched_alias']!r}"
            if selected.get("matched_alias")
            else ""
        )
        print(
            "Match: "
            f"{selected['family']}/{selected['method']}{alias_suffix}; "
            f"lexical={selected['lexical_score']}, "
            f"phonetic={selected['phonetic_score']}, "
            f"context={selected['context_score']}, total={selected['total_score']}"
        )
    print()

    ranked = report["ranked_candidates"][:max_results]
    print(f"Ranked candidates ({len(ranked)} shown):")
    if not ranked:
        print("  <none>")
    for index, item in enumerate(ranked, 1):
        metadata = [item["media_type"]]
        if item["artist"]:
            metadata.append(f"artist={item['artist']}")
        if item["album"]:
            metadata.append(f"album={item['album']}")
        if item["series"]:
            metadata.append(f"series={item['series']}")
        if item["year"]:
            metadata.append(f"year={item['year']}")
        metadata_text = ", ".join(str(value) for value in metadata if value)
        print(f"  {index}. {item['title']} ({metadata_text or 'no metadata'})")
        print(
            "     "
            f"id={item['id']} | {item['family']}/{item['method']} | "
            f"lexical={item['lexical_score']} phonetic={item['phonetic_score']} "
            f"context={item['context_score']} total={item['total_score']}"
        )
        print(f"     retrieved by: {', '.join(item['retrieved_by']) or '<unknown>'}")



def _local_shortlist_entry(
    outcome: LocalCatalogSearchOutcome,
    item_id: str,
) -> Any | None:
    for entry in outcome.shortlist:
        if entry.record.item_id == item_id:
            return entry
    return None


def _local_ranked_dict(
    outcome: LocalCatalogSearchOutcome,
    ranked: Any,
) -> dict[str, Any]:
    candidate = ranked.candidate
    title_match = ranked.title_match
    shortlist_entry = _local_shortlist_entry(outcome, candidate.key)
    result: dict[str, Any] = {
        "id": candidate.key,
        "physical_ids": (
            list(shortlist_entry.record.physical_item_ids)
            if shortlist_entry is not None
            else list(candidate.physical_keys or (candidate.key,))
        ),
        "provider_ids": dict(candidate.provider_ids),
        "title": candidate.title,
        "media_type": candidate.media_type,
        "artist": candidate.artist,
        "album": candidate.album,
        "series": candidate.series,
        "year": candidate.year,
        "family": title_match.family.value,
        "method": title_match.method.value,
        "matched_alias": title_match.matched_alias,
        "lexical_score": title_match.lexical_score,
        "phonetic_score": title_match.phonetic_score,
        "context_score": ranked.context_score,
        "total_score": ranked.total_score,
        "contradictions": ranked.contradiction_count,
        "shortlisted_by": (
            [method.value for method in shortlist_entry.methods]
            if shortlist_entry is not None
            else []
        ),
        "token_overlap": shortlist_entry.token_overlap if shortlist_entry else 0,
        "ngram_overlap": shortlist_entry.ngram_overlap if shortlist_entry else 0,
        "ngram_similarity": (
            round(shortlist_entry.ngram_similarity, 4) if shortlist_entry else 0.0
        ),
        "context_evidence": [
            {
                "field": evidence.field.value,
                "relation": evidence.relation.value,
                "requested": evidence.requested,
                "candidate": evidence.candidate,
                "adjustment": evidence.adjustment,
                "method": evidence.method.value if evidence.method else None,
            }
            for evidence in ranked.evidence
        ],
    }
    if title_match.fuzzy is not None:
        result["edit_distance"] = title_match.fuzzy.edit_distance
        result["similarity"] = round(title_match.fuzzy.similarity, 4)
    if title_match.phonetic is not None:
        result["phonetic_query_signature"] = title_match.phonetic.query_signature
        result["phonetic_candidate_signature"] = (
            title_match.phonetic.candidate_signature
        )
    return result


def _manager_diagnostics_dict(
    diagnostics: CatalogManagerDiagnostics | None,
) -> dict[str, Any] | None:
    if diagnostics is None:
        return None
    return {
        "available": diagnostics.available,
        "source": diagnostics.source.value,
        "refresh_in_progress": diagnostics.refresh_in_progress,
        "requested_types": list(diagnostics.requested_types),
        "cache_path": diagnostics.cache_path,
        "catalog_created_at": diagnostics.catalog_created_at,
        "cache_age_seconds": diagnostics.cache_age_seconds,
        "last_cache_load_duration_ms": diagnostics.last_cache_load_duration_ms,
        "last_refresh_duration_ms": diagnostics.last_refresh_duration_ms,
        "last_index_build_duration_ms": diagnostics.last_index_build_duration_ms,
        "last_cache_write_duration_ms": diagnostics.last_cache_write_duration_ms,
        "last_search_duration_ms": diagnostics.last_search_duration_ms,
        "search_count": diagnostics.search_count,
        "last_error": diagnostics.last_error,
    }


def local_outcome_dict(
    outcome: LocalCatalogSearchOutcome,
    *,
    snapshot: Any,
    index: CatalogIndex,
    server: Mapping[str, Any],
    manager_diagnostics: CatalogManagerDiagnostics | None = None,
) -> dict[str, Any]:
    selected = outcome.decision.selected
    return {
        "read_only": True,
        "mode": "local_catalog",
        "manager": _manager_diagnostics_dict(manager_diagnostics),
        "server": {
            "name": server.get("ServerName"),
            "version": server.get("Version"),
        },
        "query": outcome.query,
        "context": {
            "media_type": outcome.context.media_type,
            "artist": outcome.context.artist,
            "album": outcome.context.album,
            "series": outcome.context.series,
            "year": outcome.context.year,
        },
        "catalog": {
            "requested_types": list(snapshot.requested_types),
            "pages": len(snapshot.pages),
            "raw_items": snapshot.raw_item_count,
            "snapshot_items": len(snapshot.items),
            "duplicates": snapshot.duplicate_item_count,
            "missing_ids": snapshot.missing_id_count,
            "server_overflow": snapshot.server_overflow_item_count,
            "truncated": snapshot.truncated,
            "stop_reason": snapshot.stop_reason.value,
            "indexed_records": len(index.records),
            "logical_groups": index.logical_group_count,
            "grouped_physical_items": index.grouped_physical_item_count,
            "index_issues": len(index.issues),
            "eligible_records": outcome.eligible_record_count,
            "shortlist_size": len(outcome.shortlist),
        },
        "decision": {
            "status": outcome.decision.status.value,
            "reason": outcome.decision.reason.value,
            "active_family": (
                outcome.decision.active_family.value
                if outcome.decision.active_family
                else None
            ),
            "automatic_selection_allowed": (
                outcome.decision.automatic_selection_allowed
            ),
            "required_minimum_score": outcome.decision.required_minimum_score,
            "required_margin": outcome.decision.required_margin,
            "required_minimum_similarity": (
                outcome.decision.required_minimum_similarity
            ),
            "observed_margin": outcome.decision.observed_margin,
            "selected": _local_ranked_dict(outcome, selected) if selected else None,
        },
        "ranked_candidates": [
            _local_ranked_dict(outcome, ranked)
            for ranked in outcome.ranking.matches
        ],
        "index_issues": [
            {
                "position": issue.input_position,
                "id": issue.item_id,
                "reason": issue.reason.value,
            }
            for issue in index.issues
        ],
    }


def print_local_human_report(
    report: Mapping[str, Any],
    *,
    max_results: int,
) -> None:
    server = report["server"]
    context = report["context"]
    catalog = report["catalog"]
    decision = report["decision"]

    print("Jellyfin Media Assistant — READ-ONLY LOCAL CATALOG SEARCH")
    print("Only HTTP GET requests are permitted by this test client.")
    print()
    print(
        f"Server: {server.get('name') or '<unknown>'} "
        f"{server.get('version') or ''}".rstrip()
    )
    print(f"Original query: {report['query']}")
    supplied_context = ", ".join(
        f"{key}={value}"
        for key, value in context.items()
        if value not in (None, "")
    )
    print(f"Context: {supplied_context or '<none>'}")
    print()
    print(
        "Catalog snapshot: "
        f"types={','.join(catalog['requested_types'])}; "
        f"{catalog['pages']} pages; {catalog['raw_items']} raw; "
        f"{catalog['indexed_records']} logical indexed; "
        f"{catalog['logical_groups']} provider groups "
        f"({catalog['grouped_physical_items']} absorbed records); "
        f"{catalog['duplicates']} duplicate IDs; "
        f"{catalog['index_issues']} index issues"
    )
    print(
        f"Eligible records: {catalog['eligible_records']}; "
        f"shortlist: {catalog['shortlist_size']}"
    )
    manager = report.get("manager")
    if manager:
        def duration(name: str) -> str:
            value = manager.get(name)
            return "n/a" if value is None else f"{value:.1f} ms"

        age = manager.get("cache_age_seconds")
        age_text = "n/a" if age is None else f"{age:.1f} s"
        print(
            "Catalog manager: "
            f"source={manager['source']}; cache age={age_text}; "
            f"cache load={duration('last_cache_load_duration_ms')}; "
            f"refresh={duration('last_refresh_duration_ms')}; "
            f"index build={duration('last_index_build_duration_ms')}; "
            f"cache write={duration('last_cache_write_duration_ms')}; "
            f"search={duration('last_search_duration_ms')}"
        )
        if manager.get("last_error"):
            print(f"Catalog manager warning: {manager['last_error']}")
    print()

    print(f"Decision: {decision['status']} ({decision['reason']})")
    print(f"Active family: {decision['active_family'] or '<none>'}")
    print(f"Automatic selection allowed: {decision['automatic_selection_allowed']}")
    if decision["observed_margin"] is not None:
        print(
            f"Observed margin: {decision['observed_margin']} "
            f"(required: {decision['required_margin']})"
        )

    selected = decision["selected"]
    if selected:
        print(
            "Selected: "
            f"{selected['title']} [{selected['media_type'] or 'unknown'}] "
            f"id={selected['id']}"
        )
        if len(selected.get("physical_ids", ())) > 1:
            print(
                "Logical entity IDs: "
                + ", ".join(selected["physical_ids"])
            )
        if selected.get("provider_ids"):
            providers = ", ".join(
                f"{key}={value}"
                for key, value in selected["provider_ids"].items()
            )
            print(f"Provider IDs: {providers}")
        alias_suffix = (
            f" via alias={selected['matched_alias']!r}"
            if selected.get("matched_alias")
            else ""
        )
        print(
            "Match: "
            f"{selected['family']}/{selected['method']}{alias_suffix}; "
            f"lexical={selected['lexical_score']}, "
            f"phonetic={selected['phonetic_score']}, "
            f"context={selected['context_score']}, total={selected['total_score']}"
        )
    print()

    ranked = report["ranked_candidates"][:max_results]
    print(f"Ranked candidates ({len(ranked)} shown):")
    if not ranked:
        print("  <none>")
    for index, item in enumerate(ranked, 1):
        metadata = [item["media_type"]]
        if item["artist"]:
            metadata.append(f"artist={item['artist']}")
        if item["album"]:
            metadata.append(f"album={item['album']}")
        if item["series"]:
            metadata.append(f"series={item['series']}")
        if item["year"]:
            metadata.append(f"year={item['year']}")
        metadata_text = ", ".join(str(value) for value in metadata if value)
        print(f"  {index}. {item['title']} ({metadata_text or 'no metadata'})")
        print(
            "     "
            f"id={item['id']}"
            + (
                f" ids={','.join(item['physical_ids'])}"
                if len(item.get('physical_ids', ())) > 1
                else ""
            )
            + f" | {item['family']}/{item['method']} | "
            f"lexical={item['lexical_score']} phonetic={item['phonetic_score']} "
            f"context={item['context_score']} total={item['total_score']}"
        )
        print(
            "     shortlisted by: "
            f"{', '.join(item['shortlisted_by']) or '<unknown>'}"
        )

def _context_from_args(args: argparse.Namespace) -> MediaSearchContext:
    return MediaSearchContext(
        media_type=args.media_type,
        artist=args.artist,
        album=args.album,
        series=args.series,
        year=args.year,
    )


async def run(args: argparse.Namespace) -> int:
    settings = merged_environment(args.env_file)
    api = JellyfinReadOnlyApi(
        server_url=required_setting(settings, "JELLYFIN_URL"),
        api_key=required_setting(settings, "JELLYFIN_API_KEY"),
        verify_ssl=parse_bool(settings.get("JELLYFIN_VERIFY_SSL"), default=True),
    )
    user_id = required_setting(settings, "JELLYFIN_USER_ID")

    server = await api.validate_connection()
    client = JellyfinCatalogClient(api=api, user_id=user_id)
    context = _context_from_args(args)

    if args.catalog:
        requested_types = [args.media_type] if args.media_type else None

        async def snapshot_loader() -> Any:
            return await load_catalog_snapshot(
                client.fetch_catalog_page,
                item_types=requested_types,
                page_size=args.catalog_page_size,
                max_items=args.catalog_max_items or None,
            )

        server_identity = str(server.get("Id") or api.server_url)
        cache_store = None
        if not args.no_catalog_cache and not args.catalog_max_items:
            cache_path = args.catalog_cache_dir / catalog_cache_filename(requested_types)
            cache_store = CatalogCacheStore(cache_path)

        manager = CatalogManager(
            snapshot_loader=snapshot_loader,
            requested_types=requested_types,
            cache_identity=f"{server_identity}:{user_id}",
            cache_store=cache_store,
            allow_truncated_snapshots=bool(args.catalog_max_items),
        )
        cache_loaded = await manager.async_load_cache()
        if args.refresh_catalog or not cache_loaded:
            try:
                await manager.async_refresh()
            except CatalogRefreshError:
                if manager.index is None:
                    raise

        managed = manager.search(args.query, context=context)
        snapshot = manager.snapshot
        index = manager.index
        if snapshot is None or index is None:  # pragma: no cover - defensive
            raise CatalogRefreshError("catalog manager did not produce an index")
        report = local_outcome_dict(
            managed.outcome,
            snapshot=snapshot,
            index=index,
            server=server,
            manager_diagnostics=managed.diagnostics,
        )
        if args.json:
            print(json.dumps(report, indent=2, ensure_ascii=False, default=str))
        else:
            print_local_human_report(report, max_results=args.max_results)
        return 0

    outcome = await retrieve_rank_and_decide(
        args.query,
        client,
        context=context,
    )
    report = outcome_dict(outcome, server)

    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False, default=str))
    else:
        print_human_report(report, max_results=args.max_results)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.max_results <= 0:
        parser.error("--max-results must be positive")
    if args.catalog_page_size <= 0:
        parser.error("--catalog-page-size must be positive")
    if args.catalog_max_items < 0:
        parser.error("--catalog-max-items must not be negative")
    if (args.refresh_catalog or args.no_catalog_cache) and not args.catalog:
        parser.error("catalog cache options require --catalog")

    try:
        return asyncio.run(run(args))
    except (
        JellyfinLiveConfigurationError,
        JellyfinReadOnlyError,
        JellyfinCatalogConfigurationError,
        JellyfinCatalogResponseError,
        CatalogPageResponseError,
        CatalogRefreshError,
        ValueError,
    ) as err:
        print(f"Live search failed: {err}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Live search cancelled.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
