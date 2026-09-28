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
    filename_claims,
)


def test_first_holder_wins_and_second_is_refused():
    registry = FilenameClaimRegistry()

    assert registry.claim("task-1:a", "report.pdf", owner_user_id="alice", shared=False) is True
    assert registry.claim("task-1:b", "report.pdf", owner_user_id="alice", shared=False) is False


def test_release_frees_the_name():
    registry = FilenameClaimRegistry()
    registry.claim("task-1:a", "report.pdf", owner_user_id="alice", shared=False)

    registry.release("task-1:a")

    assert registry.claim("task-1:b", "report.pdf", owner_user_id="alice", shared=False) is True


def test_same_holder_can_reclaim_its_own_name():
    """A retry of the same file must not be blocked by its own claim."""
    registry = FilenameClaimRegistry()

    assert registry.claim("task-1:a", "report.pdf", owner_user_id="alice", shared=False) is True
    assert registry.claim("task-1:a", "report.pdf", owner_user_id="alice", shared=False) is True


def test_aliases_contest_the_same_claim():
    """notes.txt is indexed as notes.md by the legacy Langflow path, so the two
    names are one name for duplicate purposes — here too."""
    registry = FilenameClaimRegistry()

    assert registry.claim("task-1:a", "notes.txt", owner_user_id="alice", shared=False) is True
    assert registry.claim("task-1:b", "notes.md", owner_user_id="alice", shared=False) is False


def test_other_owners_do_not_contest():
    """Another user's private document with this name is not a duplicate, and
    is invisible to the check that would find it."""
    registry = FilenameClaimRegistry()

    assert registry.claim("task-1:a", "report.pdf", owner_user_id="alice", shared=False) is True
    assert registry.claim("task-2:a", "report.pdf", owner_user_id="bob", shared=False) is True


def test_a_shared_write_contends_with_the_same_user_s_private_write():
    """The case the scope-string keying missed. A private write's duplicate
    check sees ownerless documents, so the two can land on one name — on the
    connector re-sync path each file resolves `shared` from its own indexed
    state, so two files heading for one name can disagree."""
    registry = FilenameClaimRegistry()

    assert registry.claim("task-1:a", "report.pdf", owner_user_id="alice", shared=True) is True
    assert registry.claim("task-1:b", "report.pdf", owner_user_id="alice", shared=False) is False


def test_a_private_write_contends_with_an_existing_shared_claim_of_another_user():
    """An ownerless document is visible instance-wide, so it is what every
    user's duplicate check sees."""
    registry = FilenameClaimRegistry()

    assert registry.claim("task-1:a", "report.pdf", owner_user_id="alice", shared=True) is True
    assert registry.claim("task-2:a", "report.pdf", owner_user_id="bob", shared=False) is False


def test_two_shared_writes_contend():
    registry = FilenameClaimRegistry()

    assert registry.claim("task-1:a", "report.pdf", owner_user_id="alice", shared=True) is True
    assert registry.claim("task-2:a", "report.pdf", owner_user_id="bob", shared=True) is False


def test_an_ownerless_write_is_treated_as_shared():
    registry = FilenameClaimRegistry()

    assert registry.claim("task-1:a", "report.pdf", owner_user_id=None, shared=False) is True
    assert registry.claim("task-2:a", "report.pdf", owner_user_id="bob", shared=False) is False


def test_release_of_an_unknown_holder_is_a_no_op():
    """Most files never reach the duplicate gate's claim — failed downloads,
    unsupported types — and TaskService releases for all of them."""
    registry = FilenameClaimRegistry()

    registry.release("task-1:never-claimed")  # must not raise


def test_blank_filename_claims_nothing():
    registry = FilenameClaimRegistry()

    assert registry.claim("task-1:a", "", owner_user_id="alice", shared=False) is True
    assert registry.claim("task-1:b", "", owner_user_id="alice", shared=False) is True


def test_releasing_one_holder_leaves_the_others_alone():
    registry = FilenameClaimRegistry()
    registry.claim("task-1:a", "a.pdf", owner_user_id="alice", shared=False)
    registry.claim("task-1:b", "b.pdf", owner_user_id="alice", shared=False)

    registry.release("task-1:a")

    assert registry.holder_for("a.pdf", owner_user_id="alice", shared=False) is None
    assert registry.holder_for("b.pdf", owner_user_id="alice", shared=False) == "task-1:b"


def test_holder_identity_is_per_file_within_a_task():
    assert claim_holder("task-1", "/tmp/a.pdf") != claim_holder("task-1", "/tmp/b.pdf")
    assert claim_holder("task-1", "/tmp/a.pdf") != claim_holder("task-2", "/tmp/a.pdf")


@pytest.mark.asyncio
async def test_module_registry_is_clean_between_tests():
    """The autouse fixture in conftest clears it; without that, a claim leaked
    by a test driving process_item directly would skip a later test's file."""
    assert filename_claims.holder_for("report.pdf", owner_user_id="alice", shared=False) is None


def test_release_reports_who_was_turned_away():
    """The holder's outcome decides what the refused files' skips meant, so the
    registry has to remember them."""
    registry = FilenameClaimRegistry()
    registry.claim("task-1:a", "report.pdf", owner_user_id="alice", shared=False)

    assert registry.claim("task-1:b", "report.pdf", owner_user_id="alice", shared=False) is False
    assert registry.claim("task-1:c", "report.pdf", owner_user_id="alice", shared=False) is False

    assert registry.release("task-1:a") == {"task-1:b", "task-1:c"}


def test_release_reports_nobody_when_no_one_was_refused():
    registry = FilenameClaimRegistry()
    registry.claim("task-1:a", "report.pdf", owner_user_id="alice", shared=False)

    assert registry.release("task-1:a") == set()


def test_refusals_do_not_leak_to_the_next_holder():
    """Whoever takes the name next starts with a clean slate — the previous
    holder's losers were already accounted for."""
    registry = FilenameClaimRegistry()
    registry.claim("task-1:a", "report.pdf", owner_user_id="alice", shared=False)
    registry.claim("task-1:b", "report.pdf", owner_user_id="alice", shared=False)
    registry.release("task-1:a")

    registry.claim("task-1:b", "report.pdf", owner_user_id="alice", shared=False)

    assert registry.release("task-1:b") == set()
