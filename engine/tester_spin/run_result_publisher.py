from __future__ import annotations

import atexit
import json
import os
import re
import subprocess
import tempfile
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote, unquote_plus, urlsplit, urlunsplit

from tester_spin.models import GameTestResult, utc_now_iso
from tester_spin.run_diagnostics import sanitize

Progress = Callable[[str], None]
RESULT_BRANCH = "tester-spin-runs"
RESULT_ROOT = "run-results"
EXPECTED_REPOSITORY = "shisetsu-code/tester-spin"
MAX_TEXT_FILE_BYTES = 2 * 1024 * 1024
MAX_DOCUMENT_SOURCE_BYTES = 16 * 1024 * 1024
_TEXT_SUFFIXES = {".json", ".jsonl", ".txt", ".raw", ".log"}
_URL = re.compile(r'''\b(?:https?|wss?)://[^\s<>"']+''', re.IGNORECASE)
_PARAMETER = re.compile(r'''(?<![\w.%+~\[\]-])(?P<name>[\w.%+~\[\]-]+)=(?P<value>[^\s&"'<>]*)''')
_RAW_AUTHORIZATION = re.compile(r'(?i)(?<![\w-])(?:proxy-)?authorization[ \t]*:[ \t]*')
_RAW_HEADER_LINE = re.compile(r"^[ \t]*[!#$%&'*+.^_`|~\w-]+[ \t]*:")
_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="github-result-publisher")


def _subprocess_window_kwargs() -> dict[str, Any]:
    """Keep helper processes invisible when Tester-Spin runs under pythonw on Windows."""
    if os.name != "nt":
        return {}

    kwargs: dict[str, Any] = {}
    create_no_window = int(getattr(subprocess, "CREATE_NO_WINDOW", 0) or 0)
    if create_no_window:
        kwargs["creationflags"] = create_no_window

    startupinfo_factory = getattr(subprocess, "STARTUPINFO", None)
    if startupinfo_factory is not None:
        startupinfo = startupinfo_factory()
        startupinfo.dwFlags |= int(getattr(subprocess, "STARTF_USESHOWWINDOW", 0) or 0)
        startupinfo.wShowWindow = int(getattr(subprocess, "SW_HIDE", 0) or 0)
        kwargs["startupinfo"] = startupinfo
    return kwargs


def _safe_component(value: str) -> str:
    clean = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value or "").strip()).strip("._")
    return clean[:140] or "unknown"


def _repo_root() -> Path | None:
    candidate = Path(__file__).resolve().parents[1]
    try:
        proc = subprocess.run(
            ["git", "-C", str(candidate), "rev-parse", "--show-toplevel"],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=10,
            **_subprocess_window_kwargs(),
        )
    except Exception:
        return None
    value = proc.stdout.strip()
    return Path(value) if value else None


def _git(repo: Path, *args: str, input_text: str | None = None, env: dict[str, str] | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
    merged = os.environ.copy()
    if env:
        merged.update(env)
    merged.setdefault("GIT_AUTHOR_NAME", "Tester-Spin Results")
    merged.setdefault("GIT_AUTHOR_EMAIL", "tester-spin-results@local.invalid")
    merged.setdefault("GIT_COMMITTER_NAME", merged["GIT_AUTHOR_NAME"])
    merged.setdefault("GIT_COMMITTER_EMAIL", merged["GIT_AUTHOR_EMAIL"])
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        input=input_text,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=check,
        timeout=45,
        env=merged,
        **_subprocess_window_kwargs(),
    )


def _origin_is_expected(repo: Path) -> bool:
    try:
        remote = _git(repo, "remote", "get-url", "origin").stdout.strip().lower()
    except Exception:
        return False
    normalized = remote.removesuffix(".git").replace(":", "/")
    return EXPECTED_REPOSITORY in normalized


def _current_commit(repo: Path) -> str:
    try:
        return _git(repo, "rev-parse", "HEAD").stdout.strip()
    except Exception:
        return ""


def _read_artifact(path: Path) -> tuple[str, Any]:
    text = path.read_text(encoding="utf-8", errors="replace")
    if path.suffix.casefold() == ".json":
        try:
            return "json", json.loads(text)
        except Exception:
            pass
    return "text", text


def _public_field(name: str, item: str) -> str:
    decoded = unquote_plus(name)
    cleaned = sanitize({decoded: item})[decoded]
    return name + '=' + (quote(cleaned, safe='') if cleaned != item else item)


def _public_parameter(match: re.Match[str]) -> str:
    return _public_field(match['name'], match['value'])


def _public_query(query: str) -> str:
    # Commas and semicolons can belong to one credential value. Within an
    # already parsed query only '&' separates fields; preserve public bytes.
    fields = []
    for field in query.split('&'):
        name, separator, item = field.partition('=')
        fields.append(_public_field(name, item) if separator else field)
    return '&'.join(fields)


def _public_url(match: re.Match[str]) -> str:
    try:
        parts = urlsplit(match.group())
        # Credentials in userinfo must never leave the local run directory.
        return urlunsplit(parts._replace(netloc=parts.netloc.rsplit('@', 1)[-1],
                                        query=_public_query(parts.query)))
    except ValueError:
        return '[REDACTED_URL]'


def _public_raw_authorization(value: str) -> str:
    """Remove complete raw header values, including HTTP continuation lines."""
    output = []
    authorization_prefix = None
    for line in value.splitlines(keepends=True):
        # JSONL records must be decoded by _public_value before touching their
        # strings; matching serialized header text would eat JSON punctuation.
        if line.lstrip().startswith(('{', '[')):
            try:
                json.loads(line)
            except ValueError:
                pass
            else:
                authorization_prefix = None
                output.append(line)
                continue
        if authorization_prefix is not None:
            content = line.removeprefix(authorization_prefix)
            # A log may repeat its prefix for each folded header line. New
            # headers (even indented ones) and blank lines end the value.
            if (content.startswith((' ', '\t')) and content.strip()
                    and not _RAW_HEADER_LINE.match(content)):
                continue
            authorization_prefix = None
        header = _RAW_AUTHORIZATION.search(line)
        if header:
            authorization_prefix = line[:header.start()]
            ending = line[len(line.rstrip('\r\n')):]
            line = line[:header.end()] + '[REDACTED]' + ending
        output.append(line)
    return ''.join(output)


def _public_value(value: Any) -> Any:
    """Reuse protocol and session-path sanitizers at the publication boundary."""
    if isinstance(value, dict):
        # Reuse the shared key/name-value policy without running its text regexes
        # over already serialized JSON children (where newlines are escaped).
        fields = {str(key): item for key, item in value.items()}
        policy = sanitize({key: item if key == 'name' and isinstance(item, str) else None
                           for key, item in fields.items()})
        return {key: '[REDACTED]' if policy[key] == '[REDACTED]' else _public_value(item)
                for key, item in fields.items()}
    if isinstance(value, (list, tuple)):
        return [_public_value(item) for item in value]
    if isinstance(value, str):
        from tester_spin.providers.bgaming.runtime import sanitize_error_text
        # Raw captures and JSONL can contain structured headers represented as
        # name/value records. Apply the same recursive policy without changing
        # the artifact's text encoding or inventing protocol fields.
        if value.lstrip().startswith(('{', '[')):
            try:
                decoded = json.loads(value)
            except ValueError:
                pass
            else:
                # The fields are already sanitized. Raw-text regexes applied to
                # this serialization could consume adjacent JSON punctuation.
                return json.dumps(_public_value(decoded), ensure_ascii=False)
        value = _public_raw_authorization(value)
        lines = value.splitlines(keepends=True)
        if len(lines) > 1:
            # Logs can start with plain text before independently parseable JSON
            # records; process each line regardless of the artifact's preamble.
            return ''.join(_public_value(line.rstrip('\r\n')) + line[len(line.rstrip('\r\n')):]
                           for line in lines)
        value = _URL.sub(_public_url, value)
        return sanitize(sanitize_error_text(_PARAMETER.sub(_public_parameter, value)))
    return value


def _private_artifact(path: Path) -> bool:
    return any(part.startswith('.') or re.search(r'(?i)(?:^|[._-])private(?:$|[._-])', part)
               for part in path.parts)


def build_result_document(result: GameTestResult, *, source_commit: str = "") -> dict[str, Any]:
    root = Path(str(result.run_dir or ""))
    artifacts: dict[str, Any] = {}
    skipped: list[dict[str, Any]] = []
    consumed = 0
    if result.run_dir and root.is_dir():
        priority_names = {"result.json", "path-coverage.json", "sample-catalog.json", "profile.json", "flow-choice-coverage.json", "game-structure.json"}
        failed_roots = [Path(a.artifact_dir).resolve() for a in result.attempts
                        if a.artifact_dir and (not a.ok or not a.terminal or a.warning or a.error)]
        def priority(path: Path) -> tuple[int, str]:
            if path.name in priority_names:
                return (0, path.as_posix())
            if any(path.resolve().is_relative_to(folder) for folder in failed_roots):
                return (1, path.as_posix())
            return (2, path.as_posix())
        for path in sorted((item for item in root.rglob("*") if item.is_file()
                            and item.resolve().is_relative_to(root.resolve())), key=priority):
            if (_private_artifact(path.relative_to(root))
                    or _private_artifact(path.resolve().relative_to(root.resolve()))):
                continue
            if path.suffix.casefold() not in _TEXT_SUFFIXES:
                continue
            try:
                size = path.stat().st_size
                relative = path.relative_to(root).as_posix()
            except OSError:
                continue
            if size > MAX_TEXT_FILE_BYTES:
                skipped.append({"path": relative, "bytes": size, "reason": "file_limit"})
                continue
            if consumed + size > MAX_DOCUMENT_SOURCE_BYTES:
                skipped.append({"path": relative, "bytes": size, "reason": "document_limit"})
                continue
            try:
                encoding, value = _read_artifact(path)
            except OSError:
                skipped.append({"path": relative, "bytes": size, "reason": "read_error"})
                continue
            artifacts[relative] = {"encoding": encoding, "bytes": size, "value": value}
            consumed += size

    result_payload = result.to_dict()
    if result_payload.get("run_dir"):
        result_payload["run_dir"] = root.name
    return _public_value({
        "schema": "tester-spin/github-run-result/v1",
        "published_at": utc_now_iso(),
        "source_commit": source_commit,
        "provider": result.provider,
        "game": {"slug": result.slug, "name": result.game_name, "symbol": result.symbol, "url": result.game_url},
        "result": result_payload,
        "artifact_bytes_embedded": consumed,
        "artifacts": artifacts,
        "skipped_artifacts": skipped,
    })


def result_document_path(result: GameTestResult) -> str:
    return f"{RESULT_ROOT}/{_safe_component(result.provider)}/{_safe_component(result.slug)}.json"


def _remote_parent(repo: Path) -> str:
    _git(repo, "fetch", "--quiet", "origin", f"refs/heads/{RESULT_BRANCH}:refs/remotes/origin/{RESULT_BRANCH}", check=False)
    probe = _git(repo, "rev-parse", "--verify", f"refs/remotes/origin/{RESULT_BRANCH}", check=False)
    return probe.stdout.strip() if probe.returncode == 0 else ""


def _commit_document(repo: Path, path: str, content: str, message: str) -> str:
    for attempt in range(2):
        parent = _remote_parent(repo)
        with tempfile.TemporaryDirectory(prefix="tester-spin-publish-") as temp:
            env = {"GIT_INDEX_FILE": str(Path(temp) / "index")}
            _git(repo, "read-tree", parent, env=env) if parent else _git(repo, "read-tree", "--empty", env=env)
            blob = _git(repo, "hash-object", "-w", "--stdin", input_text=content).stdout.strip()
            _git(repo, "update-index", "--add", "--cacheinfo", "100644", blob, path, env=env)
            tree = _git(repo, "write-tree", env=env).stdout.strip()
            args = ["commit-tree", tree]
            if parent:
                args.extend(["-p", parent])
            args.extend(["-m", message])
            commit = _git(repo, *args).stdout.strip()
        pushed = _git(repo, "push", "--quiet", "origin", f"{commit}:refs/heads/{RESULT_BRANCH}", check=False)
        if pushed.returncode == 0:
            return commit
        if attempt == 1:
            raise RuntimeError((pushed.stderr or pushed.stdout or "git push failed").strip())
    raise RuntimeError("No se pudo publicar el resultado.")


def publish_result_to_github(result: GameTestResult, *, progress: Progress | None = None) -> str:
    if str(os.environ.get("TESTER_SPIN_PUBLISH_RESULTS", "1")).strip().casefold() in {"0", "false", "no", "off"}:
        return ""
    if not result.run_dir or not Path(result.run_dir).is_dir():
        return ""
    repo = _repo_root()
    if repo is None or not _origin_is_expected(repo):
        if progress is not None:
            progress("GitHub resultados: checkout/origin de Tester-Spin no disponible; publicación omitida.")
        return ""
    document = build_result_document(result, source_commit=_current_commit(repo))
    path = result_document_path(result)
    commit = _commit_document(repo, path, json.dumps(document, ensure_ascii=False, indent=2), f"Record {result.provider} result for {result.slug}")
    if progress is not None:
        progress(f"GitHub resultados: {RESULT_BRANCH}/{path} actualizado ({commit[:7]}).")
    return commit


def _publish_safely(result: GameTestResult, progress: Progress | None) -> str:
    try:
        return publish_result_to_github(result, progress=progress)
    except Exception as exc:
        if progress is not None:
            progress(f"GitHub resultados ERROR (no afecta la prueba): {type(exc).__name__}: {exc}")
        return ""


def queue_result_publish(result: GameTestResult, *, progress: Progress | None = None) -> Future[str]:
    return _EXECUTOR.submit(_publish_safely, result, progress)


def _shutdown() -> None:
    _EXECUTOR.shutdown(wait=True, cancel_futures=False)


atexit.register(_shutdown)

__all__ = ["RESULT_BRANCH", "build_result_document", "publish_result_to_github", "queue_result_publish", "result_document_path"]
