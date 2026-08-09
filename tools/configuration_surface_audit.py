"""Audit tracked files for public-release configuration and privacy risks.

Step 41B removes knowledge of any specific household from this audit. The
remaining checks are structural: private addresses, inline Jellyfin user IDs,
non-example entities in the public Home Assistant reference, local storage
paths, sensitive tracked files, and known temporary configuration debt.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath
import re
import subprocess
from typing import Iterable, Pattern


@dataclass(frozen=True, slots=True)
class SurfaceRule:
    """One public-release configuration or privacy rule."""

    name: str
    category: str
    pattern: Pattern[str]
    baseline_max: int
    scan_prefixes: tuple[str, ...] = ()
    scan_paths: tuple[str, ...] = ()
    allowed_prefixes: tuple[str, ...] = ()
    allowed_paths: tuple[str, ...] = ()

    def path_should_scan(self, relative_path: str) -> bool:
        """Return whether this rule applies to the repository path."""

        normalized = PurePosixPath(relative_path).as_posix()
        if not self.scan_prefixes and not self.scan_paths:
            return True
        return normalized in self.scan_paths or any(
            normalized.startswith(prefix) for prefix in self.scan_prefixes
        )

    def path_is_allowed(self, relative_path: str) -> bool:
        """Return whether a finding is confined to an approved reference area."""

        normalized = PurePosixPath(relative_path).as_posix()
        return normalized in self.allowed_paths or any(
            normalized.startswith(prefix) for prefix in self.allowed_prefixes
        )


@dataclass(frozen=True, slots=True)
class Finding:
    """One matched repository location."""

    rule_name: str
    category: str
    path: str
    line_number: int
    matched_text: str


@dataclass(frozen=True, slots=True)
class AuditResult:
    """Complete audit result for one repository snapshot."""

    tracked_files: tuple[str, ...]
    findings: tuple[Finding, ...]
    unapproved_findings: tuple[Finding, ...]
    baseline_overages: tuple[str, ...]
    sensitive_tracked_files: tuple[str, ...]

    @property
    def passed(self) -> bool:
        """Return whether the current repository satisfies the audit."""

        return not (
            self.unapproved_findings
            or self.baseline_overages
            or self.sensitive_tracked_files
        )


_PUBLIC_HA_REFERENCE = "reference/current-working/home-assistant/"
_UPSTREAM_JELLYHA_REFERENCE = "reference/current-working/jellyha/"
_REFERENCE_TESTS = "tests/reference/"

_PRIVATE_NETWORK_LITERAL = re.compile(
    r"\b(?:"
    r"10(?:\.\d{1,3}){3}|"
    r"192\.168(?:\.\d{1,3}){2}|"
    r"172\.(?:1[6-9]|2\d|3[01])(?:\.\d{1,3}){2}"
    r")\b"
)
_INLINE_JELLYFIN_USER_ID = re.compile(
    r"(?:UserId=|user_id[^\n]{0,20}?)[0-9a-f]{32}",
    re.IGNORECASE,
)
_NON_EXAMPLE_PUBLIC_PLAYER = re.compile(
    r"media_player\.(?!example(?:_|\b)|media_stop\b|turn_on\b)[a-z0-9_]+",
    re.IGNORECASE,
)
_HARDCODED_DEFAULT_PLAYER = re.compile(
    r"else\s+['\"]media_player\.[a-z0-9_]+['\"]",
    re.IGNORECASE,
)

SURFACE_RULES: tuple[SurfaceRule, ...] = (
    SurfaceRule(
        name="private_network_literal",
        category="instance_specific",
        pattern=_PRIVATE_NETWORK_LITERAL,
        baseline_max=16,
        allowed_prefixes=(_UPSTREAM_JELLYHA_REFERENCE,),
    ),
    SurfaceRule(
        name="inline_jellyfin_user_id",
        category="credential_adjacent",
        pattern=_INLINE_JELLYFIN_USER_ID,
        baseline_max=0,
    ),
    SurfaceRule(
        name="non_example_public_media_player",
        category="instance_specific",
        pattern=_NON_EXAMPLE_PUBLIC_PLAYER,
        baseline_max=0,
        scan_prefixes=(_PUBLIC_HA_REFERENCE,),
    ),
    SurfaceRule(
        name="household_storage_path",
        category="instance_specific",
        pattern=re.compile(r"/volume\d+/", re.IGNORECASE),
        baseline_max=0,
    ),
    SurfaceRule(
        name="hardcoded_home_assistant_config_entry_id",
        category="instance_specific",
        pattern=re.compile(
            r"config_entry_id:\s*(?:[0-9A-HJKMNP-TV-Z]{26}|[0-9a-f]{32})\b",
            re.IGNORECASE,
        ),
        baseline_max=0,
        scan_prefixes=(
            _PUBLIC_HA_REFERENCE,
        ),
    ),
    SurfaceRule(
        name="hardcoded_default_player_fallback",
        category="configuration_debt",
        pattern=_HARDCODED_DEFAULT_PLAYER,
        baseline_max=7,
        scan_prefixes=(
            _PUBLIC_HA_REFERENCE,
            _REFERENCE_TESTS,
        ),
        allowed_prefixes=(
            _PUBLIC_HA_REFERENCE,
            _REFERENCE_TESTS,
        ),
    ),
    SurfaceRule(
        name="fixed_queue_service_port",
        category="configuration_debt",
        pattern=re.compile(r"(?<!\d)8787(?!\d)"),
        baseline_max=10,
        scan_paths=(
            "reference/current-working/home-assistant/configuration.yaml",
            "reference/current-working/queue-service/docker-compose.yml",
            "reference/current-working/queue-service/server.py",
        ),
        allowed_paths=(
            "reference/current-working/home-assistant/configuration.yaml",
            "reference/current-working/queue-service/docker-compose.yml",
            "reference/current-working/queue-service/server.py",
        ),
    ),
)

_AUDIT_EXCLUDED_PATHS = frozenset({"tools/configuration_surface_audit.py"})
_SENSITIVE_EXACT_NAMES = frozenset(
    {
        ".env",
        "secrets.yaml",
        "credentials.json",
        "id_rsa",
        "id_ed25519",
    }
)
_SENSITIVE_SUFFIXES = (".pem", ".p12", ".pfx")


def tracked_files(repository: Path) -> tuple[str, ...]:
    """Return Git-tracked files using repository-relative POSIX paths."""

    completed = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=repository,
        check=True,
        capture_output=True,
    )
    return tuple(
        item.decode("utf-8")
        for item in completed.stdout.split(b"\0")
        if item
    )


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return None


def _sensitive_tracked_files(paths: Iterable[str]) -> tuple[str, ...]:
    sensitive: list[str] = []
    for relative_path in paths:
        name = PurePosixPath(relative_path).name
        if name in _SENSITIVE_EXACT_NAMES or name.lower().endswith(_SENSITIVE_SUFFIXES):
            sensitive.append(relative_path)
    return tuple(sorted(sensitive))


def audit_repository(repository: Path) -> AuditResult:
    """Audit one repository against the current public-release ceiling."""

    repository = repository.resolve()
    paths = tracked_files(repository)
    findings: list[Finding] = []
    unapproved: list[Finding] = []
    counts = {rule.name: 0 for rule in SURFACE_RULES}

    for relative_path in paths:
        if relative_path in _AUDIT_EXCLUDED_PATHS:
            continue
        text = _read_text(repository / relative_path)
        if text is None:
            continue
        for line_number, line in enumerate(text.splitlines(), start=1):
            for rule in SURFACE_RULES:
                if not rule.path_should_scan(relative_path):
                    continue
                matches = tuple(rule.pattern.finditer(line))
                counts[rule.name] += len(matches)
                for match in matches:
                    finding = Finding(
                        rule_name=rule.name,
                        category=rule.category,
                        path=relative_path,
                        line_number=line_number,
                        matched_text=match.group(0),
                    )
                    findings.append(finding)
                    if not rule.path_is_allowed(relative_path):
                        unapproved.append(finding)

    overages = tuple(
        f"{rule.name}: {counts[rule.name]} > baseline {rule.baseline_max}"
        for rule in SURFACE_RULES
        if counts[rule.name] > rule.baseline_max
    )

    return AuditResult(
        tracked_files=paths,
        findings=tuple(findings),
        unapproved_findings=tuple(unapproved),
        baseline_overages=overages,
        sensitive_tracked_files=_sensitive_tracked_files(paths),
    )


def repository_root() -> Path:
    """Return the repository root containing this module."""

    return Path(__file__).resolve().parents[1]


def _summary_lines(result: AuditResult) -> list[str]:
    counts: dict[str, int] = {rule.name: 0 for rule in SURFACE_RULES}
    for finding in result.findings:
        counts[finding.rule_name] += 1

    lines = [
        "Configuration surface audit",
        f"Tracked files: {len(result.tracked_files)}",
    ]
    for rule in SURFACE_RULES:
        lines.append(
            f"- {rule.name}: {counts[rule.name]} "
            f"(baseline ceiling {rule.baseline_max})"
        )

    if result.sensitive_tracked_files:
        lines.append("Sensitive tracked files:")
        lines.extend(f"- {path}" for path in result.sensitive_tracked_files)
    if result.unapproved_findings:
        lines.append("Findings outside approved reference areas:")
        lines.extend(
            f"- {finding.rule_name}: {finding.path}:{finding.line_number}"
            for finding in result.unapproved_findings
        )
    if result.baseline_overages:
        lines.append("Baseline overages:")
        lines.extend(f"- {message}" for message in result.baseline_overages)

    lines.append("PASS" if result.passed else "FAIL")
    return lines


def main() -> int:
    """Run the tracked-repository audit from the command line."""

    result = audit_repository(repository_root())
    print("\n".join(_summary_lines(result)))
    return 0 if result.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
