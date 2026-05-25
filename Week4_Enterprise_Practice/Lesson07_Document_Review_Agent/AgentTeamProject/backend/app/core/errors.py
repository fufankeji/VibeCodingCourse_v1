import uuid

from fastapi import HTTPException


def _request_id(request_id: str = "") -> str:
    return request_id or f"req_{uuid.uuid4().hex[:12]}"


class APIError:
    @staticmethod
    def not_found(resource: str, request_id: str = "") -> HTTPException:
        return HTTPException(
            status_code=404,
            detail={
                "error_code": "NOT_FOUND",
                "message": f"{resource}不存在",
                "request_id": _request_id(request_id),
            },
        )

    @staticmethod
    def bad_request(message: str, request_id: str = "") -> HTTPException:
        return HTTPException(
            status_code=400,
            detail={
                "error_code": "BAD_REQUEST",
                "message": message,
                "request_id": _request_id(request_id),
            },
        )

    @staticmethod
    def conflict(message: str, request_id: str = "") -> HTTPException:
        return HTTPException(
            status_code=409,
            detail={
                "error_code": "CONFLICT",
                "message": message,
                "request_id": _request_id(request_id),
            },
        )

    @staticmethod
    def forbidden(message: str, request_id: str = "") -> HTTPException:
        return HTTPException(
            status_code=403,
            detail={
                "error_code": "FORBIDDEN",
                "message": message,
                "request_id": _request_id(request_id),
            },
        )

    @staticmethod
    def unprocessable(message: str, request_id: str = "") -> HTTPException:
        return HTTPException(
            status_code=422,
            detail={
                "error_code": "UNPROCESSABLE",
                "message": message,
                "request_id": _request_id(request_id),
            },
        )

    @staticmethod
    def internal(message: str = "内部服务错误", request_id: str = "") -> HTTPException:
        return HTTPException(
            status_code=500,
            detail={
                "error_code": "INTERNAL_ERROR",
                "message": message,
                "request_id": _request_id(request_id),
            },
        )

    @staticmethod
    def service_unavailable(message: str, request_id: str = "") -> HTTPException:
        return HTTPException(
            status_code=503,
            detail={
                "error_code": "SERVICE_UNAVAILABLE",
                "message": message,
                "request_id": _request_id(request_id),
            },
        )

    @staticmethod
    def session_state_invalid(current_state: str, required_state: str, request_id: str = "") -> HTTPException:
        return HTTPException(
            status_code=409,
            detail={
                "error_code": "SESSION_STATE_INVALID",
                "message": f"当前会话状态 '{current_state}' 不允许此操作，需要状态: '{required_state}'",
                "request_id": _request_id(request_id),
            },
        )

    @staticmethod
    def file_too_large(max_mb: int = 50, request_id: str = "") -> HTTPException:
        return HTTPException(
            status_code=413,
            detail={
                "error_code": "FILE_TOO_LARGE",
                "message": f"文件大小超过限制 ({max_mb}MB)",
                "request_id": _request_id(request_id),
            },
        )

    @staticmethod
    def unsupported_file_type(request_id: str = "") -> HTTPException:
        return HTTPException(
            status_code=415,
            detail={
                "error_code": "UNSUPPORTED_FILE_TYPE",
                "message": "不支持的文件类型，仅支持 PDF 和 DOCX",
                "request_id": _request_id(request_id),
            },
        )

    @staticmethod
    def encrypted_pdf(request_id: str = "") -> HTTPException:
        return HTTPException(
            status_code=422,
            detail={
                "error_code": "ENCRYPTED_PDF",
                "message": "PDF 文件已加密，无法解析",
                "request_id": _request_id(request_id),
            },
        )

    @staticmethod
    def corrupt_file(request_id: str = "") -> HTTPException:
        return HTTPException(
            status_code=422,
            detail={
                "error_code": "CORRUPT_FILE",
                "message": "文件损坏或结构不完整",
                "request_id": _request_id(request_id),
            },
        )

    @staticmethod
    def idempotent_duplicate(request_id: str = "") -> HTTPException:
        return HTTPException(
            status_code=200,
            detail={
                "error_code": "IDEMPOTENT_DUPLICATE",
                "message": "幂等键已存在，返回首次响应",
                "request_id": _request_id(request_id),
            },
        )
