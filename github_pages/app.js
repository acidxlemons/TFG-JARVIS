document.addEventListener('DOMContentLoaded', () => {
    // Typewriter effect in the terminal
    const terminalBody = document.getElementById('typewriter');

    const codeLines = [
        "<span style='color: #a8b2d1;'>INFO:</span> Initializing FastAPI Backend v3.9...",
        "<span style='color: #a8b2d1;'>INFO:</span> Connecting to PostgreSQL Vector (pgvector)... <span style='color: #27c93f;'>OK</span>",
        "<span style='color: #a8b2d1;'>INFO:</span> Connecting to Redis Cache... <span style='color: #27c93f;'>OK</span>",
        "<span style='color: #a8b2d1;'>INFO:</span> Starting LiteLLM Model Proxy... <span style='color: #27c93f;'>OK</span>",
        "<span style='color: #a8b2d1;'>INFO:</span> Model <span style='color: #ffbd2e;'>llama3.1:8b-instruct-q8_0</span> loaded in Ollama",
        "<span style='color: #a8b2d1;'>INFO:</span> SharePoint Webhook listener active on port 8003",
        "<br>",
        "<span style='color: #a8b2d1;'>[POST]</span> /chat { message: 'Busca la normativa de seguridad...', mode: 'rag' }",
        "<span style='color: #64ffda;'>--> Extrayendo entidades...</span>",
        "<span style='color: #64ffda;'>--> Buscando chunks en Qdrant (top_k=5)...</span>",
        "<span style='color: #64ffda;'>--> Generando respuesta contextual...</span>",
        "<br>",
        "<span style='color: #27c93f;'>200 OK</span> - Response ready in 2.3s"
    ];

    let currentLine = 0;

    function typeLine() {
        if (currentLine < codeLines.length) {
            const lineHtml = codeLines[currentLine];

            // Si es un <br>, saltamos rapido
            if (lineHtml === '<br>') {
                terminalBody.innerHTML += '<br>';
                currentLine++;
                setTimeout(typeLine, 100);
            } else {
                const lineDiv = document.createElement('div');
                lineDiv.innerHTML = lineHtml;
                terminalBody.appendChild(lineDiv);

                // Scroll to bottom
                terminalBody.scrollTop = terminalBody.scrollHeight;

                currentLine++;

                // Random delay between lines for realism (200ms to 800ms)
                const delay = Math.random() * 600 + 200;
                setTimeout(typeLine, delay);
            }
        }
    }

    // Delay start
    setTimeout(typeLine, 1000);
});
