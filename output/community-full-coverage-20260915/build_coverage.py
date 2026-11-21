"""Build the 27-layout inventory from actual audits, with explicit unknowns."""
import csv
import json
from pathlib import Path
import shutil
import sys

ROOT=Path(__file__).resolve().parent
REPO=ROOT.parents[1]
sys.path.insert(0,str(REPO/'asurada-core/scripts'))
from f1_25_track_catalog import F1_25_TRACK_CATALOG

ZH={0:'澳大利亚·墨尔本',2:'中国·上海',3:'巴林',4:'西班牙·加泰罗尼亚',5:'摩纳哥',6:'加拿大·蒙特利尔',7:'英国·银石',9:'匈牙利',10:'比利时·斯帕',11:'意大利·蒙扎',12:'新加坡',13:'日本·铃鹿',14:'阿布扎比',15:'美国·奥斯汀',16:'巴西',17:'奥地利',19:'墨西哥',20:'阿塞拜疆·巴库',26:'荷兰·赞德沃特',27:'伊莫拉',29:'沙特·吉达',30:'迈阿密',31:'拉斯维加斯',32:'卡塔尔·卢赛尔',39:'银石反向',40:'奥地利反向',41:'赞德沃特反向'}

def main():
    remote=[r for r in json.loads((ROOT/'remote-files.json').read_text()) if r['name'].startswith('f1_25_')]
    receipts={p.name[:-8]:json.loads(p.read_text()) for p in (ROOT/'raw').glob('*.gz.json')}
    audits=[json.loads(p.read_text()) for p in (ROOT/'audits').glob('*.json')]
    download_status=json.loads((ROOT/'download-status.json').read_text())
    failures=[r for r in download_status if r.get('status')=='failed']
    rows=[]
    for track in F1_25_TRACK_CATALOG:
        matches=[]
        for audit in audits:
            for uid,s in audit.get('sessions',{}).items():
                if track.track_id in s['track_ids']:
                    matches.append({'file':audit['file'],'session_uid':uid,'packets':sum(s['packet_counts'].values()),
                        'container_integrity':audit['container_integrity'],'all_required_packet_types_present':s['all_required_packet_types_present'],
                        'missing_packet_types':s['missing_required_packet_types'],'session_types':s['session_types'],
                        'player_laps':s['fields'].get('current_lap_num'),'spectating':s['spectating'],
                        'time_reversals':dict(s['time_reversals_by_packet']),
                        'player_field_names':sorted(s['fields'])})
        own=track.track_id in {2,13}
        status='已有自录；完整性待统一验收' if own else ('已下载原始录制；完整性未通过验收' if matches else '尚无经包头确认的本地原始录制')
        rows.append({'track_id':track.track_id,'track':track.track_name,'name_zh':ZH[track.track_id],
                     'profile_slug':track.profile_slug,'self_recorded_retained':own,'downloaded_sessions':matches,
                     'complete_verified':False,'status':status})
    result={'scope':'F1 25 base 2025, 24 normal circuits + 3 reverse layouts; F1 26/2026 DLC and real-world FastF1 excluded',
            'required_layouts':27,'remote_recordings':len(remote),'downloaded_files':len(receipts),
            'downloaded_raw_bytes':sum(r['raw_bytes'] for r in receipts.values()),
            'stored_bytes':sum(r['stored_bytes'] for r in receipts.values()),
            'layouts_with_downloaded_recording':sum(bool(r['downloaded_sessions']) for r in rows),
            'layouts_with_any_raw_source_including_self':sum(bool(r['downloaded_sessions']) or r['self_recorded_retained'] for r in rows),
            'complete_layouts_verified':0,'disk_free_bytes':shutil.disk_usage(ROOT).free,
            'failed_downloads':failures,
            'layouts':rows,'pending_downloads':[r for r in remote if r['name'] not in receipts]}
    (ROOT/'coverage.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    with (ROOT/'coverage.csv').open('w',newline='',encoding='utf-8-sig') as f:
        writer=csv.writer(f);writer.writerow(['track_id','赛道','自录保留','社区录制文件数','完整验收','状态'])
        for r in rows:writer.writerow([r['track_id'],r['name_zh'],r['self_recorded_retained'],len({s['file'] for s in r['downloaded_sessions']}),False,r['status']])
    lines=['# F1 25 全赛道原始遥测覆盖清单','',
        '## 目标与完整口径','',
        '目标为 24 个正常赛道及 3 个反向布局。沿用当前 F1 25 / UDP 2025，不将 2026 DLC、真实 F1 转播遥测、其他游戏或合成数据混入。',
        '完整验收至少需要：每布局有从比赛开始到结束的有效比赛录制；Session、LapData、Motion、MotionEx、CarTelemetry、CarStatus、CarDamage、Participants、CarSetups、Event、SessionHistory、TyreSets、FinalClassification 等相关包可用；主车物理字段有效且时间可对齐。比赛中断、倒带、旁观视角、受限对手字段和缺包需单独标记。',
        '这是一套数据采集验收口径，不表示单场比赛足以训练可靠模型。干湿天气、胎种、驾驶者、车辆设置及真实攻防标签覆盖仍需扩充。',
        '当前 audit 只检查文件记录数、所有包头及选定主车字段；尚未完成逐帧联合完整性、对手隐私/字段有效性、整场比赛边界和训练标签验收。因此不把“包类型出现过”当成“完整可训练”。','',
        '## 当前结果','',
        f"- 已识别远端 F1 25 录制：{len(remote)} 个；已下载并校验：{len(receipts)} 个。",
        f"- 原文件字节合计：{result['downloaded_raw_bytes']:,}；无损 gzip 存储：{result['stored_bytes']:,} 字节。",
        f"- 已下载社区录制实际涉及：{result['layouts_with_downloaded_recording']} / 27 布局。",
        f"- 连同上海、铃鹿自录，已有某种原始录制：{result['layouts_with_any_raw_source_including_self']} / 27 布局。",
        '- 全部 27 布局完整覆盖：未达成。完整可训练验收不因下载成功而自动通过。','',
        f"- 因磁盘空间下限停止的文件：{len(failures)} 个；生成报告时可用空间约 {result['disk_free_bytes']/1024**3:.2f} GiB。",
        '- SHA-256 检查确认本地压缩前后字节一致；提供方未公布校验和，因此不是与提供方校验和的独立比对。',
        '- 两个吉达玩家练习录制的容器头声明记录数与实际记录数不符，已标记 source_header_count_mismatch；不能作为完整性合格数据。','',
        '## 逐赛道清单','', '| ID | 赛道 | 社区原始文件数 | 当前状态 |','|---:|---|---:|---|']
    for r in rows:
        lines.append(f"| {r['track_id']} | {r['name_zh']} | {len({s['file'] for s in r['downloaded_sessions']})} | {r['status']} |")
    lines+=['','## 缺口与补采','',
        '目前尚无经包头确认的本地原始录制（包括自录）的布局：'+ '、'.join(r['name_zh'] for r in rows if not r['downloaded_sessions'] and not r['self_recorded_retained'])+'。',
        '没有原始录制的布局，需要找到其他公开源或由驾驶者提供 F1 25 完整比赛录制。当前搜索未确认一套可直接下载、覆盖全部布局且满足上述口径的公开数据集。',
        '补采优先每布局一场正常完赛的比赛，保留全部游戏 UDP 包、接收时间、游戏时间、session UID 和帧号；尽量包含进站与连续轮胎使用段。再扩充雨天、不同轮胎/燃油及攻防场景。',
        '大厅、Time Trial、短片段、退赛样本可以补充特定场景，但不能填充完整比赛缺口。仅依据文件名推断赛道的远端文件不计入已覆盖。','',
        '## 下载与清理','',
        '已按用户指令删除 manifest 列出的 81 个 F1Laps 社区原始单圈文件（35,609,412 字节）。删除日志为 deletion-record.json。保留上海、铃鹿自录、现有模型、训练导出以及已生成赛道配置。旧社区 manifest 为来源历史，DOWNLOAD_STATUS.json 已标明原文件删除。',
        'raw/*.f1pcap.gz 为源文件的逐字节无损 gzip 归档，旁边的 .json 保存来源、原始 SHA-256 和大小。gzip 解压后的文件仍是提供方 .f1pcap；不是直接供现有 CaptureJsonlSource 使用的 JSONL。','',
        '继续下载需增加可用空间或指定有空间的目录。即使将当前来源的 25 个文件全部下载，也不能据此宣称全赛道完整覆盖；未取得的文件仍需逐一按包头和内容验收。','',
        '## 来源与复现','',
        '- [Pits n’ Giggles 公共录制文件夹](https://drive.google.com/drive/folders/13tIadKMvi3kuItkovT6GUTTHOL3YM6n_)',
        '- [提供方集成测试](https://github.com/ashwin-nat/pits-n-giggles/tree/main/tests/integration_test)',
        '- source-evidence 保存本次来源快照、仓库树及 GitHub 搜索记录；没有执行下载来的程序。',
        '- download_recordings.py：限空间下载、gzip 压缩及还原哈希检查。',
        '- audit_recordings.py：流式读取容器及字段检查，不发出 UDP、不运行模型。',
        '- coverage.json / coverage.csv：机器可读覆盖矩阵；audits/：逐文件及逐 session 的检查结果。',
        '- 本次没有启动训练、替换模型、宣称模型质量或实时游戏验收通过。','']
    (ROOT/'全赛道覆盖报告.md').write_text('\n'.join(lines))
    print(json.dumps({k:v for k,v in result.items() if k not in {'layouts','pending_downloads','failed_downloads'}},ensure_ascii=False))

if __name__=='__main__':main()
