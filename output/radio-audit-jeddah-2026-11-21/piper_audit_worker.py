from pathlib import Path
import sys,json,re
from piper import PiperVoice,SynthesisConfig
import numpy as np
# Same model, phoneme dictionary, synthesis settings and PCM scale as the baseline.
v=PiperVoice.load('/tmp/asurada-piper-CA8rJL/zh_CN-chaowen-medium.onnx')
phonemes=v.config.phoneme_id_map
chars={}
for line in '''
守shou3 直zhi2 道dao4 尽jin4 头tou2 主zhu3 找zhao3 机ji1 会hui4 长chang2 防fang2 前qian2 后hou4 面mian4
对dui4 手shou3 是shi4 还hai2 在zai4 追zhui1 近jin4 逼bi1 又you4 上shang4 来lai2 了le5 车che1 你ni3
伤shang1 程cheng2 轮lun2 抓zhua1 地di4 下xia4 降jiang4 到dao4
收shou1 油you2 速su4 公gong1 里li3 每mei3 小xiao3 时shi2 至zhi4 参can1 考kao3
赛sai4 恩en1 莱lai2 塔ta3 端duan1 努nu3 克ke4 力li4 达da2
劳lao2 森sen1 阿a1 尔er3 本ben3 霍huo4 肯ken3 伯bo2 格ge2 斯si1 特te4 罗luo2 加jia1 利li4
科ke1 拉la1 平ping2 托tuo1 比bi3 曼man4 安an1 东dong1 内nei4 皮pi2 亚ya4 克ke4 夏xia4
汉han4 密mi4 顿dun4 勒le4 维wei2 塞sai4 纳na4 诺nuo4 里li3 博bo2 弗fu2 潘pan1
百bai3 分fen1 之zhi1 二er4 三san1 四si4 五wu3 六liu4 七qi1 八ba1 九jiu3 十shi2 零ling2 再zai4 慢man4
左zuo3 右you4 两liang3 侧ce4 受shou4 损sun3 入ru4 能neng2 推tui1 跑pao3 宽kuan1 多duo1 减jian3 点dian3 速su4 度du4 顺shun4 转zhuan3 向xiang4
条tiao2 末mo4 端duan1 的de5 早zao3 刹sha1 小xiao3 心xin1 方fang1 向xiang4 打da3 卡ka3 尼ni2 管guan3 理li3 胎tai1
奥ao4 康kang1 哈ha1 达da2 角jiao3 田tian2 裕yu4 毅yi4 一yi1 号hao4 弯wan1 子zi3
可ke3 以yi3 用yong4 尾wei3 翼yi4 黄huang2 旗qi2 这zhe4 段duan4 已yi3 经jing1 并bing4 排pai2 次ci4 没mei2 过guo4
超chao1 去qu4 位wei4 置zhi4 确que4 认ren4 先xian1 别bie2 攻gong1 窗chuang1 口kou3 关guan1
动dong4 态tai4 不bu4 稳wen3 定ding4 住zhu4 跟gen1 准zhun3 备bei4 进jin4 刚gang1 才cai2 那na4 遥yao2 测ce4 足zu2 结jie2 果guo3
漂piao4 亮liang4 节jie2 奏zou4 很hen3 好hao3 成cheng2 功gong1 完wan2 干gan4 得de5 他ta1 后hou4 茨ci2 赫he4
'''.split():chars[line[0]]=line[1:]
chars.update({x[0]:x[1:] for x in '快kuai4 线xian4 内nei4 外wai4 卡ka3 位wei4 侧ce4 稳wen3 保bao3 持chi2 别bie2 口kou3 退tui4 让rang4 追zhui1 逼bi1 低di1 落luo4 后hou4 米mi3 秒miao3 没mei2 划hua2 算suan4 撤che4 回hui2 硬ying4 中zhong1 留liu2 兴xing1 进jin4 站zhan4 格ge2 控kong4 制zhi4'.split()})
for request in sys.stdin:
 try:
  txt,path=json.loads(request);ids=list(phonemes['^'])
  for ch in txt:
   if ch in '，。、': seq=[ch]
   elif ch.isspace():continue
   else:
    syl=chars[ch];m=re.fullmatch('(zh|ch|sh|[bpmfdtnlgkhjqxrzcsyw])?(.*)([1-5])',syl);ini,final,tone=m.groups()
    seq=[ini or 'Ø',final,tone]
   for token in seq:ids.extend(phonemes[token])
   ids.extend(phonemes['_'])
  ids.extend(phonemes['$'])
  samples=v.phoneme_ids_to_audio(ids,SynthesisConfig(noise_scale=0,noise_w_scale=0))
  (samples.clip(-1,1)*32767).round().astype('<i2').tofile(path);print('ok',flush=True)
 except Exception as e:print(repr(e),flush=True)
