import tempfile
from pathlib import Path
from copy import deepcopy
from asurada.capability_executor import CapabilityExecutor
from asurada.capabilities.history import ReviewScope
from asurada.task_runtime import TaskContext
from asurada.workflow_store import WorkflowStore
from regression_support import emit_result


def run():
    scope=ReviewScope('session',0,'Shanghai');checks={}
    with tempfile.TemporaryDirectory() as temp:
        store=WorkflowStore(Path(temp)/'review.db')
        rows=[]
        for name,times in [('A',[1000,1400,1200]),('B',[1500,1550,1600]),('missing',[1000,1200]),('different',[1000,1600,1800])]:
            for lap,duration in enumerate(times,1):
                rows.append({'session_uid':'session','epoch':0,'track':'Shanghai','segment':name,'lap':lap,'duration_ms':duration,'start_m':100,'end_m':200,'conditions':['rain' if name=='different' and lap==3 else 'dry'], 'evidence':{'source_sha256':'fixture','first_line':lap,'last_line':lap+1}})
        review={'source_sha256':'fixture','segments':rows}
        store.create('review',{'driver_id':'driver','steps':['analyze_segments']})
        store.run('review',(('analyze_segments',lambda request,results,context:deepcopy(review)),))
        def execute(**changes):
            args={'review_task_id':'review','lap_numbers':[1,2,3],'top_k':1,**changes}
            executor=CapabilityExecutor(context=TaskContext.start('query',1000),permissions=frozenset({'read_session_history'}),historical=True,review_store=store,driver_id='driver')
            return executor.execute('compare_review_segments',state=scope,arguments=args)['data']
        result=execute();first=result['comparisons'][0]
        checks['rank_and_top_k']=len(result['comparisons'])==1 and first['segment']=='A' and first['spread_ms']==400 and result['eligible_segment_count']==2
        checks['delta_and_evidence']=first['delta_ms']==200 and len(first['evidence'])==3 and first['evidence'][0]['review_task_id']=='review'
        checks['incomparable_excluded']=result['excluded']=={'missing':'missing_or_duplicate_lap','different':'conditions_or_distance_differ'}
        checks['no_data_explicit']=execute(lap_numbers=[8,9])['status']=='insufficient_data'
        for value in (0,21,True):
            try:execute(top_k=value);checks['invalid_top_'+str(value)]=False
            except ValueError:checks['invalid_top_'+str(value)]=True
    return {'passed':all(checks.values()),'checks':checks}


if __name__=='__main__':emit_result(run())
