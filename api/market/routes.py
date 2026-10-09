from fastapi import APIRouter, Request
from api.errors import AnalysisError
from api.models import normalize_symbol
from .models import Quote, History, Scanner

router = APIRouter(prefix='/api/v1/market', tags=['market'])


def ticker(value):
    try:
        return normalize_symbol(value)
    except ValueError as error:
        raise AnalysisError('invalid_ticker', 'Provide a BIST ticker such as ASELS or ASELS.IS.', 422) from error


@router.get('/quote/{symbol}', response_model=Quote)
async def quote(symbol: str, request: Request):
    return await request.app.state.market_service.quote(ticker(symbol))


@router.get('/history/{symbol}', response_model=History)
async def history(symbol: str, request: Request, interval: str = '1d', range: str = '3mo'):
    return await request.app.state.market_service.history(ticker(symbol), interval, range)


@router.get('/scanner', response_model=Scanner)
async def scanner(request: Request):
    return await request.app.state.market_service.scanner()
