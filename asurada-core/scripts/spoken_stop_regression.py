"""Only complete exact wake-qualified stop commands trigger cancellation."""
from types import SimpleNamespace
from asurada.spoken_stop import SpokenStopRouter
from regression_support import emit_result


def run():
    calls=[];router=SpokenStopRouter(wake_phrases=('阿斯拉',),on_stop=lambda:calls.append('stop'))
    checks={}
    for phrase in ('阿斯拉停止','阿斯拉，取消。'):
        before=len(calls)
        checks[phrase]=router.accept(SimpleNamespace(status='recognized',transcript_text=phrase)) and len(calls)==before+1
    for phrase in ('停止','阿斯拉不要停止','请说阿斯拉停止','阿斯拉停止之后怎么样','阿斯拉'):
        before=len(calls)
        checks[phrase]=not router.accept(SimpleNamespace(status='recognized',transcript_text=phrase)) and len(calls)==before
    checks['partial_not_actionable']=not router.accept(SimpleNamespace(status='recognized_partial',transcript_text='阿斯拉停止'))
    try:
        SpokenStopRouter(wake_phrases=(),on_stop=lambda:None)
        checks['wake_required']=False
    except ValueError:checks['wake_required']=True
    return {'passed':all(checks.values()),'checks':checks}


if __name__=='__main__':emit_result(run())
