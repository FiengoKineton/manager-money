from money_manager.web import auth
from money_manager.web.routes import backup, bonifico, contacts, integrity, net_explanation, notifications, onboarding, phone, phone_api, profile, search, security, settings_updates, settings_cache, settings_categories
from money_manager.web.routes.accounts import accounts, currencies, internal_transfers
from money_manager.web.routes.assets import investments
from money_manager.web.routes.core import analysis, dashboard, transactions, yearly_summary
from money_manager.web.routes.planning import expense_projects, financial_calendar, forecast, managed_recurring, mortgages, payables, pending
from money_manager.web.routes.support import debts, discount_balances, documents, parent_support, receivables, sparagnat


def register_routes(app):
    app.register_blueprint(auth.bp)
    app.register_blueprint(notifications.bp)
    app.register_blueprint(phone.bp)
    app.register_blueprint(phone_api.bp)
    app.register_blueprint(profile.bp)
    app.register_blueprint(integrity.bp)
    app.register_blueprint(settings_updates.bp)
    app.register_blueprint(settings_cache.bp)
    app.register_blueprint(settings_categories.bp)
    app.register_blueprint(security.bp)
    app.register_blueprint(backup.bp)
    app.register_blueprint(onboarding.bp)
    app.register_blueprint(search.bp)
    app.register_blueprint(contacts.bp)
    app.register_blueprint(bonifico.bp)

    app.register_blueprint(dashboard.bp)
    app.register_blueprint(transactions.bp)
    app.register_blueprint(analysis.bp)
    app.register_blueprint(yearly_summary.bp)
    app.register_blueprint(net_explanation.bp)

    app.register_blueprint(accounts.bp)
    app.register_blueprint(currencies.bp)
    app.register_blueprint(internal_transfers.bp)

    app.register_blueprint(pending.bp)
    app.register_blueprint(forecast.bp)
    app.register_blueprint(financial_calendar.bp)
    app.register_blueprint(payables.bp)
    app.register_blueprint(managed_recurring.bp)
    app.register_blueprint(mortgages.bp)
    app.register_blueprint(expense_projects.bp)

    app.register_blueprint(documents.bp)
    app.register_blueprint(discount_balances.bp)
    app.register_blueprint(sparagnat.bp)
    app.register_blueprint(debts.bp)
    app.register_blueprint(receivables.bp)
    app.register_blueprint(parent_support.bp)

    app.register_blueprint(investments.bp)
