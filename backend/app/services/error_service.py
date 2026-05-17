import re
from app.services.groq_service import fix_latex_errors

def parse_log(log: str) -> str:
    """Extract meaningful LaTeX errors from log text."""
    errors = []
    for line in log.splitlines():
        if "!" in line or "Error" in line:
            errors.append(line.strip())
    return "\n".join(errors) if errors else log

def fix_errors(code: str, errors: str) -> dict:
    """Fix LaTeX errors using Groq AI."""
    result = fix_latex_errors(code, errors)
    if result["success"]:
        return {"code": result["code"]}
    return {"code": code}