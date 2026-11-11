from fastapi import HTTPException

from app.models import User


def error(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message})


def not_found() -> HTTPException:
    return error(404, "not_found", "Not found.")


def owned(record, user: User):
    if record is None or getattr(record, "user_id", None) != user.id:
        raise not_found()
    return record


def page(items: list, page_number: int, page_size: int) -> dict:
    page_number = max(page_number, 1)
    page_size = min(max(page_size, 1), 50)
    start = (page_number - 1) * page_size
    return {"items": items[start : start + page_size], "total": len(items), "page": page_number, "page_size": page_size}
