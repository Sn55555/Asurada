"""One live recognizer worker; cancelled non-cooperative calls keep their slot."""
from .task_runtime import BoundedTaskExecutor

_RECOGNIZER = BoundedTaskExecutor(1)


def listen_with_context(recognizer, context):
    def listen():
        if getattr(recognizer, 'supports_task_context', False):
            return recognizer.listen_once(context=context)
        return recognizer.listen_once()
    return context.wait(_RECOGNIZER.submit(context,listen))
