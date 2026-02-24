@echo off
echo Compilando memoria LaTeX...

if not exist "main.tex" (
    echo Error: No se encuentra main.tex en este directorio.
    exit /b 1
)

pdflatex -interaction=nonstopmode main.tex
biber main
pdflatex -interaction=nonstopmode main.tex
pdflatex -interaction=nonstopmode main.tex

echo ==============================================
echo Compilación finalizada.
echo Abre main.pdf para ver el resultado.
echo ==============================================
