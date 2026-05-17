from pydantic import BaseModel
from typing import Optional

class CompileRequest(BaseModel):
    content: str
    compiler: Optional[str] = "pdflatex"

class CompileResponse(BaseModel):
    pdf_base64: Optional[str] = None
    error_log: Optional[str] = None

class FixErrorRequest(BaseModel):
    code: str
    errors: str

class FixErrorResponse(BaseModel):
    code: str