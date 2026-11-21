"""Configured post-race analysis adapter for the existing voice coordinator."""
import os
from pathlib import Path
import shlex

from .analysis_agent import CommandAnalysisPlanner
from .analysis_planner import HttpAnalysisPlanner
from .capabilities.history import ReviewScope, completed_review
from .capability_executor import CapabilityExecutor
from .durable_analysis import run_durable_analysis
from .workflow_store import WorkflowStore


class ReviewVoiceService:
    def __init__(self, *, store, driver_id, review_task_id, planner_factory, planner_identity):
        self.store, self.driver_id, self.review_task_id = store, driver_id, review_task_id
        self.planner_factory, self.planner_identity = planner_factory, planner_identity

    @classmethod
    def from_env(cls):
        review_id = os.getenv('ASURADA_REVIEW_TASK_ID')
        if not review_id:
            return None
        path = Path(os.environ['ASURADA_REVIEW_STORE'])
        if not path.is_file():
            raise ValueError('review_store_must_exist')
        driver = os.environ['ASURADA_REVIEW_DRIVER_ID']
        command = os.getenv('ASURADA_REVIEW_PLANNER_COMMAND')
        if command:
            argv = shlex.split(command)
            factory = lambda: CommandAnalysisPlanner(argv)
            identity = {'command': argv}
        else:
            provider = os.environ['ASURADA_REVIEW_PROVIDER']
            configured = HttpAnalysisPlanner.from_env(provider)
            identity = {'provider': provider, 'model': configured.provider.model, 'base_url': configured.provider.base_url}
            factory = lambda: HttpAnalysisPlanner(configured.provider, style=configured.style)
        return cls(store=WorkflowStore(path), driver_id=driver, review_task_id=review_id,
                   planner_factory=factory, planner_identity=identity)

    def accepts(self, question):
        return question.strip().startswith(('复盘', '帮我复盘', '请复盘'))

    def analyze(self, *, question, request_id, context):
        review = completed_review(self.store, self.driver_id, self.review_task_id, context)
        indexes = [entry['result'] for entry in review['results'] if entry['step'] == 'index_official_laps']
        if len(indexes) != 1:
            raise ValueError('review_lap_index_unavailable')
        scopes = {(row['session_uid'], row['epoch'], row['track']) for row in indexes[0]}
        if len(scopes) != 1:
            raise ValueError('review_scope_ambiguous')
        scope = ReviewScope(*next(iter(scopes)))
        executor = CapabilityExecutor(context=context, permissions=frozenset({'read_session_history'}),
            historical=True, review_store=self.store, driver_id=self.driver_id)
        return run_durable_analysis(store=self.store, task_id='analysis:voice:' + request_id,
            planner=self.planner_factory(), planner_identity=self.planner_identity, executor=executor,
            question=question, scope=scope, review_task_id=self.review_task_id)
