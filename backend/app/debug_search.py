import asyncio
import logging
import sys
import os

# Ensure we can import from the app
sys.path.append("/workspace")

from app.api.web_search import search_with_html_scraping, web_search, WebSearchResponse

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def test_search():
    query = "10 micromarcas de relojes de pulseras estadunidenses"
    print(f"\n--- Testing Search inside Container for: '{query}' ---")
    
    # Check DDGS library version/presence
    try:
        import duckduckgo_search
        print(f"duckduckgo_search version: {duckduckgo_search.__version__}")
    except ImportError:
        print("duckduckgo_search library NOT FOUND")
    
    try:
        # We call the function directly to see what it returns
        # We need to mock the Request/Response context if needed, but web_search is just a function
        # However, it expects a Query param. We can call the underlying logic if we extract it, 
        # or just call the function awaiting the result.
        
        # Let's verify what `search_with_html_scraping` does specifically first
        print("\n[Testing Scraping Fallback Direct Call]")
        scraping_results = await search_with_html_scraping(query)
        for r in scraping_results:
            print(f"  - [{r.source_type}] {r.title}: {r.link}")
            
    except Exception as e:
        print(f"Scraping Test Error: {e}")

    # Now test the full flow
    # Note: web_search is an endpoint, we can just call the logic block if we copy-pasted it, 
    # but better to test the components.
    
    print("\n[Testing DDGS Library Direct Call]")
    try:
        from duckduckgo_search import DDGS
        with DDGS() as ddgs:
            # Replicating the logic in web_search.py
            enhanced_query = f"{query} 2026" # Simulating the year addition
            print(f"Querying DDGS with: {enhanced_query} and region='es-es'")
            ddgs_results = list(ddgs.text(enhanced_query, max_results=5, region="es-es"))
            if not ddgs_results:
                print("DDGS returned NO results.")
            for r in ddgs_results:
                print(f"  - {r.get('title')}: {r.get('href')}")
    except Exception as e:
        print(f"DDGS Error: {e}")

if __name__ == "__main__":
    asyncio.run(test_search())
