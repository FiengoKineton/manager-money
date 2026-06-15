from money_manager.web.routes import accounts, analysis, currencies, dashboard, debts, internal_transfers, documents, expense_projects, forecast, investments, parent_support, pending, payables, receivables, sparagnat, transactions
from money_manager.web import auth

def register_routes(app):
    app.register_blueprint(auth.bp)
    
    app.register_blueprint(dashboard.bp)
    app.register_blueprint(transactions.bp)
    app.register_blueprint(analysis.bp)
    app.register_blueprint(accounts.bp)
    app.register_blueprint(currencies.bp)
    app.register_blueprint(internal_transfers.bp)
    app.register_blueprint(pending.bp)
    app.register_blueprint(forecast.bp)
    app.register_blueprint(documents.bp)
    app.register_blueprint(sparagnat.bp)
    app.register_blueprint(debts.bp)
    app.register_blueprint(payables.bp)
    app.register_blueprint(expense_projects.bp)
    app.register_blueprint(receivables.bp)
    app.register_blueprint(investments.bp)
    app.register_blueprint(parent_support.bp)
