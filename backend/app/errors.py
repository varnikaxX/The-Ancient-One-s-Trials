"""One error type -> the contract error shape {"error": {"code", "message"}}."""

STATUS = {
    "UNAUTHORIZED": 401,
    "FORBIDDEN": 403,
    "VALIDATION": 400,
    "NOT_FOUND": 404,
    "SLOT_TAKEN": 409,
    "STALE_DRAFT": 409,
    "DUPLICATE": 409,
}


class ApiError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = STATUS.get(code, 400)

    def body(self) -> dict:
        return {"error": {"code": self.code, "message": self.message}}
