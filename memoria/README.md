# Memoria del TFG

Esta carpeta contiene la versión activa de la memoria en LaTeX.

## Estructura vigente

- `main.tex`: documento principal.
- `resumen.tex`, `portada.tex`, `dedicatoria.tex`, `agradecimientos.tex`: front matter.
- `capitulos/01_Introduccion.tex`
- `capitulos/02_EstadoDelArte.tex`
- `capitulos/03_MarcoTecnologico.tex`
- `capitulos/04_SistemasRelacionados.tex`
- `capitulos/05_DescripcionFuncional.tex`
- `capitulos/06_DisenoImplementacion.tex`
- `capitulos/07_Metodologia.tex`
- `capitulos/08_Resultados.tex`
- `capitulos/09_Conclusiones.tex`
- `bibliografia.bib`: referencias bibliográficas.

## Criterio de limpieza

Se han eliminado de esta carpeta:

- archivos auxiliares generados por LaTeX (`.aux`, `.toc`, `.out`, `.bbl`, `.bcf`, etc.),
- capítulos duplicados o heredados que ya no forman parte de la estructura activa.

El objetivo es que la memoria tenga una única estructura canónica y no existan capítulos alternativos que puedan confundir durante la redacción o la revisión.

## Compilación

Para generar el PDF hacen falta `pdflatex` y `biber` instalados en el sistema. Si no están disponibles, `compile.bat` abortará con un mensaje explícito.
