def strategy_status():
    return {'strategies': [
        {'name': 'Daily Strategy v1', 'status': 'available', 'scope': 'read_only_completed_daily_technical'},
        {'name': 'Intraday Data Contract', 'status': 'ready'},
        {'name': 'Intraday Strategy v2', 'status': 'not_implemented'},
    ]}
