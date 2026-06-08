def register_context_processors(app):
    @app.context_processor
    def inject_endpoint_checker():
        def endpoint_exists(endpoint):
            return endpoint in app.view_functions

        return {"endpoint_exists": endpoint_exists}
