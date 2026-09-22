"""In-flight filename claims (utils.filename_claims).

The duplicate gate asks OpenSearch whether a name is taken, which only sees
what is already indexed. Files inside a task are ingested concurrently, so two
files heading for the same name are both told "no". These cover the registry
that makes the second one resolve as a duplicate instead.
"""

import pytest

from utils.filename_claims import (
    FilenameClaimRegistry,
    claim_holder,
    claim_scope,
    filename_claims,
)


def test_first_holder_wins_and_second_is_refused():
    registry = FilenameClaimRegistry()

    assert registry.claim("task-1:a", "owner:alice", "report.pdf") is True
    assert registry.claim("task-1:b", "owner:alice", "report.pdf") is False


def test_release_frees_the_name():
    registry = FilenameClaimRegistry()
    registry.claim("task-1:a", "owner:alice", "report.pdf")

    registry.release("task-1:a")

    assert registry.claim("task-1:b", "owner:alice", "report.pdf") is True


def test_same_holder_can_reclaim_its_own_name():
    """A retry of the same file must not be blocked by its own claim."""
    registry = FilenameClaimRegistry()

    assert registry.claim("task-1:a", "owner:alice", "report.pdf") is True
    assert registry.claim("task-1:a", "owner:alice", "report.pdf") is True


def test_aliases_contest_the_same_claim():
    """notes.txt is indexed as notes.md by the legacy Langflow path, so the two
    names are one name for duplicate purposes — here too."""
    registry = FilenameClaimRegistry()

    assert registry.claim("task-1:a", "owner:alice", "notes.txt") is True
    assert registry.claim("task-1:b", "owner:alice", "notes.md") is False


def test_other_owners_do_not_contest():
    """Another user's private document with this name is not a duplicate, and
    is invisible to the check that would find it."""
    registry = FilenameClaimRegistry()

    assert registry.claim("task-1:a", "owner:alice", "report.pdf") is True
    assert registry.claim("task-2:a", "owner:bob", "report.pdf") is True


def test_shared_writes_share_one_scope():
    assert claim_scope("alice", shared=True) == claim_scope("bob", shared=True)
    assert claim_scope("alice", shared=False) != claim_scope("bob", shared=False)


def test_anonymous_writes_land_in_the_shared_scope():
    assert claim_scope(None, shared=False) == claim_scope("alice", shared=True)


def test_release_of_an_unknown_holder_is_a_no_op():
    """Most files never reach the duplicate gate's claim — failed downloads,
    unsupported types — and TaskService releases for all of them."""
    registry = FilenameClaimRegistry()

    registry.release("task-1:never-claimed")  # must not raise


def test_blank_filename_claims_nothing():
    registry = FilenameClaimRegistry()

    assert registry.claim("task-1:a", "owner:alice", "") is True
    assert registry.claim("task-1:b", "owner:alice", "") is True


def test_releasing_one_holder_leaves_the_others_alone():
    registry = FilenameClaimRegistry()
    registry.claim("task-1:a", "owner:alice", "a.pdf")
    registry.claim("task-1:b", "owner:alice", "b.pdf")

    registry.release("task-1:a")

    assert registry.holds("owner:alice", "a.pdf") is None
    assert registry.holds("owner:alice", "b.pdf") == "task-1:b"


def test_holder_identity_is_per_file_within_a_task():
    assert claim_holder("task-1", "/tmp/a.pdf") != claim_holder("task-1", "/tmp/b.pdf")
    assert claim_holder("task-1", "/tmp/a.pdf") != claim_holder("task-2", "/tmp/a.pdf")


@pytest.mark.asyncio
async def test_module_registry_is_clean_between_tests():
    """The autouse fixture in conftest clears it; without that, a claim leaked
    by a test driving process_item directly would skip a later test's file."""
    assert filename_claims.holds("owner:alice", "report.pdf") is None
