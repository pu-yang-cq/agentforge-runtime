from agentforge.api.app import create_app
from agentforge.config import Settings
from agentforge.infrastructure.db.runtime_store import PostgresRuntimeStore
from agentforge.infrastructure.db.session import create_engine, create_session_factory

settings = Settings()
engine = create_engine(settings.database_url)
session_factory = create_session_factory(engine)
store = PostgresRuntimeStore(session_factory)
app = create_app(store)
