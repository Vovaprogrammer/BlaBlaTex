\# BlaBLaTex



AI-powered LaTeX editor with smart assistance for scientific writing.



\## 🚀 Features



\- \*\*LaTeX Editor\*\* with syntax highlighting

\- \*\*Real-time PDF preview\*\*

\- \*\*AI Assistant\*\* for generating and explaining LaTeX code

\- \*\*Math intelligence\*\* (equation verification, derivations)

\- \*\*Reference management\*\* (BibTeX from DOI/arXiv)

\- \*\*Collaboration tools\*\* (diff, merge, comments)



\## 🛠️ Tech Stack



\- \*\*Frontend\*\*: React, TypeScript, TailwindCSS

\- \*\*Backend\*\*: Python, FastAPI

\- \*\*AI\*\*: Google Gemini API, SymPy



\## 📦 Installation



\### Prerequisites

\- Python 3.10+

\- Node.js 18+



\### Quick Start



```bash

\# Clone the repository

git clone https://github.com/Vovaprogrammer/BlaBLaTex.git

cd BlaBLaTex



\# Backend setup

cd backend

python -m venv venv

source venv/bin/activate  # or venv\\Scripts\\activate on Windows

pip install -r requirements.txt

uvicorn app.main:app --reload



\# Frontend setup (in new terminal)

cd frontend

npm install

npm run dev

