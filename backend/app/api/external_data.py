"""
backend/app/api/external_data.py

Endpoints para conectar con fuentes de datos externas (APIs).
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List, Optional, Dict
from app.integrations.boe_connector import BoeConnector

router = APIRouter(prefix="/external", tags=["External Data"])

class BoeSearchRequest(BaseModel):
    query: Optional[str] = None
    date: Optional[str] = None # YYYYMMDD
    mode: str = "search" # "search" or "summary"

@router.post("/boe")
async def search_boe(request: BoeSearchRequest):
    """
    Busca legislación en el BOE o recupera el sumario del día.
    """
    connector = BoeConnector()
    
    if request.mode == "summary":
        # Sumario del día (o fecha específica)
        items = connector.get_summary(request.date)
        return {
            "source": "BOE",
            "mode": "summary",
            "date": request.date or "today",
            "count": len(items),
            "results": items
        }
    
    else:
        # Búsqueda por texto
        if not request.query:
            raise HTTPException(status_code=400, detail="Query required for search mode")
            
        results = connector.search_legislation(request.query)
        return {
            "source": "BOE",
            "mode": "search",
            "query": request.query,
            "count": len(results),
            "results": results
        }

class BoeGetLawRequest(BaseModel):
    law_name: Optional[str] = None  # "LOPD", "Constitución", etc.
    law_id: Optional[str] = None    # "BOE-A-2018-16673"
    include_text: bool = False      # Si incluir texto completo
    
@router.post("/boe/law")
async def get_boe_law(request: BoeGetLawRequest):
    """
    Obtiene información de una ley específica.
    Acepta nombre común (LOPD) o ID del BOE (BOE-A-2018-16673).
    """
    connector = BoeConnector()
    
    # Resolver ID si se pasó nombre
    law_id = request.law_id
    if not law_id and request.law_name:
        law_id = connector.resolve_law_id(request.law_name)
        if not law_id:
            raise HTTPException(status_code=404, detail=f"Ley '{request.law_name}' no encontrada en el mapeo")
    
    if not law_id:
        raise HTTPException(status_code=400, detail="Debe proporcionar law_name o law_id")
    
    if request.include_text:
        result = connector.get_law_text(law_id)
    else:
        result = connector.get_law_metadata(law_id)
    
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    
    return {"source": "BOE", "type": "law", **result}

@router.post("/boe/law/analysis")
async def get_boe_law_analysis(request: BoeGetLawRequest):
    """
    Obtiene análisis jurídico: qué leyes modifica y cuáles la modifican.
    """
    connector = BoeConnector()
    
    law_id = request.law_id
    if not law_id and request.law_name:
        law_id = connector.resolve_law_id(request.law_name)
        if not law_id:
            raise HTTPException(status_code=404, detail=f"Ley '{request.law_name}' no encontrada")
    
    if not law_id:
        raise HTTPException(status_code=400, detail="Debe proporcionar law_name o law_id")
    
    result = connector.get_law_analysis(law_id)
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    
    return {"source": "BOE", "type": "analysis", **result}

@router.get("/boe/subjects")
async def get_boe_subjects():
    """
    Obtiene la lista de materias/categorías disponibles en el BOE.
    """
    connector = BoeConnector()
    subjects = connector.get_subjects()
    return {
        "source": "BOE",
        "type": "subjects",
        "count": len(subjects),
        "subjects": subjects
    }
