import pandas as pd
from regression_support import emit_result
from asurada.training_partition import session_partitions


def run():
    frame=pd.DataFrame([{'session_uid':uid,'split':'test' if uid=='test' else 'train','frame':n} for uid in ['a','b','c','test'] for n in range(20)])
    train,val,test,manifest=session_partitions(frame)
    checks={'session_disjoint':not(set(train.session_uid)&set(val.session_uid) or set(train.session_uid)&set(test.session_uid) or set(val.session_uid)&set(test.session_uid)),
            'all_rows_assigned':len(train)+len(val)+len(test)==len(frame),
            'shuffle_stable':session_partitions(frame.sample(frac=1,random_state=42))[3]['sessions']==manifest['sessions']}
    leaked=frame.copy();leaked.loc[0,'split']='test'
    try: session_partitions(leaked); checks['leak_rejected']=False
    except ValueError as exc: checks['leak_rejected']='crosses' in str(exc)
    try: session_partitions(frame[frame.session_uid.isin(['a','test'])]);checks['no_row_fallback']=False
    except ValueError as exc:checks['no_row_fallback']='insufficient_sessions' in str(exc)
    return {'passed':all(checks.values()),'checks':checks,'analysis':manifest}

if __name__=='__main__':emit_result(run())
