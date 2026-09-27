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

Two writes contend when they could land on the same indexed document, which is
the boundary ``build_replace_filename_query`` already draws for the delete a
replace performs: a write collides with anything ownerless, and with anything
owned by the same user. So a shared write contends with every other write for
that name, while two users' private writes do not — neither can see the other's
document, and their chunks are written under different ownership scopes
(``DocumentIndexWriter._scoped_chunk_id``).

In-process only. That is the same single-worker assumption the RBAC and
identity caches already make (see AGENTS.md); with several workers, two files
landing in different processes fall back to the pre-existing behaviour.
"""

from collections.abc import Iterable
from dataclasses import dataclass

from utils.file_utils import get_filename_aliases
from utils.logging_config import get_logger

logger = get_logger(__name__)


# Error recorded on a file whose skip turned out to describe an ingestion that
# never happened. Kept distinctive so failure classification can recognise it
# without colliding with the corruption/duplicate substring heuristics.
INFLIGHT_CLAIM_WINNER_FAILED_ERROR = (
    "Another file with this name was ingesting at the same time and did not finish, "
    "so this file was not ingested."
)


@dataclass(frozen=True)
class _Claim:
    """A name held by one in-flight file, and the layout it will be written in."""

    holder: str
    owner_user_id: str | None
    shared: bool


def _contends(claim: _Claim, owner_user_id: str | None, shared: bool) -> bool:
    """Whether a write by this owner, in this layout, could land on `claim`'s
    document.

    An ownerless document is visible to the whole instance and is what every
    user's duplicate check sees, so a shared write on either side makes the two
    contend. Otherwise they contend only when the same user owns both: another
    user's private document is invisible to the check and is written under a
    different ownership scope, so it cannot be collided with.

    A write with no owner at all is treated as shared, which is how it is
    indexed.
    """
    if shared or not owner_user_id or claim.shared or not claim.owner_user_id:
        return True
    return claim.owner_user_id == owner_user_id


class FilenameClaimRegistry:
    """Which in-flight file holds which filename, per ownership scope.

    Every method runs to completion without awaiting, so the event loop cannot
    interleave two claims for the same name — the check and the take are one
    step, which is the whole point of the registry.
    """

    def __init__(self) -> None:
        # alias -> holder -> claim. Several holders can sit under one alias when
        # they do not contend (two users' private writes of the same name).
        self._claims: dict[str, dict[str, _Claim]] = {}
        self._claimed_by: dict[str, set[str]] = {}
        # Who was turned away while a holder had the name. The holder's outcome
        # decides what their skip meant, so release() hands them back.
        self._refused: dict[str, set[str]] = {}

    def claim(self, holder: str, filename: str, *, owner_user_id: str | None, shared: bool) -> bool:
        """Take `filename` and its aliases for `holder`, or report the name as
        already in flight for a write this one would collide with.

        Re-claiming what this holder already holds succeeds, so a retry of the
        same file is never blocked by its own claim.
        """
        aliases = get_filename_aliases(filename)
        if not aliases:
            return True

        for alias in aliases:
            for existing in self._claims.get(alias, {}).values():
                if existing.holder == holder:
                    continue
                if not _contends(existing, owner_user_id, shared):
                    continue
                logger.info(
                    "Filename already claimed by an in-flight ingestion",
                    filename=filename,
                    owner_user_id=owner_user_id,
                    shared=shared,
                    holder=holder,
                    held_by=existing.holder,
                )
                self._refused.setdefault(existing.holder, set()).add(holder)
                return False

        claim = _Claim(holder=holder, owner_user_id=owner_user_id, shared=shared)
        for alias in aliases:
            self._claims.setdefault(alias, {})[holder] = claim
        self._claimed_by.setdefault(holder, set()).update(aliases)
        return True

    def release(self, holder: str) -> set[str]:
        """Drop everything `holder` claimed and report who was turned away for it.

        Safe to call for a holder that never claimed anything, which is the
        common case (a file that failed before reaching the duplicate gate).

        The refused holders come back because their outcome was decided on the
        assumption that this one would index the name: if it did not, their skip
        described something that never happened, and the caller has to say so.
        """
        for alias in self._claimed_by.pop(holder, ()):
            holders = self._claims.get(alias)
            if holders is None:
                continue
            holders.pop(holder, None)
            if not holders:
                del self._claims[alias]
        return self._refused.pop(holder, set())

    def is_awaiting_outcome(self, holder: str) -> bool:
        """True while a name this holder was refused is still held by someone.

        The refusal decided that file's outcome on the assumption the holder
        would index the name. Until the holder reaches a terminal state that
        assumption is unsettled, so anything staged for the refused file has to
        stay put — it may yet be handed back for a retry.
        """
        return any(holder in refused for refused in self._refused.values())

    def holder_for(self, filename: str, *, owner_user_id: str | None, shared: bool) -> str | None:
        """The in-flight holder a write like this would contend with, if any."""
        for alias in get_filename_aliases(filename):
            for existing in self._claims.get(alias, {}).values():
                if _contends(existing, owner_user_id, shared):
                    return existing.holder
        return None

    def clear(self) -> None:
        self._claims.clear()
        self._claimed_by.clear()
        self._refused.clear()


# One registry per process: ingestion is driven by the singleton TaskService.
filename_claims = FilenameClaimRegistry()


def claim_holder(task_id: str, file_key: str) -> str:
    """Stable identity for one file's run within one task."""
    return f"{task_id}:{file_key}"


def release_claims(task_id: str, file_keys: Iterable[str]) -> None:
    for file_key in file_keys:
        filename_claims.release(claim_holder(task_id, file_key))
