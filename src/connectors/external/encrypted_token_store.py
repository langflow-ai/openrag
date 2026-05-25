"""OpenRAG's encrypted-at-rest TokenStore.

Implements the structural ``TokenStore`` Protocol from
``openrag_connectors.token_store`` — duck typing, not inheritance.
``LibraryBackend`` injects this into every external connector so tokens live
encrypted on disk alongside the rest of OpenRAG's connection state.
"""

import os
from typing import Optional, Tuple


class EncryptedFileTokenStore:
    def __init__(self, file_path: str):
        self.file_path = file_path

    async def load(self) -> tuple[str | None, bool]:
        from utils.encryption import read_encrypted_file

        return await read_encrypted_file(self.file_path)

    async def save(self, data: str) -> None:
        from utils.encryption import write_encrypted_file

        parent = os.path.dirname(os.path.abspath(self.file_path))
        if parent and not os.path.exists(parent):
            os.makedirs(parent, exist_ok=True)
        await write_encrypted_file(self.file_path, data)

    async def delete(self) -> None:
        if os.path.exists(self.file_path):
            os.remove(self.file_path)
