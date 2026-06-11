"""Checks that the SDK surfaces errors correctly instead of swallowing them."""

import io
import uuid

from harness import Check, Context, Skip
from openrag_sdk.exceptions import NotFoundError, OpenRAGError

from checks.common import supports_delete_by_filter_id


async def get_missing_conversation(ctx: Context) -> None:
    try:
        await ctx.client.chat.get(str(uuid.uuid4()))
    except NotFoundError:
        return
    raise AssertionError("chat.get on a missing conversation did not raise NotFoundError")


async def delete_missing_conversation(ctx: Context) -> None:
    result = await ctx.client.chat.delete(str(uuid.uuid4()))
    assert result is False, "deleting a missing conversation did not return False"


async def invalid_settings_value(ctx: Context) -> None:
    try:
        await ctx.client.settings.update({"chunk_size": -999999})
    except OpenRAGError:
        return
    raise AssertionError("invalid settings value did not raise OpenRAGError")


async def ingest_without_args(ctx: Context) -> None:
    try:
        await ctx.client.documents.ingest()
    except ValueError:
        return
    raise AssertionError("ingest() with no arguments did not raise ValueError")


async def ingest_file_object_without_filename(ctx: Context) -> None:
    try:
        await ctx.client.documents.ingest(file=io.BytesIO(b"content"))
    except ValueError:
        return
    raise AssertionError("ingest(file=...) without filename did not raise ValueError")


async def delete_with_filename_and_filter_id(ctx: Context) -> None:
    if not supports_delete_by_filter_id(ctx.client):
        raise Skip("documents.delete(filter_id=...) requires openrag-sdk >= 0.4.0")
    try:
        await ctx.client.documents.delete("foo.pdf", filter_id="something")
    except ValueError:
        return
    raise AssertionError("delete with both filename and filter_id did not raise ValueError")


async def bogus_filter_id_in_search(ctx: Context) -> None:
    try:
        await ctx.client.search.query("anything", filter_id=f"does-not-exist-{uuid.uuid4().hex}")
    except OpenRAGError:
        return
    raise AssertionError("search with a bogus filter_id did not raise OpenRAGError")


async def bogus_filter_id_in_chat(ctx: Context) -> None:
    try:
        await ctx.client.chat.create(message="hi", filter_id=f"does-not-exist-{uuid.uuid4().hex}")
    except OpenRAGError:
        return
    raise AssertionError("chat with a bogus filter_id did not raise OpenRAGError")


CHECKS = [
    Check("errors.get_missing_conversation", get_missing_conversation),
    Check("errors.delete_missing_conversation", delete_missing_conversation),
    Check("errors.invalid_settings_value", invalid_settings_value),
    Check("errors.ingest_without_args", ingest_without_args),
    Check("errors.ingest_file_object_without_filename", ingest_file_object_without_filename),
    Check("errors.delete_with_filename_and_filter_id", delete_with_filename_and_filter_id),
    Check("errors.bogus_filter_id_in_search", bogus_filter_id_in_search),
    Check("errors.bogus_filter_id_in_chat", bogus_filter_id_in_chat),
]
