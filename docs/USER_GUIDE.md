# 👤 Guía de Usuario - JARVIS

**Para**: Usuarios finales  
**Versión**: 3.9  
**Proyecto**: TFG - Universidad Rey Juan Carlos

---

## 📖 Índice

1. [Introducción](#introducción)
2. [Acceso al Sistema](#acceso-al-sistema)
3. [Tipos de Preguntas](#tipos-de-preguntas)
4. [Comandos Especiales](#comandos-especiales)
5. [Interpretación de Respuestas](#interpretación-de-respuestas)
6. [Mejores Prácticas](#mejores-prácticas)
7. [Ejemplos Prácticos](#ejemplos-prácticos)
8. [Consultas al BOE (Boletín Oficial del Estado)](#consultas-al-boe-boletín-oficial-del-estado) 🆕
9. [Indexar Webs Completas (Scraping Recursivo)](#indexar-webs-completas-scraping-recursivo) 🆕
10. [Preguntas Frecuentes](#preguntas-frecuentes)

---

## 🎯 Introducción

JARVIS es tu **asistente inteligente** para:

✅ Consultar documentos indexados (manuales, políticas, procedimientos)  
✅ Buscar información actualizada en internet  
✅ Analizar páginas web  
✅ Leer documentos escaneados e imágenes  
✅ Consultar el **Boletín Oficial del Estado (BOE)**  
✅ Mantener conversaciones con contexto  
✅ **Responder en tu idioma** (español, inglés, francés, alemán) 🆕

**No necesitas conocimientos técnicos para usarlo.**

> 🌍 **Detecta tu idioma automáticamente**: Si preguntas en inglés, responde en inglés. Si preguntas en español, responde en español.

---

## 🔐 Acceso al Sistema

### 1. Abrir el Sistema

En tu navegador, ve a:
```
http://localhost:3002
```

> ⚠️ **Nota**: Si trabajas remotamente, pregunta al administrador por la URL correcta.

### 2. Iniciar Sesión

**Primera vez**:
1. Click en "Sign up"
2. Completa el formulario
3. Espera aprobación del administrador (si aplica)

**Usuarios existentes**:
1. Ingresa email y contraseña
2. Click en "Sign in"

### 3. Seleccionar Modelo

**IMPORTANTE**: Siempre selecciona **"JARVIS"** como modelo.

Este es el único modelo que tendrás que usar. Es inteligente y decide automáticamente qué hacer.

---

## 🔐 2. Acceso y Permisos

El sistema puede configurarse para usar grupos de usuarios y decidir qué documentos puede ver cada persona.

### ¿Por qué no veo algunos documentos?
El sistema RAG respeta la privacidad de los departamentos:
*   **Usuarios de Calidad** → Ven documentos de `Calidad`.
*   **Miembros de DeptA** → Ven documentos de `DeptA`.
*   **Todos** → Ven documentos públicos/comunes.

Si crees que deberías tener acceso a un documento y no te aparece al usar `/listar`:
1.  Verifica con el administrador que tienes los permisos correctos.
2.  Si te acaban de añadir, espera unos minutos y vuelve a iniciar sesión.

---

## 💬 Tipos de Preguntas

El sistema puede responder diferentes tipos de consultas:

### 1. 📚 Consultas sobre Documentos Internos (RAG)

**Cuándo usar**: Quieres información de manuales, políticas, procedimientos.

**IMPORTANTE (🆕 v3.8)**: Ahora debes decir **explícitamente** "busca en tus documentos" para activar este modo:

**Ejemplos**:
```
Busca en tus documentos qué dice la política de calidad
```
```
Busca en los documentos el procedimiento de compras
```
```
Busca en tus páginas guardadas información sobre auditorías
```

**Frases clave que activan este modo**:
- `busca en tus documentos`
- `busca en los documentos`
- `busca en las páginas guardadas`

**Qué ocurre**:
- El sistema busca en los PDFs indexados
- Encuentra los fragmentos relevantes
- Genera una respuesta basada en esos documentos
- **Te muestra las fuentes** con número de página

**Respuesta esperada**:
```
✅ Según la Política de Calidad (documento MAP-003), 
los objetivos deben ser:
1. Medibles y cuantificables
2. Alineados con la visión de la empresa
3. Revisados anualmente

📚 Fuentes Citadas:
[1] 📄 Politica_Calidad.pdf (pág. 2) - relevancia: 0.87
```

---

### 2. 🌐 Búsquedas en Internet

**Cuándo usar**: Necesitas información actualizada que no está en documentos internos.

**IMPORTANTE (🆕 v3.8)**: Ahora debes decir **explícitamente** "busca en internet" para activar este modo.

**Ejemplos**:
```
Busca en internet el precio actual del Bitcoin
```
```
Busca en internet las últimas noticias sobre inteligencia artificial
```

**Frase clave OBLIGATORIA**: `busca en internet` o `buscar en internet`

**Qué ocurre**:
- El sistema busca en DuckDuckGo
- Sintetiza los resultados
- Te da una respuesta con fuentes web

**Respuesta esperada**:
```
✅ Según CoinMarketCap, el precio actual del Bitcoin 
es aproximadamente $45,000 USD...

🌐 Fuentes Web:
[1] Bitcoin Price (coinmarketcap.com)
[2] Latest Bitcoin News (coindesk.com)
```

---

### 3. 🔍 Análisis de Páginas Web (Navegación Inteligente)

**Cuándo usar**: Quieres que el sistema lea, analice o memorice una URL específica.

**Ejemplos**:
```
Analiza https://es.wikipedia.org/wiki/Inteligencia_artificial
```
```
https://www.ejemplo.com/articulo
```

**Qué ocurre (Nuevo en v3.7)**:
1.  **Detección Inteligente**: El sistema verifica si la URL ya existe en su memoria (RAG).
    *   Si **NO existe**: La descarga y analiza en tiempo real.
    *   Si **SÍ existe**: Te avisa y te ofrece usar la versión guardada (mucho más rápido).

**Comandos de Memoria Web**:

Una vez analizada una página, tienes dos niveles de memoria:

**A. Memoria Conversacional (Corto Plazo)**:
Por defecto, la web solo "vive" en este chat. Puedes preguntar sobre ella, pero si cierras el chat, se olvida.

**B. "Guarda esto" (Largo Plazo)**:
Si la información es valiosa, di:
```
Guarda esto
```
El sistema la indexará en la **Base de Conocimientos**.
*   **Beneficio**: Podrás abrir un chat nuevo mañana y preguntar sobre esa web sin tener que volver a dársela.
*   **Colaborativo**: Tus compañeros también podrán encontrar esa información si buscan sobre el tema.

**Respuesta esperada al guardar**:
```
✅ Contenido guardado exitosamente
📄 Título: [Título Web]
📅 Scrapeado: 2024-01-15
El contenido ahora está disponible para consultas RAG futuras.
```

---

### 4. 💬 Conversación General

**Cuándo usar**: Preguntas generales, saludos, charla casual.

**Ejemplos**:
```
Hola, ¿cómo estás?
```
```
Cuéntame un chiste
```
```
¿Qué es la inteligencia artificial?
```

**Qué ocurre**:
- Conversación normal
- No busca en documentos
- No muestra fuentes

**Respuesta esperada**:
```
💬 ¡Hola! Estoy bien, gracias por preguntar. 
¿En qué puedo ayudarte hoy?
```

---

## 🎮 Comandos Especiales

El sistema tiene comandos que empiezan con `/` para funciones específicas:

---

### `/listar` - Ver Documentos Disponibles

**Aliases**: `/docs`, `/documentos`

**Qué hace**: Muestra todos los PDFs indexados y disponibles para consulta.

**Ejemplo**:
```
/listar
```

**Filtrar por colección**:
Puedes listar documentos de una colección específica si tienes acceso a múltiples departamentos.

```
que docs tengo en DeptA
docs de documents_deptA
```

---

### `/webs` - Listar Páginas Web Guardadas (🆕 v3.8)

**Aliases**: `listar webs`, `que webs tienes`, `páginas guardadas`

**Qué hace**: Muestra **solo las páginas web** que has guardado (scrapeado e indexado).

**Ejemplos**:
```
listar webs
```
```
que webs tienes
```
```
páginas guardadas
```

**Respuesta**:
```
📋 Consultando documentos disponibles...
Total de documentos: 3

1. 🌐 Críticas de Superman (2025)
2. 🌐 Example Domain
3. 🌐 Noticias - BBC News Mundo
```

**Cuándo usar**: 
- Para ver qué páginas web tienes guardadas
- Antes de buscar en tus documentos para saber si tienes la info

-----

### `¿cómo va?` - Ver Estado de Ingestion (🆕 NUEVO)

**Aliases**: `status`, `estado de documentos`, `qué tal va la subida`

**Qué hace**: Muestra el estado de procesamiento de documentos recientes.

**Ejemplo**:
```
cómo va la subida?
```

**Respuesta**:
```
📊 Consultando estado de ingestión...

| Archivo | Estado | Mensaje | Actualizado |
|---|---|---|---|
| contrato.pdf | ✅ completed | Indexado correctamente | 10:30:00 |
| manual.pdf | ⚙️ processing | Procesando OCR... | 10:29:55 |

💡 Los archivos se eliminan automáticamente si los borras de la carpeta watch.
```

**Estados posibles**:
- ⏳ pending - Detectado, esperando procesamiento
- ⚙️ processing - Procesando (OCR, chunking, embeddings)
- ✅ completed - Indexado correctamente
- ❌ failed - Error en procesamiento

---

### Eliminación Automática de Documentos (🆕 NUEVO)

**¿Cómo funciona?**

Cuando un archivo **se elimina de la carpeta `data/watch`**, el sistema:
1. Detecta automáticamente la ausencia
2. Borra los embeddings de Qdrant
3. Actualiza el estado a "deleted"

**No necesitas hacer nada manualmente** - el proceso es automático.

**Tiempo de detección**: ~5 minutos (intervalo de escaneo)

---

## 📊 Interpretación de Respuestas

### Respuestas con Fuentes (RAG)

Cuando ves la sección **📚 Fuentes Citadas**, significa que la respuesta viene de documentos reales:

```
📚 Fuentes Citadas:

[1] 📄 Politica_Calidad.pdf (pág. 2) - relevancia: 0.87
[2] 📄 Manual_ISO.pdf (pág. 15) - relevancia: 0.79
```

**Cómo interpretarlo**:

| Elemento | Significado |
|----------|-------------|
| `[1]`, `[2]` | Número de referencia |
| `📄 Politica_Calidad.pdf` | Nombre del documento |
| `(pág. 2)` | Página específica donde está la info |
| `relevancia: 0.87` | Qué tan relevante es (0-1) |

**Score de relevancia**:
- **0.80 - 1.00**: Muy relevante (excelente)
- **0.60 - 0.79**: Moderadamente relevante (bueno)
- **< 0.60**: Poco relevante (revisar)

### Respuestas Sin Fuentes

Si NO aparece la sección de fuentes:
- Es conversación general
- O búsqueda en internet (fuentes web)
- O el sistema no encontró información relevante

---

## ✨ Mejores Prácticas

### 1. Sé Específico

❌ **Mal**:
```
Dime sobre calidad
```

✅ **Bien**:
```
¿Qué dice la política de calidad sobre los objetivos para 20 25?
```

**Por qué**: Las preguntas específicas obtienen respuestas más precisas.

---

### 2. Menciona el Documento (Si lo Conoces)

❌ **Aceptable**:
```
¿Cómo se hace una compra?
```

✅ **Mejor**:
```
Según el procedimiento de compras, ¿cómo se hace una compra?
```

**Por qué**: Ayuda al sistema a enfocarse en el documento correcto.

---

### 3. Usa Comandos para Explorar

✅ **Primero**:
```
/listar
```

✅ **Luego**:
```
¿Qué dice el Manual ISO sobre auditorías?
```

**Por qué**: Sabrás exactamente qué documentos consultar.

---

### 4. Verifica las Fuentes

Siempre mira la sección **📚 Fuentes Citadas** para:
- Confirmar que viene de un documento oficial
- Saber qué página consultar si quieres leer más
- Verificar la relevancia

---

### 5. Reformula Si No Entiendes

Si la respuesta no es clara:

✅ **Reformula**:
```
Explícamelo de forma más simple
```

O:

✅ **Pide ejemplos**:
```
Dame un ejemplo de cómo se aplicaría
```

---

## 🎯 Ejemplos Prácticos

### Escenario 1: Nuevo Empleado

**Objetivo**: Conocer políticas de la empresa

```
Usuario: /listar
Sistema: [Lista 5 documentos]

Usuario: ¿Cuántos días de vacaciones tengo?
Sistema: ✅ Según la Política de RRHH, tienes derecho a 20 días...
         📚 Fuentes: [1] Politica_RRHH.pdf (pág. 3)

Usuario: ¿Cómo solicito vacaciones?
Sistema: ✅ Para solicitar vacaciones debes...
```

---

### Escenario 2: Auditor

**Objetivo**: Revisar procedimientos de calidad

```
Usuario: ¿Qué dice el manual ISO sobre auditorías internas?
Sistema: ✅ El Manual ISO establece que las auditorías...
         📚 Fuentes: [1] Manual_ISO_9001.pdf (pág. 12-15)

Usuario: Resúmeme los pasos del procedimiento
Sistema: ✅ Los pasos son: 1. Planificación...
```

---

### Escenario 3: Investigación de Mercado

**Objetivo**: Información actualizada

```
Usuario: Buscar en internet las tendencias de IA en 2024
Sistema: 🌐 Según TechCrunch y Forbes, las principales...
         🌐 Fuentes Web: [1] TechCrunch, [2] Forbes

Usuario: Analiza https://www.mckinsey.com/articulo-ia
Sistema: 🔍 Procesando... [contenido indexado]

Usuario: ¿Qué dice McKinsey sobre ROI de IA?
Sistema: ✅ Según el artículo de McKinsey...
```

---

## ❓ Preguntas Frecuentes

### 1. ¿Puedo confiar en las respuestas?

**Sí, pero con matices**:

✅ **Si tiene fuentes citadas**: Alta confianza (viene de documentos reales)  
⚠️ **Si no tiene fuentes**: Conversación general (verificar)  

**Recomendación**: Siempre revisa la sección **📚 Fuentes**.

---

### 2. ¿Por qué a veces no encuentra información?

**Posibles razones**:

1. **El documento no está indexado**:
   - Usar `/listar` para verificar
   - Pedir al admin que lo suba

2. **La pregunta es muy ambigua**:
   - Ser más específico
   - Mencionar el documento

3. **La información no existe**:
   - El sistema responderá honestamente: "No encontré..."

---

### 3. ¿Puedo subir documentos?

**Depende de tu rol**:

❌ **Usuarios normales**: No (por seguridad)  
✅ **Administradores**: Sí, copiando a `data/watch/`

**Solicitud**: Contacta al administrador para indexar documentos.

---

### 4. ¿Funciona con documentos escaneados?

✅ **Sí**, el sistema tiene OCR (reconocimiento óptico de caracteres).

**Soporta**:
- PDFs escaneados
- Imágenes de documentos (JPG, PNG)
- Fotos de documentos

**Calidad**: Mejor con documentos escaneados en alta resolución.

---

### 5. ¿Cuánto tarda en responder?

**Depende del modo**:

| Modo | Tiempo Aprox. |
|------|---------------|
| Chat normal | 1-2 segundos |
| RAG (documentos) | 2-5 segundos |
| Web search | 3-8 segundos |
| Web scraping | 10-30 segundos |

**Factores**:
- Cantidad de documentos
- Complejidad de la pregunta
- Carga del servidor

---

### 6. ¿Mantiene historial de conversaciones?

✅ **Sí, con memoria mejorada** (🆕 v3.6).

El sistema ahora recuerda toda la conversación, permitiendo:

**Preguntas de seguimiento**:
```
Usuario: Busca en internet sobre energía solar
Sistema: [Resultados: 1. Paneles solares... 2. Energía renovable...]

Usuario: Cuéntame más sobre el punto 2
Sistema: ✅ Sobre energía renovable... [entiende que se refiere al punto 2 anterior]
```

**Referencias a respuestas anteriores**:
```  
Usuario: ¿Qué dice el manual ISO sobre auditorías?
Sistema: [Respuesta con fuentes]

Usuario: ¿Y qué pasa si no se cumple?
Sistema: ✅ Si no se cumplen las auditorías... [mantiene el contexto]
```

**Límites de memoria**:
- Últimos ~10-20 mensajes de la conversación
- La memoria se resetea al cerrar sesión
- Por privacidad, no se almacena permanentemente

---

### 7. ¿Puedo usar el sistema desde móvil?

✅ **Sí**, OpenWebUI es responsive.

**Navegadores recomendados**:
- Chrome/Edge (móvil)
- Safari (iOS)
- Firefox (Android)

---

### 8. ¿Qué hago si la respuesta es incorrecta?

**Pasos**:

1. **Verifica las fuentes**: ¿Dice realmente eso el documento?
2. **Reformula**: Pregunta de otra manera
3. **Reporta**: Contacta al administrador con:
   - Tu pregunta
   - La respuesta incorrecta
   - Qué debería decir

---

### 9. ¿Puedo hacer varias preguntas seguidas?

✅ **Sí**, el sistema mantiene contexto completo (🆕 Mejorado en v3.6).

**Ejemplo de seguimiento**:
```
Usuario: ¿Qué dice sobre vacaciones?
Sistema: [Respuesta sobre vacaciones]

Usuario: ¿Y sobre permisos?
Sistema: [Respuesta sobre permisos, en el mismo contexto]

Usuario: Resume ambos temas
Sistema: ✅ [Resumen de vacaciones Y permisos - recuerda toda la conversación]
```

**Funciona en todos los modos**:
- ✅ Chat normal
- ✅ Consultas RAG (documentos)
- ✅ Búsquedas en internet
- ✅ Análisis de archivos adjuntos

---

### 10. ¿Es seguro? ¿Quién ve mis preguntas?

**Seguridad**:

✅ **Datos locales**: Todo en el servidor de la empresa  
✅ **No sale información**: A diferencia de ChatGPT  
✅ **Logs solo admin**: Solo administradores ven logs  

**Privacidad**:
- Las conversaciones NO se almacenan permanentemente
- Solo se guardan temporalmente para contexto
- El admin puede ver logs de sistema (no conversaciones)

---

## 💡 Tips Avanzados

### Combinar Modos

Puedes combinar diferentes tipos de consultas:

```
1. /listar
   [Ver documentos disponibles]

2. Buscar en internet las mejores prácticas de ISO 9003
   [Información externa]

3. Compara eso con nuestro Manual ISO
   [RAG sobre documentos internos]
```

---

### Usar para Resúmenes

```
Resúmeme en 3 puntos principales la política de calidad
```

```
Dame los puntos clave del procedimiento de compras
```

---

---

### Comparaciones (🆕 MEJORADO)

Ahora puedes pedir explícitamente comparar dos documentos, incluso si son muy diferentes en nombre.

```
Usuario: Compara CODIGO ETICO GRUPO ADIT.pdf con Código de conducta ética en materia de relaciones comerciales tu empresa.pdf

Sistema: 📚 Consultando documentos internos...
Respuesta: Ambos documentos abordan la ética pero con enfoques distintos...
[Análisis comparativo detallado]
📚 Fuentes Citadas: [1] CODIGO ETICO..., [2] Código de conducta...
```

---

## 📜 Consultas al BOE (Boletín Oficial del Estado)

JARVIS puede consultar el **Boletín Oficial del Estado** en tiempo real para responder preguntas legales.

### Resumen del BOE de hoy

```
¿Qué dice el BOE de hoy?
Resumen del BOE
```

### Buscar legislación

```
Busca en el BOE normativa sobre protección de datos
Noticias del BOE sobre defensa
```

### Obtener texto de leyes específicas (🆕 v3.9)

Puedes pedir el texto completo o un artículo concreto de una ley:

```
Dame el artículo 5 de la LOPD
Texto de la Constitución
¿Qué dice la ley sobre el Estatuto de los Trabajadores?
```

**Leyes disponibles**: LOPD, Constitución, Código Civil, Código Penal, Estatuto de los Trabajadores, LPAC, LCSP, LGT, IRPF, LSSICE, RGPD...

### Análisis de referencias legales (🆕 v3.9)

Puedes preguntar qué leyes modifica o deroga una norma:

```
¿Qué modifica la Ley 39/2015?
Referencias del Real Decreto 28/2020
¿Qué leyes modifica el Código Civil?
```

**Respuesta esperada**:
```
🔍 Analizando referencias de: Ley 39/2015

### Leyes que modifica (3):
- Ley 30/1992 (Régimen Jurídico de las AAPP)
- Ley 11/2007 (Acceso electrónico ciudadanos)

### Leyes que la modifican (2):
- Real Decreto-ley 11/2020
```

### Palabras clave que activan BOE

- "ley", "real decreto", "BOE"
- "normativa", "legislación"
- "artículo X de la..."
- Siglas: LOPD, LISOS, LGT, etc.

---

## 🖼️ Análisis de Imágenes / OCR (🆕 v3.9)

JARVIS puede **ver y analizar imágenes** usando visión artificial (modelo Qwen2.5VL).

### Cómo usarlo

1. **Adjunta una imagen** usando el botón de clip 📎 en el chat
2. Escribe tu pregunta (o déjalo en blanco para descripción general)

**Ejemplos**:
```
[Adjunta imagen] ¿Qué texto aparece en esta imagen?
[Adjunta imagen] Describe lo que ves
[Adjunta imagen] Lee el contenido de este documento escaneado
```

**Qué puede hacer**:
- 📝 **Leer texto** en imágenes (OCR)
- 🖼️ **Describir** fotos e ilustraciones
- 📊 **Interpretar** gráficos y tablas
- 📄 **Extraer datos** de documentos escaneados

**Respuesta esperada**:
```
🖼️ Analizando imagen...

El documento muestra una factura con los siguientes datos:
- Empresa: Acme Corp
- Fecha: 15/01/2025
- Importe: 1.250,00 €
- Concepto: Servicio de consultoría
```

---

## 🕷️ Indexar Webs Completas (Scraping Recursivo)

Puedes pedirle a JARVIS que **indexe un sitio web completo** para poder consultarlo después.

### Cómo usarlo

**Sintaxis**:
```
Indexa https://docs.ejemplo.com con profundidad 2

Scrapea todo el sitio https://wiki.miempresa.com

Guarda todos los enlaces de https://faq.servicio.com
```

### Parámetros

| Parámetro | Descripción | Ejemplo |
|-----------|-------------|---------|
| **URL** | Dirección del sitio | https://docs.python.org |
| **Profundidad** | Cuántos niveles de enlaces seguir | 1, 2 o 3 |

### Qué esperar

1. **Confirmación**: JARVIS te confirma que ha iniciado el proceso
2. **Segundo plano**: El scraping se ejecuta sin bloquear el chat
3. **Disponible para consultas**: Una vez completado, puedes preguntar sobre el contenido

**Ejemplo**:
```
Usuario: Indexa https://docs.python.org/3/tutorial/ con profundidad 2

JARVIS: 🕷️ Scraping recursivo iniciado

• URL base: https://docs.python.org/3/tutorial/
• Profundidad: 2 niveles
• Máximo páginas: 50
• Job ID: a1b2c3d4

El proceso se ejecuta en segundo plano...
```

**Después de indexar**:
```
Usuario: ¿Cómo creo una lista en Python?

JARVIS: Según la documentación oficial de Python...
[Respuesta con contexto del sitio indexado]

📚 Fuentes:
[1] Python Tutorial - Data Structures (docs.python.org)
```

### Límites

- **Máxima profundidad**: 3 niveles
- **Máximas páginas**: 100 por job
- **Solo mismo dominio**: No sigue enlaces externos

---

## 📞 Soporte

**¿Problemas o dudas?**

1. **Primero**: Lee estas FAQs
2. **Luego**: Contacta al administrador del sistema
3. **Urgente**: (configurar canal de soporte)

---

**Siguiente**: Para información técnica, ver [TECHNICAL_ARCHITECTURE.md](TECHNICAL_ARCHITECTURE.md)
