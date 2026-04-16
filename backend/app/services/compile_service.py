import subprocess
import tempfile
import base64
import os
from typing import Optional

def compile_latex(content: str, compiler: str = "pdflatex") -> tuple[Optional[str], Optional[str]]:
    """
    Compile LaTeX to PDF using pdflatex or xelatex.

    Args:
        content (str): LaTeX document source code.
        compiler (str): Compiler to use ("pdflatex" or "xelatex").

    Returns:
        tuple[str | None, str | None]: (pdf_base64, error_log)
    """
    # Проверка валидности компилятора
    if compiler not in ["pdflatex", "xelatex"]:
        compiler = "pdflatex"
    
    with tempfile.TemporaryDirectory() as tmpdir:
        tex_path = os.path.join(tmpdir, "document.tex")
        pdf_path = os.path.join(tmpdir, "document.pdf")

        # Запись файла в UTF-8
        with open(tex_path, "w", encoding="utf-8") as f:
            f.write(content)

        try:
            # Первый проход
            result1 = subprocess.run(
                [compiler, "-interaction=nonstopmode", "document.tex"],
                cwd=tmpdir,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=60
            )

            # Второй проход (для ссылок)
            result2 = subprocess.run(
                [compiler, "-interaction=nonstopmode", "document.tex"],
                cwd=tmpdir,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=60
            )

            full_log = (result1.stdout + result1.stderr + result2.stdout + result2.stderr)

            if os.path.exists(pdf_path):
                with open(pdf_path, "rb") as f:
                    pdf_bytes = f.read()
                pdf_base64 = base64.b64encode(pdf_bytes).decode("utf-8")
                return pdf_base64, None
            else:
                return None, full_log

        except FileNotFoundError:
            return None, f"Error: {compiler} command not found. Please ensure it is installed."
        except subprocess.TimeoutExpired:
            return None, "Error: Compilation timed out."
        except Exception as e:
            return None, f"An unexpected error occurred: {str(e)}"