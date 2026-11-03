"""Reviewed static reference only; no database, agent runtime or provider imports."""
import json
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse


def create_public_reference(directory: Path) -> APIRouter:
    router = APIRouter(tags=['public reference'])

    @router.get('/api/documentation')
    def chapters() -> FileResponse:
        return FileResponse(directory / 'chapters.json', media_type='application/json')

    @router.get('/api/agent-anatomy')
    def anatomy() -> FileResponse:
        return FileResponse(directory / 'anatomy.json', media_type='application/json')

    @router.get('/api/documentation/source')
    def source(path: str = Query(max_length=240)) -> dict[str, str]:
        sources = json.loads((directory / 'sources.json').read_text(encoding='utf-8'))
        if path not in sources:
            raise HTTPException(404, 'Unknown documentation source')
        return {'path': path, 'text': sources[path]}

    return router
