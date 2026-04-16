from pydantic import BaseModel
from typing import Optional

class CompileRequest(BaseModel):
    content: str
    compiler: Optional[str] = "pdflatex"  # "pdflatex" или "xelatex"

class CompileResponse(BaseModel):
    pdf_base64: Optional[str] = None
    error_log: Optional[str] = None

class FixErrorRequest(BaseModel):
    content: str
    error_log: str

class FixErrorResponse(BaseModel):
    fixed_content: str