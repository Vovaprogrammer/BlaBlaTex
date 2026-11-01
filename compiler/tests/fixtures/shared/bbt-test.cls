% Мини-класс для тестов компилятора. Лежит там же, куда в dev монтируется
% templates/_shared, и проверяет, что TeX находит классы через TEXINPUTS.
% Настоящий общий класс mtuci-report — задача T1.2.
\NeedsTeXFormat{LaTeX2e}
\ProvidesClass{bbt-test}[2026/11/01 BlaBlaTex compiler test class]
\LoadClass{article}
\RequirePackage{fontspec}
\setmainfont{Liberation Serif}
\setmonofont{Liberation Mono}
\RequirePackage[russian]{babel}
\RequirePackage{listings}
\lstset{basicstyle=\ttfamily, extendedchars=true}
\tracinglostchars=2
