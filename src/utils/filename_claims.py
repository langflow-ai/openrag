"""In-flight claims on the filename a document is about to be indexed under.

Duplicate detection asks OpenSearch whether a name is taken, which can only
answer for what is already indexed. Files within a task are ingested
concurrently (``TaskService`` runs them under a worker semaphore), so two files
heading for the same name are both told "no" and both proceed:

  * chunk ids are content-derived, so the two documents do not overwrite each
    other — the index ends up with one filename whose chunks come from two
    different files, and deleting "it" deletes both;
  * with ``replace_duplicates`` on (the default for uploads) the later file
    deletes the earlier one's chunks mid-flight instead, and the earlier file's
    task still reports success.

Neither is reachable by looking at the index, because at the moment each file
checks, the other has not written yet. Claiming the name for the duration of
one file's ingestion turns that race into an ordinary duplicate: the first file
to claim proceeds, the rest take the existing "a file with this name already
exists" skip.

Claims cover every alias a name can be indexed under (``get_filename_aliases``),
so ``notes.txt`` and ``notes.md`` in one batch contest the same claim, matching
what the duplicate check and the delete path already treat as one name.

Scoped by ownership, mirroring ``DocumentIndexWriter._scoped_chunk_id`` and the
DLS rules the duplicate check runs under: another user's private document with
the same name is not a duplicate and is invisible to the check anyway.

In-process only. That is the same single-worker assumption the RBAC and
identity caches already make (see AGENTS.md); with several workers, two files
landing in different processes fall back to the pre-existing behaviour.
"""

from collections.abc import Iterable

from utils.file_utils import get_filename_aliases
from utils.logging_config import get_logger

logger = get_logger(__name__)


def claim_scope(owner_user_id: str | None, shared: bool) -> str:
    """The visibility scope a claim belongs to.

    Shared (ownerless) writes all land in one scope; private writes are scoped
    to their owner.
    """
    return "shared" if shared or not owner_user_id else f"owner:{owner_user_id}"


class FilenameClaimRegistry:
    """Which in-flight file holds which filename, per ownership scope.

    Every method runs to completion without awaiting, so the event loop cannot
    interleave two claims for the same name — the check and the take are one
    step, which is the whole point of the registry.
    """

    def __init__(self) -> None:
        self._holders: dict[tuple[str, str], str] = {}
        self._claimed_by: dict[str, set[tuple[str, str]]] = {}

    def claim(self, holder: str, scope: str, filename: str) -> bool:
        """Take `filename` and its aliases for `holder`, or report the name as
        already in flight.

        Re-claiming what this holder already holds succeeds, so a retry of the
        same file is never blocked by its own claim.
        """
        keys = [(scope, alias) for alias in get_filename_aliases(filename)]
        if not keys:
            return True

        for key in keys:
            current = self._holders.get(key)
            if current is not None and current != holder:
                logger.info(
                    "Filename already claimed by an in-flight ingestion",
                    filename=filename,
                    scope=scope,
                    holder=holder,
                    held_by=current,
                )
                return False

        for key in keys:
            self._holders[key] = holder
        self._claimed_by.setdefault(holder, set()).update(keys)
        return True

    def release(self, holder: str) -> None:
        """Drop everything `holder` claimed. Safe to call for a holder that
        never claimed anything, which is the common case (a file that failed
        before reaching the duplicate gate)."""
        for key in self._claimed_by.pop(holder, ()):
            if self._holders.get(key) == holder:
                del self._holders[key]

    def holds(self, scope: str, filename: str) -> str | None:
        """The holder of this name, for tests and diagnostics."""
        for alias in get_filename_aliases(filename):
            holder = self._holders.get((scope, alias))
            if holder is not None:
                return holder
        return None

    def clear(self) -> None:
        self._holders.clear()
        self._claimed_by.clear()


# One registry per process: ingestion is driven by the singleton TaskService.
filename_claims = FilenameClaimRegistry()


def claim_holder(task_id: str, file_key: str) -> str:
    """Stable identity for one file's run within one task."""
    return f"{task_id}:{file_key}"


def release_claims(task_id: str, file_keys: Iterable[str]) -> None:
    for file_key in file_keys:
        filename_claims.release(claim_holder(task_id, file_key))
