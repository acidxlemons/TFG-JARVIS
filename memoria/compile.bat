@echo off
setlocal

echo Compilando memoria LaTeX...

if not exist "main.tex" (
    echo Error: No se encuentra main.tex en este directorio.
    exit /b 1
)

where pdflatex >nul 2>nul
if errorlevel 1 (
    echo Error: pdflatex no esta instalado o no esta en PATH.
    exit /b 1
)

where biber >nul 2>nul
if errorlevel 1 (
    echo Error: biber no esta instalado o no esta en PATH.
    exit /b 1
)

pdflatex -interaction=nonstopmode main.tex
if errorlevel 1 exit /b 1

biber main
if errorlevel 1 exit /b 1

pdflatex -interaction=nonstopmode main.tex
if errorlevel 1 exit /b 1

pdflatex -interaction=nonstopmode main.tex
if errorlevel 1 exit /b 1

echo ==============================================
echo Compilacion finalizada correctamente.
echo Abre main.pdf para ver el resultado.
echo ==============================================
