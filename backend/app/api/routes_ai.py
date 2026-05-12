from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional
import json
from app.services.ollama_service import (
    generate_document, generate_document_stream,
    generate_formula, generate_formula_stream,
    generate_part, generate_part_stream,
    explain_code, explain_code_stream,
    explain_latex, explain_latex_stream,
    math_solve_equation, math_solve_equation_stream,
    math_derive, math_derive_stream,
    math_physics_formula, math_physics_formula_stream,
    math_check_formula, math_check_formula_stream,
    fix_latex_errors,
    get_available_models, DEFAULT_MODEL
)

router = APIRouter(prefix="/ai", tags=["AI Assistant"])

class GenerateDocumentRequest(BaseModel):
    description: str
    model: Optional[str] = DEFAULT_MODEL

class GenerateFormulaRequest(BaseModel):
    description: str
    model: Optional[str] = DEFAULT_MODEL

class GeneratePartRequest(BaseModel):
    description: str
    part_type: str = "section"
    model: Optional[str] = DEFAULT_MODEL

class ExplainCodeRequest(BaseModel):
    code: str
    model: Optional[str] = DEFAULT_MODEL

class ExplainLatexRequest(BaseModel):
    question: str
    model: Optional[str] = DEFAULT_MODEL

class MathSolveRequest(BaseModel):
    equation: str
    model: Optional[str] = DEFAULT_MODEL

class MathDeriveRequest(BaseModel):
    expression: str
    model: Optional[str] = DEFAULT_MODEL

class MathPhysicsRequest(BaseModel):
    description: str
    model: Optional[str] = DEFAULT_MODEL

class MathCheckRequest(BaseModel):
    formula: str
    model: Optional[str] = DEFAULT_MODEL

class FixErrorsRequest(BaseModel):
    code: str
    errors: str
    model: Optional[str] = DEFAULT_MODEL

@router.get("/models")
async def available_models():
    return {"models": get_available_models()}

@router.post("/generate/document")
async def generate_document_endpoint(request: GenerateDocumentRequest):
    async def stream():
        for chunk in generate_document_stream(request.description, request.model):
            yield chunk
    return StreamingResponse(stream(), media_type="text/event-stream")

@router.post("/generate/formula")
async def generate_formula_endpoint(request: GenerateFormulaRequest):
    async def stream():
        for chunk in generate_formula_stream(request.description, request.model):
            yield chunk
    return StreamingResponse(stream(), media_type="text/event-stream")

@router.post("/generate/part")
async def generate_part_endpoint(request: GeneratePartRequest):
    async def stream():
        for chunk in generate_part_stream(request.description, request.part_type, request.model):
            yield chunk
    return StreamingResponse(stream(), media_type="text/event-stream")

@router.post("/explain/code")
async def explain_code_endpoint(request: ExplainCodeRequest):
    async def stream():
        for chunk in explain_code_stream(request.code, request.model):
            yield chunk
    return StreamingResponse(stream(), media_type="text/event-stream")

@router.post("/explain/latex")
async def explain_latex_endpoint(request: ExplainLatexRequest):
    async def stream():
        for chunk in explain_latex_stream(request.question, request.model):
            yield chunk
    return StreamingResponse(stream(), media_type="text/event-stream")

# Math endpoints
@router.post("/math/solve")
async def math_solve_endpoint(request: MathSolveRequest):
    async def stream():
        for chunk in math_solve_equation_stream(request.equation, request.model):
            yield chunk
    return StreamingResponse(stream(), media_type="text/event-stream")

@router.post("/math/derive")
async def math_derive_endpoint(request: MathDeriveRequest):
    async def stream():
        for chunk in math_derive_stream(request.expression, request.model):
            yield chunk
    return StreamingResponse(stream(), media_type="text/event-stream")

@router.post("/math/physics")
async def math_physics_endpoint(request: MathPhysicsRequest):
    async def stream():
        for chunk in math_physics_formula_stream(request.description, request.model):
            yield chunk
    return StreamingResponse(stream(), media_type="text/event-stream")

@router.post("/math/check")
async def math_check_endpoint(request: MathCheckRequest):
    async def stream():
        for chunk in math_check_formula_stream(request.formula, request.model):
            yield chunk
    return StreamingResponse(stream(), media_type="text/event-stream")

@router.post("/fix-errors")
async def fix_errors(request: FixErrorsRequest):
    result = fix_latex_errors(request.code, request.errors, request.model)
    if not result["success"]:
        raise HTTPException(status_code=500, detail=result.get("error", "Fix failed"))
    return result