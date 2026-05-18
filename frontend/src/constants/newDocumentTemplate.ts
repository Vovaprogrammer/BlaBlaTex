// src/constants/newDocumentTemplate.ts

export const NEW_DOCUMENT_TEMPLATE = `\\documentclass{article}
\\usepackage[utf8]{inputenc}
\\usepackage[T2A]{fontenc}
\\usepackage[russian]{babel}
\\usepackage{amsmath}

\\title{Новый документ}
\\author{Ваше имя}
\\date{\\today}

\\begin{document}
\\maketitle

\\section{Введение}
Начните писать ваш документ здесь...

\\end{document}`;


export const DEFAULT_APP_TEMPLATE = `\\documentclass{article}
\\usepackage[utf8]{inputenc}
\\usepackage[T2A]{fontenc}
\\usepackage[russian]{babel}
\\usepackage{amsmath}
\\usepackage{amsfonts}
\\usepackage{amssymb}

\\title{Название документа}
\\author{Ваше имя}
\\date{\\today}

\\begin{document}

\\maketitle

\\section{Введение}

Напишите введение здесь.

\\section{Основная часть}

Основной текст здесь. Используйте математические формулы: $E = mc^2$ внутри строки или отображаемые уравнения:

\\begin{equation}
    \\int_{-\\infty}^{\\infty} e^{-x^2} dx = \\sqrt{\\pi}
\\end{equation}

\\section{Заключение}

Завершите документ здесь.

\\end{document}`;