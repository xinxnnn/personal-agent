"""Existing user service plus isolated browser-driven runtime management."""
from app.user_app import app
from app.experience_runtime import router, shutdown
from app.experience_subagents import router as children_router
from app.deletion_review import user_router as deletion_router
from app.group_anp import router as anp_router
from contextlib import asynccontextmanager

app.include_router(router)
app.include_router(children_router)
app.include_router(deletion_router)
app.include_router(anp_router)
original_lifespan = app.router.lifespan_context

@asynccontextmanager
async def lifespan(application):
    async with original_lifespan(application):
        from app import runtime_watchdog, experience_runtime
        runtime_watchdog.start(experience_runtime)
        try:
            yield
        finally:
            shutdown()
            runtime_watchdog.join()

app.router.lifespan_context = lifespan
