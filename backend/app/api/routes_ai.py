from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional, List
import json
from app.services.groq_service import (
    generate_document, generate_document_stream,
    generate_formula, generate_formula_stream,
    generate_part, generate_part_stream,
    explain_code, explain_code_stream,
    explain_latex, explain_latex_stream,
    math_solve_equation, math_solve_equation_stream,
    math_derive, math_derive_stream,
    math_physics_formula, math_physics_formula_stream,
    math_check_formula, math_check_formula_stream,
    generate_table, generate_table_stream,
    generate_diagram, generate_diagram_stream,
    generate_plot, generate_plot_stream,
    fetch_bibtex, fetch_bibtex_stream,
    format_references, format_references_stream,
    check_citation, check_citation_stream,
    add_alt_text, add_alt_text_stream,
    check_colors, check_colors_stream,
    check_template, check_template_stream,
    get_diff, get_diff_stream,
    summarize_changes, summarize_changes_stream,
    summarize_document, summarize_document_stream,
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
    operation: str = "derive"
    model: Optional[str] = DEFAULT_MODEL

class MathPhysicsRequest(BaseModel):
    description: str
    model: Optional[str] = DEFAULT_MODEL

class MathCheckRequest(BaseModel):
    formula: str
    model: Optional[str] = DEFAULT_MODEL

class GenerateTableRequest(BaseModel):
    csv: str
    has_header: bool = True
    use_booktabs: bool = True
    model: Optional[str] = DEFAULT_MODEL

class GenerateDiagramRequest(BaseModel):
    prompt: str
    model: Optional[str] = DEFAULT_MODEL

class GeneratePlotRequest(BaseModel):
    expression: str
    xlabel: str = "x"
    ylabel: str = "y"
    title: str = ""
    model: Optional[str] = DEFAULT_MODEL

class FetchBibtexRequest(BaseModel):
    identifier: str
    model: Optional[str] = DEFAULT_MODEL

class FormatReferencesRequest(BaseModel):
    references: str
    style: str = "ieee"
    model: Optional[str] = DEFAULT_MODEL

class CheckCitationRequest(BaseModel):
    citation: str
    model: Optional[str] = DEFAULT_MODEL

class AddAltTextRequest(BaseModel):
    figure_code: str
    model: Optional[str] = DEFAULT_MODEL

class CheckColorRequest(BaseModel):
    colors: List[str]
    palette_type: str = "all"
    model: Optional[str] = DEFAULT_MODEL

class CheckTemplateRequest(BaseModel):
    latex_code: str
    template: str = "ieee"
    model: Optional[str] = DEFAULT_MODEL

class DiffRequest(BaseModel):
    old_text: str
    new_text: str
    model: Optional[str] = DEFAULT_MODEL

class SummarizeChangesRequest(BaseModel):
    old_text: str
    new_text: str
    model: Optional[str] = DEFAULT_MODEL

class SummarizeDocumentRequest(BaseModel):
    latex_code: str
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

@router.post("/math/solve")
async def math_solve_endpoint(request: MathSolveRequest):
    async def stream():
        for chunk in math_solve_equation_stream(request.equation, request.model):
            yield chunk
    return StreamingResponse(stream(), media_type="text/event-stream")

@router.post("/math/derive")
async def math_derive_endpoint(request: MathDeriveRequest):
    async def stream():
        for chunk in math_derive_stream(request.expression, request.operation, request.model):
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

@router.post("/figures/table")
async def generate_table_endpoint(request: GenerateTableRequest):
    async def stream():
        for chunk in generate_table_stream(request.csv, request.has_header, request.use_booktabs, request.model):
            yield chunk
    return StreamingResponse(stream(), media_type="text/event-stream")

@router.post("/figures/diagram")
async def generate_diagram_endpoint(request: GenerateDiagramRequest):
    async def stream():
        for chunk in generate_diagram_stream(request.prompt, request.model):
            yield chunk
    return StreamingResponse(stream(), media_type="text/event-stream")

@router.post("/figures/plot")
async def generate_plot_endpoint(request: GeneratePlotRequest):
    async def stream():
        for chunk in generate_plot_stream(request.expression, request.xlabel, request.ylabel, request.title, request.model):
            yield chunk
    return StreamingResponse(stream(), media_type="text/event-stream")

@router.post("/references/fetch")
async def fetch_bibtex_endpoint(request: FetchBibtexRequest):
    async def stream():
        for chunk in fetch_bibtex_stream(request.identifier, request.model):
            yield chunk
    return StreamingResponse(stream(), media_type="text/event-stream")

@router.post("/references/format")
async def format_references_endpoint(request: FormatReferencesRequest):
    async def stream():
        for chunk in format_references_stream(request.references, request.style, request.model):
            yield chunk
    return StreamingResponse(stream(), media_type="text/event-stream")

@router.post("/references/check")
async def check_citation_endpoint(request: CheckCitationRequest):
    async def stream():
        for chunk in check_citation_stream(request.citation, request.model):
            yield chunk
    return StreamingResponse(stream(), media_type="text/event-stream")

@router.post("/accessibility/alt-text")
async def add_alt_text_endpoint(request: AddAltTextRequest):
    async def stream():
        for chunk in add_alt_text_stream(request.figure_code, request.model):
            yield chunk
    return StreamingResponse(stream(), media_type="text/event-stream")

@router.post("/accessibility/check-colors")
async def check_colors_endpoint(request: CheckColorRequest):
    async def stream():
        for chunk in check_colors_stream(request.colors, request.palette_type, request.model):
            yield chunk
    return StreamingResponse(stream(), media_type="text/event-stream")

@router.post("/accessibility/check-template")
async def check_template_endpoint(request: CheckTemplateRequest):
    async def stream():
        for chunk in check_template_stream(request.latex_code, request.template, request.model):
            yield chunk
    return StreamingResponse(stream(), media_type="text/event-stream")

@router.post("/collaboration/diff")
async def get_diff_endpoint(request: DiffRequest):
    async def stream():
        for chunk in get_diff_stream(request.old_text, request.new_text, request.model):
            yield chunk
    return StreamingResponse(stream(), media_type="text/event-stream")

@router.post("/collaboration/summarize")
async def summarize_changes_endpoint(request: SummarizeChangesRequest):
    async def stream():
        for chunk in summarize_changes_stream(request.old_text, request.new_text, request.model):
            yield chunk
    return StreamingResponse(stream(), media_type="text/event-stream")

@router.post("/collaboration/summarize-document")
async def summarize_document_endpoint(request: SummarizeDocumentRequest):
    async def stream():
        for chunk in summarize_document_stream(request.latex_code, request.model):
            yield chunk
    return StreamingResponse(stream(), media_type="text/event-stream")

@router.post("/fix-errors")
async def fix_errors(request: FixErrorsRequest):
    result = fix_latex_errors(request.code, request.errors, request.model)
    if not result["success"]:
        raise HTTPException(status_code=500, detail=result.get("error", "Fix failed"))
    return result
