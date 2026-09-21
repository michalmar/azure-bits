from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException, Request
from python_multipart import MultipartParser
from python_multipart.multipart import parse_options_header

from .config import MAX_IMAGE_BYTES, MAX_MULTIPART_BYTES, MAX_PROMPT_LENGTH


ALLOWED_IMAGE_TYPES = {"image/png", "image/jpeg"}


@dataclass(slots=True)
class GenerateUpload:
    model: str
    prompt: str
    image: bytes | None = None
    image_filename: str | None = None
    image_content_type: str | None = None


class MultipartParseError(RuntimeError):
    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


class _GenerateMultipartCollector:
    def __init__(self) -> None:
        self._header_name = bytearray()
        self._header_value = bytearray()
        self._headers: dict[str, str] = {}
        self._part_name: str | None = None
        self._part_filename: str | None = None
        self._part_content_type: str | None = None
        self._text_buffer = bytearray()
        self._image_buffer = bytearray()
        self.model: str | None = None
        self.prompt: str | None = None
        self.image_filename: str | None = None
        self.image_content_type: str | None = None

    def on_part_begin(self) -> None:
        self._header_name.clear()
        self._header_value.clear()
        self._headers = {}
        self._part_name = None
        self._part_filename = None
        self._part_content_type = None
        self._text_buffer = bytearray()

    def on_header_begin(self) -> None:
        self._header_name.clear()
        self._header_value.clear()

    def on_header_field(self, data: bytes, start: int, end: int) -> None:
        self._header_name.extend(data[start:end])

    def on_header_value(self, data: bytes, start: int, end: int) -> None:
        self._header_value.extend(data[start:end])

    def on_header_end(self) -> None:
        name = self._header_name.decode("latin-1").lower()
        value = self._header_value.decode("latin-1")
        self._headers[name] = value
        self._header_name.clear()
        self._header_value.clear()

    def on_headers_finished(self) -> None:
        disposition = self._headers.get("content-disposition")
        if not disposition:
            raise MultipartParseError(400, "multipart part missing content-disposition")
        _, params = parse_options_header(disposition)
        raw_name = params.get(b"name")
        if not isinstance(raw_name, bytes) or not raw_name:
            raise MultipartParseError(400, "multipart field name missing")
        self._part_name = raw_name.decode("utf-8", "strict")

        raw_filename = params.get(b"filename")
        if isinstance(raw_filename, bytes) and raw_filename:
            self._part_filename = raw_filename.decode("utf-8", "strict")

        content_type = self._headers.get("content-type")
        self._part_content_type = content_type.split(";", 1)[0].strip().lower() if content_type else None
        if self._part_name == "image":
            if self._part_content_type not in ALLOWED_IMAGE_TYPES:
                raise MultipartParseError(415, "image must be PNG or JPEG")
            self.image_filename = self._part_filename or "upload.png"
            self.image_content_type = self._part_content_type

    def on_part_data(self, data: bytes, start: int, end: int) -> None:
        if self._part_name is None:
            return
        chunk = data[start:end]
        if self._part_name == "image":
            if len(self._image_buffer) + len(chunk) > MAX_IMAGE_BYTES:
                raise MultipartParseError(413, f"image must be {MAX_IMAGE_BYTES} bytes or smaller")
            self._image_buffer.extend(chunk)
            return
        self._text_buffer.extend(chunk)

    def on_part_end(self) -> None:
        if self._part_name == "model":
            self.model = self._text_buffer.decode("utf-8", "strict").strip()
        elif self._part_name == "prompt":
            self.prompt = self._text_buffer.decode("utf-8", "strict").strip()
        elif self._part_name == "image":
            if not self._image_buffer:
                raise MultipartParseError(422, "uploaded image is empty")
        self._part_name = None
        self._text_buffer = bytearray()

    def on_end(self) -> None:
        return

    def to_payload(self) -> GenerateUpload:
        if not self.model:
            raise MultipartParseError(422, "model is required")
        if not self.prompt:
            raise MultipartParseError(422, "prompt is required")
        if len(self.prompt) > MAX_PROMPT_LENGTH:
            raise MultipartParseError(422, f"prompt must be {MAX_PROMPT_LENGTH} characters or fewer")
        return GenerateUpload(
            model=self.model,
            prompt=self.prompt,
            image=bytes(self._image_buffer) if self._image_buffer else None,
            image_filename=self.image_filename,
            image_content_type=self.image_content_type,
        )

    @property
    def callbacks(self) -> dict[str, Any]:
        return {
            "on_part_begin": self.on_part_begin,
            "on_header_begin": self.on_header_begin,
            "on_header_field": self.on_header_field,
            "on_header_value": self.on_header_value,
            "on_header_end": self.on_header_end,
            "on_headers_finished": self.on_headers_finished,
            "on_part_data": self.on_part_data,
            "on_part_end": self.on_part_end,
            "on_end": self.on_end,
        }


async def parse_generate_upload(request: Request) -> GenerateUpload:
    content_type = request.headers.get("content-type")
    if not content_type or "multipart/form-data" not in content_type.lower():
        raise HTTPException(status_code=415, detail="content type must be multipart/form-data")

    content_length = request.headers.get("content-length")
    if not content_length:
        raise HTTPException(status_code=411, detail="content-length header is required")
    try:
        content_length_value = int(content_length)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid content-length header") from exc
    if content_length_value > MAX_MULTIPART_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"request body must be {MAX_MULTIPART_BYTES} bytes or smaller",
        )

    _, params = parse_options_header(content_type)
    boundary = params.get(b"boundary")
    if not isinstance(boundary, (bytes, bytearray)) or not boundary:
        raise HTTPException(status_code=400, detail="multipart boundary is missing")

    collector = _GenerateMultipartCollector()
    parser = MultipartParser(boundary, callbacks=collector.callbacks, max_size=MAX_MULTIPART_BYTES)
    total_seen = 0
    try:
        async for chunk in request.stream():
            if not chunk:
                continue
            total_seen += len(chunk)
            if total_seen > MAX_MULTIPART_BYTES:
                raise HTTPException(
                    status_code=413,
                    detail=f"request body must be {MAX_MULTIPART_BYTES} bytes or smaller",
                )
            parser.write(chunk)
        parser.finalize()
    except MultipartParseError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

    return collector.to_payload()
