import subprocess
import tempfile
import base64
import os
import re
from typing import Optional

def adapt_latex_for_compiler(content: str, compiler: str) -> str:
    """
    Адаптирует LaTeX документ под конкретный компилятор.
    - Для XeLaTeX: убирает inputenc и fontenc, добавляет fontspec
    - Для pdfLaTeX: оставляет как есть (уже настроен правильно)
    """
    if compiler == "xelatex":
        # Убираем проблемные для XeLaTeX пакеты
        content = re.sub(r'\\usepackage\[utf8\]\{inputenc\}\n?', '', content)
        content = re.sub(r'\\usepackage\[T2A\]\{fontenc\}\n?', '', content)
        
        # Добавляем fontspec и настройки шрифтов, если их нет
        if '\\usepackage{fontspec}' not in content:
            # Добавляем после \documentclass
            content = re.sub(
                r'(\\documentclass.*?\n)',
                r'\1\\usepackage{fontspec}\n\\setmainfont{Times New Roman}\n',
                content
            )
    
    return content

def compile_latex(content: str, compiler: str = "pdflatex") -> tuple[Optional[str], Optional[str]]:
    """
    Compile LaTeX to PDF using pdflatex or xelatex.
    """
    if compiler not in ["pdflatex", "xelatex"]:
        compiler = "pdflatex"
    
    # Адаптируем документ под компилятор
    content = adapt_latex_for_compiler(content, compiler)
    
    # ДИАГНОСТИКА
    print(f"[DEBUG] Compiling with {compiler}")
    print(f"[DEBUG] Content length: {len(content)}")
    
    # Проверяем валидность UTF-8
    try:
        content.encode('utf-8')
        print("[DEBUG] Content is valid UTF-8")
    except UnicodeEncodeError as e:
        print(f"[DEBUG] Content has UTF-8 encoding issue: {e}")
        content = content.encode('utf-8', errors='ignore').decode('utf-8')
        print("[DEBUG] Content fixed by ignoring errors")
    
    with tempfile.TemporaryDirectory() as tmpdir:
        tex_path = os.path.join(tmpdir, "document.tex")
        pdf_path = os.path.join(tmpdir, "document.pdf")

        try:
            with open(tex_path, "w", encoding="utf-8") as f:
                f.write(content)
            print(f"[DEBUG] File written to {tex_path}")
        except Exception as e:
            print(f"[DEBUG] Error writing file: {e}")
            return None, f"Error writing file: {str(e)}"

        try:
            # Первый проход
            print(f"[DEBUG] Running {compiler} (first pass)...")
            result1 = subprocess.run(
                [compiler, "-interaction=nonstopmode", "document.tex"],
                cwd=tmpdir,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                encoding='utf-8',
                errors='replace',
                timeout=60
            )
            print(f"[DEBUG] First pass return code: {result1.returncode}")

            # Второй проход
            print(f"[DEBUG] Running {compiler} (second pass)...")
            result2 = subprocess.run(
                [compiler, "-interaction=nonstopmode", "document.tex"],
                cwd=tmpdir,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                encoding='utf-8',
                errors='replace',
                timeout=60
            )
            print(f"[DEBUG] Second pass return code: {result2.returncode}")

            full_log = (result1.stdout + result1.stderr + result2.stdout + result2.stderr)

            if os.path.exists(pdf_path):
                print(f"[DEBUG] PDF generated successfully")
                with open(pdf_path, "rb") as f:
                    pdf_bytes = f.read()
                pdf_base64 = base64.b64encode(pdf_bytes).decode("utf-8")
                return pdf_base64, None
            else:
                print(f"[DEBUG] PDF not found. Log length: {len(full_log)}")
                if full_log:
                    print(f"[DEBUG] Last 500 chars of log: {full_log[-500:]}")
                return None, full_log

        except FileNotFoundError:
            return None, f"Error: {compiler} command not found. Please ensure it is installed."
        except subprocess.TimeoutExpired:
            return None, "Error: Compilation timed out."
        except Exception as e:
            print(f"[DEBUG] Unexpected error: {str(e)}")
            return None, f"An unexpected error occurred: {str(e)}"