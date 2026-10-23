"""Authored fixture only, for local browser testing; never shipped in the API image."""

from test_pipeline import MemoryStore, config, execute_all
from test_serving import memory_reader

from openings_research.api import create_app
from openings_research.pipeline import Pipeline
from openings_research.serving import ResearchReader

store = MemoryStore()
execute_all(Pipeline(store, "fixture-preview", config()))
app = create_app(ResearchReader(memory_reader(store)))
