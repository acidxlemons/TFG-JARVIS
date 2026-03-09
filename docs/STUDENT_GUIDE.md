# Guía académica del proyecto

## Propósito

Este documento sirve como apoyo para explicar el proyecto en un contexto académico con un tono de alumno que presenta una tesis o TFG. No está planteado como un guion agresivo de defensa, sino como una guía para exponer con claridad:

- cuál es el problema abordado,
- qué solución se propone,
- qué partes reutilizan herramientas existentes,
- qué partes constituyen desarrollo propio,
- y cuáles son las decisiones técnicas más importantes.

## Idea central del trabajo

La idea principal del proyecto no es entrenar un modelo fundacional desde cero. El núcleo del trabajo consiste en integrar modelos y herramientas ya existentes para construir un asistente corporativo capaz de consultar documentación cambiante de forma segura, local y trazable.

Explicado de forma simple:

1. La organización ya tiene documentos, normativa y fuentes distribuidas.
2. Un LLM generalista por sí solo no conoce esos documentos ni garantiza respuestas verificables.
3. Por eso se construye una arquitectura RAG que recupera información antes de generar la respuesta.
4. El valor del TFG está en diseñar esa arquitectura, justificarla e implementarla.

## Cómo presentar el proyecto

### 1. Problema

El problema no es la falta de información, sino su dispersión:

- documentos repartidos en varias fuentes;
- formatos heterogéneos;
- dificultad para encontrar contenido útil;
- riesgo de usar herramientas externas y caer en \textit{Shadow AI};
- necesidad de trazabilidad en las respuestas.

### 2. Solución

La solución propuesta es un asistente corporativo basado en RAG que:

- se ejecuta en infraestructura controlada;
- reutiliza modelos locales de lenguaje y embeddings;
- consulta documentación interna y fuentes externas concretas;
- responde apoyándose en documentos recuperados;
- y ofrece una interfaz conversacional sencilla para el usuario.

### 3. Contribución real del alumno

La contribución debe explicarse sin exagerar y sin restar mérito:

#### Herramientas reutilizadas

- OpenWebUI como interfaz conversacional.
- Ollama como motor de ejecución local de modelos.
- Qdrant como base de datos vectorial.
- PaddleOCR, Playwright, Trafilatura y otras bibliotecas especializadas.

#### Desarrollo propio

- arquitectura general del sistema;
- backend en Python y lógica RAG;
- pipeline JARVIS para enrutamiento de consultas;
- integración con SharePoint;
- integración funcional con el BOE;
- servidor MCP para normativa como línea de evolución;
- configuración de despliegue, monitorización y operación.

## Qué conviene dejar claro al explicar el BOE y MCP

Uno de los puntos donde más fácilmente puede generarse confusión es MCP. La forma correcta de explicarlo es esta:

- la funcionalidad del BOE está disponible para el usuario final dentro del sistema;
- en la interfaz principal esa funcionalidad se presta actualmente mediante API;
- además, se ha desarrollado un servidor MCP propio para este dominio;
- ese servidor MCP está validado y preparado para futuras integraciones, pero no es todavía el flujo principal en la interfaz web.

## Qué conviene decir sobre SharePoint

Otro punto importante es SharePoint. La formulación más consistente es:

- la idea del sistema es trabajar con documentos corporativos cambiantes en la nube y en otras fuentes;
- la integración principal implementada y validada en el TFG es SharePoint;
- por tanto, SharePoint actúa como caso real de uso y de prueba, no como límite conceptual absoluto del sistema.

## Estructura de la memoria

La memoria activa se organiza así:

1. Introducción
2. Fundamentos de la solución propuesta
3. Tecnologías utilizadas y criterio de elección
4. Sistemas relacionados y posicionamiento de la propuesta
5. Descripción funcional del sistema
6. Diseño e implementación
7. Metodología
8. Resultados y evaluación
9. Conclusiones y trabajo futuro

## Preguntas esperables y respuesta breve

### ¿Por qué no entrenar un modelo desde cero?

Porque no era necesario para resolver el problema real del proyecto. El reto no era crear otro modelo generalista, sino integrar modelos existentes con fuentes documentales corporativas de forma útil y segura.

### ¿Dónde está la aportación propia si muchas herramientas ya existían?

La aportación está en la arquitectura, la integración, la lógica de orquestación, el pipeline conversacional, el tratamiento documental y la adaptación del conjunto al caso de uso corporativo.

### ¿Por qué Python?

Porque actúa como lenguaje de integración natural entre servicios web, bibliotecas de IA, scraping, OCR, autenticación y procesamiento documental.

### ¿Por qué RAG y no solo chat con un LLM?

Porque el problema requiere respuestas apoyadas en documentación cambiante y trazable. Un LLM solo no garantiza eso.

### ¿Qué limitaciones tiene el trabajo?

- dependencia de hardware adecuado para ejecución local;
- validación práctica centrada principalmente en SharePoint;
- integración MCP todavía no embebida en la interfaz principal;
- evaluación más funcional que académicamente estandarizada.

## Recomendación de tono

El tono más sólido para presentar este proyecto es:

- claro y preciso;
- técnico, pero sin sobreactuar;
- reconociendo qué partes ya existían;
- explicando con honestidad qué se ha implementado y qué queda como evolución futura.

En otras palabras: presentar el trabajo como una tesis aplicada en la que el mérito no está en prometer más de lo que se ha hecho, sino en haber convertido tecnologías dispersas en un sistema coherente, funcional y justificable.
