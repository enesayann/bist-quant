"""Run independently with `python -m api.main`; never starts the trading bot."""
from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from api.errors import AnalysisError
from api.models import AnalyzeRequest, AnalysisResponse
from api.services.analysis_service import AnalysisService
from api.services.strategy_service import strategy_status
from api.market.routes import router as market_router
from api.market.service import MarketDataService


def create_app(service=None, market_service=None):
    service = service or AnalysisService()
    market_service = market_service or MarketDataService()

    @asynccontextmanager
    async def lifespan(app):
        yield
        service.close()
        market_service.close()

    app = FastAPI(title='BIST Quant Analysis API', version='1.0.0', lifespan=lifespan)
    app.state.analysis_service = service
    app.state.market_service = market_service
    app.include_router(market_router)
    app.add_middleware(CORSMiddleware, allow_origins=['http://127.0.0.1:5173', 'http://localhost:5173'],
                       allow_credentials=False, allow_methods=['GET', 'POST'], allow_headers=['Content-Type'])

    @app.exception_handler(AnalysisError)
    async def analysis_error(request: Request, error: AnalysisError):
        return JSONResponse(status_code=error.status, content={'error': {'code': error.code, 'message': error.message}})

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request: Request, error: RequestValidationError):
        return JSONResponse(status_code=422, content={'error': {'code': 'invalid_request', 'message': 'Provide a valid BIST ticker such as ASELS or ASELS.IS.'}})

    @app.exception_handler(Exception)
    async def unexpected_error(request: Request, error: Exception):
        logging.getLogger('api').error('Analysis API failure: %s', type(error).__name__)
        return JSONResponse(status_code=500, content={'error': {'code': 'analysis_failed', 'message': 'Analysis is temporarily unavailable. Try again later.'}})

    @app.get('/api/v1/health')
    async def health():
        return {'status': 'ok', 'service': 'analysis-api', 'version': '1.0.0', 'mode': 'research'}

    @app.get('/api/v1/strategies/status')
    async def strategies():
        return strategy_status()

    @app.post('/api/v1/analyze', response_model=AnalysisResponse)
    async def analyze(payload: AnalyzeRequest):
        return await service.analyze(payload.ticker)

    return app


app = create_app()

if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host='127.0.0.1', port=8000)
