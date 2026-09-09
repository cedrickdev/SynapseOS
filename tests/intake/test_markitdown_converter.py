"""Integration coverage for the isolated MarkItDown worker."""

from __future__ import annotations

import asyncio
import io
import subprocess
import sys
import zipfile

from core.intake import ClientDocument, DocumentConversionRequest, DocumentFormat
from infrastructure.intake import MarkItDownDocumentConverter
from infrastructure.intake.markitdown import _read_bounded


def _minimal_docx() -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" '
            'ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/word/document.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
            "</Types>",
        )
        archive.writestr(
            "_rels/.rels",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/'
            'officeDocument" '
            'Target="word/document.xml"/>'
            "</Relationships>",
        )
        archive.writestr(
            "word/document.xml",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            "<w:body><w:p><w:r><w:t>SynapseOS client requirement</w:t></w:r></w:p></w:body>"
            "</w:document>",
        )
    return output.getvalue()


def test_converter_uses_isolated_worker_for_local_docx() -> None:
    document = ClientDocument(
        project_id="project-1",
        source_id="upload-1",
        filename="requirements.docx",
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        content=_minimal_docx(),
        retention_policy="EPHEMERAL",
        sensitivity="INTERNAL",
        provider_processing_approved=True,
    )
    request = DocumentConversionRequest(document=document, format=DocumentFormat.DOCX)

    result = asyncio.run(MarkItDownDocumentConverter(timeout_seconds=10).convert(request))

    assert "SynapseOS client requirement" in result.markdown


def test_parent_reader_drains_but_retains_only_bounded_output() -> None:
    async def exercise() -> tuple[bytes, bool]:
        reader = asyncio.StreamReader()
        reader.feed_data(b"x" * 300_000)
        reader.feed_eof()
        return await _read_bounded(reader, 1_024)

    content, truncated = asyncio.run(exercise())

    assert content == b"x" * 1_024
    assert truncated is True


def test_worker_python_runtime_denies_network_sockets() -> None:
    script = (
        "import socket; "
        "from infrastructure.intake.markitdown_worker import _install_runtime_denials; "
        "_install_runtime_denials(); socket.socket()"
    )

    completed = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        check=False,
        text=True,
        timeout=5,
    )

    assert completed.returncode != 0
    assert "network access is disabled" in completed.stderr


def test_worker_python_runtime_denies_child_processes() -> None:
    script = (
        "import subprocess,sys; "
        "from infrastructure.intake.markitdown_worker import _install_runtime_denials; "
        "_install_runtime_denials(); subprocess.run([sys.executable, '-V'], check=False)"
    )

    completed = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        check=False,
        text=True,
        timeout=5,
    )

    assert completed.returncode != 0
    assert "child processes are disabled" in completed.stderr
