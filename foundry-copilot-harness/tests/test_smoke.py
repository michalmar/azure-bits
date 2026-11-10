import json
from types import SimpleNamespace

import pytest

from scenario import REFERENCE
from smoke import check_reports


@pytest.mark.asyncio
async def test_read_only_report_check_downloads_all_deliverables():
    names = {
        "file-json": "budget.json", "file-csv": "budget.csv", "file-md": "recommendation.md",
    }
    content = {
        "file-json": json.dumps(REFERENCE).encode(),
        "file-csv": (
            b"id,base_czk,total_czk,eligible,reasons\n"
            b"A,19200,21120.00,True,\nB,24400,26840.00,False,budget\n"
            b"C,14000,15400.00,False,capacity;projector\n"
        ),
        "file-md": "Fiktivní nabídky: vítěz Atelier A.".encode(),
    }

    async def retrieve(identifier):
        return SimpleNamespace(filename=names[identifier])

    async def read_file(identifier):
        return content[identifier]

    service = SimpleNamespace(
        file_client=SimpleNamespace(files=SimpleNamespace(retrieve=retrieve)), read_file=read_file,
    )
    result = await check_reports(service, list(names))
    assert set(result) == {"budget.json", "budget.csv", "recommendation.md"}
    assert all(size > 0 for size in result.values())
    with pytest.raises(ValueError, match="three valid"):
        await check_reports(service, ["invalid.id", "file-csv", "file-md"])
