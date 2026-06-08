from money_manager.web.routes import accounts, analysis, dashboard, debts, documents, forecast, parent_support, pending, sparagnat, transactions


def register_routes(app):
    app.register_blueprint(dashboard.bp)
    app.register_blueprint(transactions.bp)
    app.register_blueprint(analysis.bp)
    app.register_blueprint(accounts.bp)
    app.register_blueprint(pending.bp)
    app.register_blueprint(forecast.bp)
    app.register_blueprint(documents.bp)
    app.register_blueprint(sparagnat.bp)
    app.register_blueprint(debts.bp)
    app.register_blueprint(parent_support.bp)
