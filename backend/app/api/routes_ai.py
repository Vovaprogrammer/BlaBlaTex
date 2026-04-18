from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, List
from app.services.ollama_service import (
    generate_latex, explain_latex, fix_latex_errors,
    derive_equation, check_units, verify_equation,
    generate_table, generate_diagram, fetch_bibtex,
    add_alt_text, check_colors, check_template,
    get_diff, summarize_changes,
    get_available_models, DEFAULT_MODEL
)

router = APIRouter(prefix="/ai", tags=["AI Assistant"])

# ============================================
# Модели запросов
# ============================================

class GenerateRequest(BaseModel):
    description: str
    model: Optional[str] = DEFAULT_MODEL

class ExplainRequest(BaseModel):
    code: str
    model: Optional[str] = DEFAULT_MODEL

class FixErrorsRequest(BaseModel):
    code: str
    errors: str
    model: Optional[str] = DEFAULT_MODEL

class DeriveEquationRequest(BaseModel):
    expression: str
    model: Optional[str] = DEFAULT_MODEL

class CheckUnitsRequest(BaseModel):
    expression: str
    model: Optional[str] = DEFAULT_MODEL

class VerifyEquationRequest(BaseModel):
    lhs: str
    rhs: str
    model: Optional[str] = DEFAULT_MODEL

class GenerateTableRequest(BaseModel):
    csv: str
    has_header: bool = True
    use_booktabs: bool = True
    model: Optional[str] = DEFAULT_MODEL

class GenerateDiagramRequest(BaseModel):
    prompt: str
    strict_latex_only: bool = True
    model: Optional[str] = DEFAULT_MODEL

class FetchBibtexRequest(BaseModel):
    identifier: str
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

# ============================================
# Эндпоинты
# ============================================

@router.get("/models")
async def available_models():
    return {"models": get_available_models()}

@router.post("/generate")
async def generate(request: GenerateRequest):
    result = generate_latex(request.description, request.model)
    if not result["success"]:
        raise HTTPException(status_code=500, detail=result.get("error", "Generation failed"))
    return result

@router.post("/explain")
async def explain(request: ExplainRequest):
    result = explain_latex(request.code, request.model)
    if not result["success"]:
        raise HTTPException(status_code=500, detail=result.get("error", "Explanation failed"))
    return result

@router.post("/fix-errors")
async def fix_errors(request: FixErrorsRequest):
    result = fix_latex_errors(request.code, request.errors, request.model)
    if not result["success"]:
        raise HTTPException(status_code=500, detail=result.get("error", "Fix failed"))
    return result

@router.post("/derive-equation")
async def derive(request: DeriveEquationRequest):
    result = derive_equation(request.expression, request.model)
    if not result["success"]:
        raise HTTPException(status_code=500, detail=result.get("error", "Derivation failed"))
    return result

@router.post("/check-units")
async def units(request: CheckUnitsRequest):
    result = check_units(request.expression, request.model)
    if not result["success"]:
        raise HTTPException(status_code=500, detail=result.get("error", "Unit check failed"))
    return result

@router.post("/verify-equation")
async def verify(request: VerifyEquationRequest):
    result = verify_equation(request.lhs, request.rhs, request.model)
    if not result["success"]:
        raise HTTPException(status_code=500, detail=result.get("error", "Verification failed"))
    return result

@router.post("/generate-table")
async def table(request: GenerateTableRequest):
    result = generate_table(request.csv, request.has_header, request.use_booktabs, request.model)
    if not result["success"]:
        raise HTTPException(status_code=500, detail=result.get("error", "Table generation failed"))
    return result

@router.post("/generate-diagram")
async def diagram(request: GenerateDiagramRequest):
    result = generate_diagram(request.prompt, request.strict_latex_only, request.model)
    if not result["success"]:
        raise HTTPException(status_code=500, detail=result.get("error", "Diagram generation failed"))
    return result

@router.post("/fetch-bibtex")
async def bibtex(request: FetchBibtexRequest):
    result = fetch_bibtex(request.identifier, request.model)
    if not result["success"]:
        raise HTTPException(status_code=500, detail=result.get("error", "BibTeX fetch failed"))
    return result

@router.post("/add-alt-text")
async def alt_text(request: AddAltTextRequest):
    result = add_alt_text(request.figure_code, request.model)
    if not result["success"]:
        raise HTTPException(status_code=500, detail=result.get("error", "Alt text generation failed"))
    return result

@router.post("/check-color")
async def color(request: CheckColorRequest):
    result = check_colors(request.colors, request.palette_type, request.model)
    if not result["success"]:
        raise HTTPException(status_code=500, detail=result.get("error", "Color check failed"))
    return result

@router.post("/check-template")
async def template(request: CheckTemplateRequest):
    result = check_template(request.latex_code, request.template, request.model)
    if not result["success"]:
        raise HTTPException(status_code=500, detail=result.get("error", "Template check failed"))
    return result

@router.post("/get-diff")
async def diff(request: DiffRequest):
    result = get_diff(request.old_text, request.new_text, request.model)
    if not result["success"]:
        raise HTTPException(status_code=500, detail=result.get("error", "Diff generation failed"))
    return result

@router.post("/summarize-changes")
async def summarize(request: SummarizeChangesRequest):
    result = summarize_changes(request.old_text, request.new_text, request.model)
    if not result["success"]:
        raise HTTPException(status_code=500, detail=result.get("error", "Summarization failed"))
    return result