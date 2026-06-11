from flask import Blueprint, redirect, render_template, request, url_for

from money_manager.services.expense_project_service import (
    add_planned_item_from_form,
    add_project_from_form,
    attach_transaction_from_form,
    delete_planned_item_from_form,
    delete_project_from_form,
    detach_movement_from_form,
    detail_context,
    overview_context,
    pay_planned_item_from_form,
    update_planned_item_from_form,
    update_project_from_form,
)

bp = Blueprint("expense_projects", __name__, url_prefix="/expense-projects")


@bp.route("", methods=["GET", "POST"])
def expense_projects_page():
    if request.method == "POST":
        action = request.form.get("action")
        if action == "add_project":
            project_id = add_project_from_form(request.form)
            if project_id:
                return redirect(url_for("expense_projects.expense_project_detail", project_id=project_id))
        elif action == "update_project":
            update_project_from_form(request.form)
        elif action == "delete_project":
            delete_project_from_form(request.form)
        return redirect(url_for("expense_projects.expense_projects_page"))

    return render_template("expense_projects.html", **overview_context())


@bp.route("/<int:project_id>", methods=["GET", "POST"])
def expense_project_detail(project_id: int):
    if request.method == "POST":
        action = request.form.get("action")
        if action == "update_project":
            update_project_from_form(request.form)
        elif action == "add_planned_item":
            add_planned_item_from_form(project_id, request.form)
        elif action == "update_planned_item":
            update_planned_item_from_form(request.form)
        elif action == "delete_planned_item":
            delete_planned_item_from_form(request.form)
        elif action == "pay_planned_item":
            pay_planned_item_from_form(project_id, request.form)
        elif action == "attach_transaction":
            attach_transaction_from_form(project_id, request.form)
        elif action == "detach_movement":
            detach_movement_from_form(request.form)
        elif action == "delete_project":
            delete_project_from_form(request.form)
            return redirect(url_for("expense_projects.expense_projects_page"))
        return redirect(url_for("expense_projects.expense_project_detail", project_id=project_id))

    context = detail_context(project_id)
    if context is None:
        return f"Expense project {project_id} not found", 404
    return render_template("expense_project_detail.html", **context)
