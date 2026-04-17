from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from app.schemas.compile_schema import (
    CompileRequest, CompileResponse,
    FixErrorRequest, FixErrorResponse
)
from app.services.compile_service import compile_latex
from app.services.error_service import fix_errors

router = APIRouter(prefix="/compile", tags=["Compile"])

@router.post("/", response_model=CompileResponse)
def compile_document(request: CompileRequest):
    pdf_base64, error_log = compile_latex(request.content, request.compiler)
    if pdf_base64:
        return JSONResponse(
            content={"pdf_base64": pdf_base64, "error_log": None},
            headers={"Content-Type": "application/json; charset=utf-8"}
        )
    else:
        return JSONResponse(
            content={"pdf_base64": None, "error_log": error_log},
            headers={"Content-Type": "application/json; charset=utf-8"}
        )