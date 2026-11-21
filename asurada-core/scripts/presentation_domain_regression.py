"""Presentation consumes domain labels rather than rebuilding numeric policy."""
from asurada.assessment import assess_domain
from asurada.config import StrategyThresholds
from asurada.response_composer import compose_structured_query_response
from phase3_voice_regression import make_state
from regression_support import emit_result


def run():
    checks={}
    for name,wear,warn,box,expected in [('custom_manage',45,40,80,'manage'),
        ('custom_box',45,30,40,'box_now'),('custom_stable',75,80,90,'stable'),
        ('default_manage',60,58,72,'manage'),('default_box',72,58,72,'box_now')]:
        state=make_state();state.raw={};state.rivals=[];state.player.status_tags=[]
        state.player.gap_ahead_s=state.player.gap_behind_s=5;state.player.tyre.wear_pct=wear
        labels=assess_domain(state,StrategyThresholds(tyre_wear_warn=warn,tyre_wear_box=box)).labels
        overall,_=compose_structured_query_response(state=state,query_kind='overall_situation')
        outlook,_=compose_structured_query_response(state=state,query_kind='tyre_wear_outlook')
        checks[name+'_core']=labels.tyre_state==expected
        checks[name+'_risk']=('最大风险是轮胎磨损偏高' in overall)==(expected!='stable')
        checks[name+'_focus']=('下一步优先保护轮胎' in overall)==(expected!='stable')
        phrase={'manage':'已经触发保胎阈值','box_now':'已经触发进站磨损阈值','stable':'尚未触发保胎阈值'}[expected]
        checks[name+'_outlook']=phrase in outlook
        checks[name+'_no_unmeasured_lap_forecast']='无法准确预测未来可跑圈数' in outlook
    state.player.tyre.wear_pct=10;state.player.gap_behind_s=1.1
    for name,limit,urgent in [('open',1.5,True),('closed',.5,False)]:
        assess_domain(state,StrategyThresholds(rival_gap_defend=limit))
        text,_=compose_structured_query_response(state=state,query_kind='overall_situation')
        checks[name+'_defence_posture']=('当前整体更偏向防守' in text)==urgent
        checks[name+'_defence_risk']=('最大风险是后车逼近' in text)==urgent
    return {'passed':all(checks.values()),'checks':checks}


if __name__=='__main__':emit_result(run())
